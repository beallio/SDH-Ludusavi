from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdh_ludusavi.launch_gate import (
    ScopeDiscoveryError,
    ScopeNotReadyError,
    SteamAppScope,
    SystemdScopeController,
)


UID = os.geteuid()
PID = 12992
UNIT = "app-steam-app3156562597-12992.scope"


class FakeClock:
    def __init__(self) -> None:
        self.now = 10.0
        self.waits = 0
        self.on_wait = None

    def monotonic(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.waits += 1
        self.now += seconds
        if self.on_wait is not None:
            self.on_wait()


class ScopeFixture:
    def __init__(self, tmp_path: Path) -> None:
        self.proc_root = tmp_path / "proc"
        self.cgroup_root = tmp_path / "cgroup"
        self.proc_dir = self.proc_root / str(PID)
        self.relative = Path(f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/{UNIT}")
        self.launcher_relative = Path(
            f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/steam-launcher.service"
        )
        self.scope_dir = self.cgroup_root / self.relative
        self.proc_dir.mkdir(parents=True)
        self.scope_dir.mkdir(parents=True)
        (self.proc_dir / "cgroup").write_text(f"0::/{self.relative.as_posix()}\n")
        self.set_process_identity()
        self.set_state(0, 0)

    def set_process_identity(
        self,
        *,
        start_ticks: int = 987654,
        command: str = "game (bootstrap) process",
    ) -> None:
        fields_after_command = ["S", *("0" for _ in range(18)), str(start_ticks)]
        (self.proc_dir / "stat").write_text(
            f"{PID} ({command}) {' '.join(fields_after_command)}\n",
            encoding="utf-8",
        )

    def set_scope_not_ready(self) -> None:
        parent = self.relative.parent
        (self.proc_dir / "cgroup").write_text(f"0::/{parent.as_posix()}\n", encoding="utf-8")

    def set_launcher_scope_not_ready(self) -> None:
        (self.proc_dir / "cgroup").write_text(
            f"0::/{self.launcher_relative.as_posix()}\n", encoding="utf-8"
        )

    def set_state(self, requested: int, completed: int) -> None:
        (self.scope_dir / "cgroup.freeze").write_text(f"{requested}\n")
        (self.scope_dir / "cgroup.events").write_text(f"populated 1\nfrozen {completed}\n")

    def controller(self, **kwargs: object) -> SystemdScopeController:
        return SystemdScopeController(
            proc_root=self.proc_root,
            cgroup_root=self.cgroup_root,
            uid=UID,
            **kwargs,
        )


@pytest.fixture
def scope_fs(tmp_path: Path) -> ScopeFixture:
    return ScopeFixture(tmp_path)


def test_discover_valid_unified_steam_app_scope(scope_fs: ScopeFixture) -> None:
    scope = scope_fs.controller().discover(PID)

    assert scope == SteamAppScope(
        unit=UNIT,
        cgroup_path=f"/{scope_fs.relative.as_posix()}",
        device=scope_fs.scope_dir.stat().st_dev,
        inode=scope_fs.scope_dir.stat().st_ino,
        root_pid=PID,
    )


@pytest.mark.parametrize("pid", [True, 1, 0, -1, 2_147_483_648])
def test_discover_rejects_unsafe_pid(scope_fs: ScopeFixture, pid: object) -> None:
    with pytest.raises(ScopeDiscoveryError, match="PID"):
        scope_fs.controller().discover(pid)


def test_discover_rejects_wrong_owner(scope_fs: ScopeFixture) -> None:
    with pytest.raises(ScopeDiscoveryError, match="owner"):
        SystemdScopeController(
            proc_root=scope_fs.proc_root,
            cgroup_root=scope_fs.cgroup_root,
            uid=UID + 1,
        ).discover(PID)


@pytest.mark.parametrize(
    "content",
    [
        "2:cpu:/user.slice/example\n",
        "0:name=systemd:/user.slice/example\n",
        "not-a-cgroup-entry\n",
        "0::relative/path\n",
        "0::/user.slice/one\n0::/user.slice/two\n",
    ],
)
def test_discover_rejects_malformed_or_non_unified_cgroup(
    scope_fs: ScopeFixture, content: str
) -> None:
    (scope_fs.proc_dir / "cgroup").write_text(content)

    with pytest.raises(ScopeDiscoveryError, match="unified cgroup"):
        scope_fs.controller().discover(PID)


@pytest.mark.parametrize(
    "relative",
    [
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice",
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/not-steam.scope",
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/{UNIT}/child",
        f"user.slice/user-{UID}.slice/user@{UID}.service/../app.slice/{UNIT}",
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/../../{UNIT}",
        f"system.slice/{UNIT}",
    ],
)
def test_discover_rejects_non_exact_or_traversing_scope(
    scope_fs: ScopeFixture, relative: str
) -> None:
    (scope_fs.proc_dir / "cgroup").write_text(f"0::/{relative}\n")

    with pytest.raises(ScopeDiscoveryError, match="Steam app scope"):
        scope_fs.controller().discover(PID)


def test_discover_rejects_symlink_escape(scope_fs: ScopeFixture, tmp_path: Path) -> None:
    outside = tmp_path / "outside" / UNIT
    outside.mkdir(parents=True)
    (outside / "cgroup.freeze").write_text("0\n")
    (outside / "cgroup.events").write_text("frozen 0\n")
    scope_fs.scope_dir.rename(scope_fs.scope_dir.with_name("original"))
    scope_fs.scope_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ScopeDiscoveryError, match="cgroup root"):
        scope_fs.controller().discover(PID)


@pytest.mark.parametrize("missing", ["cgroup.freeze", "cgroup.events"])
def test_discover_requires_freezer_state_files(scope_fs: ScopeFixture, missing: str) -> None:
    (scope_fs.scope_dir / missing).unlink()

    with pytest.raises(ScopeDiscoveryError, match="freezer state"):
        scope_fs.controller().discover(PID)


@pytest.mark.parametrize("filename", ["cgroup", "cgroup.freeze", "cgroup.events"])
def test_discover_bounds_invalid_utf8(scope_fs: ScopeFixture, filename: str) -> None:
    target = scope_fs.proc_dir / filename if filename == "cgroup" else scope_fs.scope_dir / filename
    target.write_bytes(b"\xff")

    with pytest.raises(ScopeDiscoveryError):
        scope_fs.controller().discover(PID)


def test_discover_bounds_path_resolution_runtime_error(
    scope_fs: ScopeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_resolve = Path.resolve

    def failing_resolve(path: Path, strict: bool = False) -> Path:
        if path == scope_fs.cgroup_root:
            raise RuntimeError("synthetic symlink loop")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", failing_resolve)

    with pytest.raises(ScopeDiscoveryError, match="unavailable"):
        scope_fs.controller().discover(PID)


def test_freeze_uses_exact_bounded_systemctl_command_and_default_bus(
    scope_fs: ScopeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = scope_fs.controller(command_runner=runner)
    result = controller.freeze(controller.discover(PID))

    assert result.success is True
    assert calls[0][0] == ["systemctl", "--user", "freeze", UNIT]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True
    assert isinstance(calls[0][1]["timeout"], float)
    env = calls[0][1]["env"]
    assert isinstance(env, dict)
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{UID}"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path=/run/user/{UID}/bus"


def test_command_environment_preserves_existing_bus_values(
    scope_fs: ScopeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/provided/runtime")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/provided/bus")

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs["env"])
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = scope_fs.controller(command_runner=runner)
    assert controller.freeze(controller.discover(PID)).success
    assert captured["XDG_RUNTIME_DIR"] == "/provided/runtime"
    assert captured["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/provided/bus"


def test_command_environment_clears_private_library_path_without_mutating_caller(
    scope_fs: ScopeFixture,
) -> None:
    supplied = {
        "LD_LIBRARY_PATH": "/tmp/_MEI-test",
        "XDG_RUNTIME_DIR": "/provided/runtime",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/provided/bus",
    }
    captured: dict[str, str] = {}

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs["env"])
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = scope_fs.controller(command_runner=runner, environ=supplied)

    assert controller.freeze(controller.discover(PID)).success
    assert captured["LD_LIBRARY_PATH"] == ""
    assert captured["XDG_RUNTIME_DIR"] == "/provided/runtime"
    assert captured["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/provided/bus"
    assert supplied["LD_LIBRARY_PATH"] == "/tmp/_MEI-test"


def test_inherited_private_library_path_is_cleared_only_in_child_environment(
    scope_fs: ScopeFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI-inherited")

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs["env"])
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = scope_fs.controller(command_runner=runner)

    assert controller.freeze(controller.discover(PID)).success
    assert captured["LD_LIBRARY_PATH"] == ""
    assert os.environ["LD_LIBRARY_PATH"] == "/tmp/_MEI-inherited"


def test_freeze_waits_for_requested_and_completed_state(scope_fs: ScopeFixture) -> None:
    clock = FakeClock()

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        scope_fs.set_state(1, 0)
        return subprocess.CompletedProcess(argv, 0, "", "")

    clock.on_wait = lambda: scope_fs.set_state(1, 1)
    controller = scope_fs.controller(
        command_runner=runner,
        monotonic=clock.monotonic,
        wait=clock.wait,
        transition_timeout_seconds=0.2,
    )

    result = controller.freeze(controller.discover(PID))

    assert result.success is True
    assert clock.waits == 1


def test_freeze_failure_best_effort_thaws_partial_transition(scope_fs: ScopeFixture) -> None:
    calls: list[list[str]] = []
    clock = FakeClock()

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[2] == "freeze":
            scope_fs.set_state(1, 0)
        else:
            scope_fs.set_state(0, 0)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = scope_fs.controller(
        command_runner=runner,
        monotonic=clock.monotonic,
        wait=clock.wait,
        transition_timeout_seconds=0.05,
    )

    result = controller.freeze(controller.discover(PID))

    assert result.success is False
    assert "timed out" in result.reason
    assert calls == [
        ["systemctl", "--user", "freeze", UNIT],
        ["systemctl", "--user", "thaw", UNIT],
    ]
    assert (scope_fs.scope_dir / "cgroup.freeze").read_text().strip() == "0"


def test_freeze_invalid_state_bytes_fail_bounded_and_best_effort_thaw(
    scope_fs: ScopeFixture,
) -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[2] == "freeze":
            (scope_fs.scope_dir / "cgroup.freeze").write_bytes(b"\xff")
        else:
            scope_fs.set_state(0, 0)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = scope_fs.controller(command_runner=runner)
    result = controller.freeze(controller.discover(PID))

    assert result.success is False
    assert result.reason == "Malformed or unreadable cgroup freezer state"
    assert calls == [
        ["systemctl", "--user", "freeze", UNIT],
        ["systemctl", "--user", "thaw", UNIT],
    ]


def test_transition_bounds_path_resolution_runtime_error(
    scope_fs: ScopeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    controller = scope_fs.controller(
        command_runner=lambda argv, **kwargs: calls.append(argv)  # type: ignore[arg-type]
    )
    scope = controller.discover(PID)
    original_resolve = Path.resolve

    def failing_resolve(path: Path, strict: bool = False) -> Path:
        if path == scope_fs.cgroup_root:
            raise RuntimeError("synthetic symlink loop")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", failing_resolve)

    result = controller.freeze(scope)

    assert result.success is False
    assert result.reason == "Steam app scope path is invalid"
    assert calls == []


@pytest.mark.parametrize("failure", ["missing", "timeout", "nonzero"])
def test_transition_command_failures_are_bounded(scope_fs: ScopeFixture, failure: str) -> None:
    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if failure == "missing":
            raise FileNotFoundError("systemctl")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], stderr="secret\nsecond")
        return subprocess.CompletedProcess(argv, 1, "", "x" * 1000 + "\nsecond")

    result = scope_fs.controller(command_runner=runner).freeze(scope_fs.controller().discover(PID))

    assert result.success is False
    assert len(result.reason) <= 240
    assert "\n" not in result.reason


def test_thaw_waits_for_zero_requested_and_completed_state(scope_fs: ScopeFixture) -> None:
    scope_fs.set_state(1, 1)
    clock = FakeClock()

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        scope_fs.set_state(0, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    clock.on_wait = lambda: scope_fs.set_state(0, 0)
    controller = scope_fs.controller(
        command_runner=runner,
        monotonic=clock.monotonic,
        wait=clock.wait,
        transition_timeout_seconds=0.2,
    )
    scope = controller.discover(PID)

    result = controller.thaw(scope)

    assert result.success is True
    assert result.disappeared is False
    assert clock.waits == 1


def test_thaw_treats_identity_checked_disappearance_as_idempotent(
    scope_fs: ScopeFixture,
) -> None:
    scope_fs.set_state(1, 1)

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        scope_fs.scope_dir.rename(scope_fs.scope_dir.with_name("gone"))
        return subprocess.CompletedProcess(argv, 1, "", "unit vanished")

    controller = scope_fs.controller(command_runner=runner)
    result = controller.thaw(controller.discover(PID))

    assert result.success is True
    assert result.disappeared is True


def test_stale_scope_identity_is_rejected_without_running_systemctl(
    scope_fs: ScopeFixture,
) -> None:
    calls: list[list[str]] = []
    controller = scope_fs.controller(
        command_runner=lambda argv, **kwargs: calls.append(argv)  # type: ignore[arg-type]
    )
    scope = controller.discover(PID)
    scope_fs.scope_dir.rename(scope_fs.scope_dir.with_name("old"))
    scope_fs.scope_dir.mkdir()
    scope_fs.set_state(1, 1)

    result = controller.thaw(scope)

    assert result.success is False
    assert "identity" in result.reason
    assert calls == []


def test_late_process_joining_frozen_scope_remains_covered(scope_fs: ScopeFixture) -> None:
    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = scope_fs.controller(command_runner=runner)
    scope = controller.discover(PID)
    assert controller.freeze(scope).success
    (scope_fs.scope_dir / "cgroup.procs").write_text(f"{PID}\n13305\n13311\n")

    assert controller.freeze_requested(scope) is True
    assert controller.wait_for_frozen(scope, expected=True).success is True


def _acquisition_types():
    from sdh_ludusavi.launch_gate_acquire import LaunchScopeAcquirer, ScopeAcquisitionResult

    return LaunchScopeAcquirer, ScopeAcquisitionResult


def _signal_name(value: int) -> str:
    return signal.Signals(value).name


def test_scope_not_ready_is_the_only_retryable_discovery_state(
    scope_fs: ScopeFixture,
) -> None:
    scope_fs.set_scope_not_ready()
    with pytest.raises(ScopeNotReadyError):
        scope_fs.controller().discover(PID)

    (scope_fs.proc_dir / "cgroup").write_text("0::/system.slice/not-steam.scope\n")
    with pytest.raises(ScopeDiscoveryError) as malformed:
        scope_fs.controller().discover(PID)
    assert not isinstance(malformed.value, ScopeNotReadyError)


def test_exact_steam_launcher_service_is_retryable_without_systemd_transition(
    scope_fs: ScopeFixture,
) -> None:
    commands: list[list[str]] = []
    scope_fs.set_launcher_scope_not_ready()

    with pytest.raises(ScopeNotReadyError):
        scope_fs.controller(
            command_runner=lambda argv, **kwargs: commands.append(argv)  # type: ignore[arg-type]
        ).discover(PID)

    assert commands == []


def test_launcher_service_handoff_stops_then_freezes_exact_scope_then_releases(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    clock = FakeClock()
    events: list[str] = []
    scope_fs.set_launcher_scope_not_ready()

    def wait(seconds: float) -> None:
        events.append("wait")
        clock.wait(seconds)
        (scope_fs.proc_dir / "cgroup").write_text(
            f"0::/{scope_fs.relative.as_posix()}\n", encoding="utf-8"
        )

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv[2:] == ["freeze", UNIT]
        events.append("freeze")
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def send(pid: int, sig: int) -> None:
        assert pid == PID
        if sig == signal.SIGCONT:
            assert (scope_fs.scope_dir / "cgroup.freeze").read_text().strip() == "1"
            assert "frozen 1" in (scope_fs.scope_dir / "cgroup.events").read_text()
        events.append(_signal_name(sig))

    controller = scope_fs.controller(command_runner=runner)
    acquired = LaunchScopeAcquirer(
        controller,
        signal_sender=send,
        proc_root=scope_fs.proc_root,
        uid=UID,
        monotonic=clock.monotonic,
        wait=wait,
        acquisition_timeout_seconds=0.2,
    ).acquire(PID)

    assert acquired.success is True
    assert acquired.scope is not None
    assert acquired.scope.unit == UNIT
    assert acquired.scope.cgroup_path == f"/{scope_fs.relative.as_posix()}"
    assert events == ["SIGSTOP", "wait", "freeze", "SIGCONT"]


def test_launcher_service_handoff_timeout_is_bounded_and_releases_original_pid(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    clock = FakeClock()
    signals: list[int] = []
    commands: list[list[str]] = []
    scope_fs.set_launcher_scope_not_ready()

    result = LaunchScopeAcquirer(
        scope_fs.controller(
            command_runner=lambda argv, **kwargs: commands.append(argv)  # type: ignore[arg-type]
        ),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
        monotonic=clock.monotonic,
        wait=clock.wait,
        acquisition_timeout_seconds=0.05,
        poll_seconds=0.02,
    ).acquire(PID)

    assert result.success is False
    assert "timed out" in result.reason.casefold()
    assert len(result.reason) <= 180
    assert clock.waits == 3
    assert signals == [signal.SIGSTOP, signal.SIGCONT]
    assert commands == []


@pytest.mark.parametrize(
    "relative",
    [
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/other.service",
        f"user.slice/user-{UID + 1}.slice/user@{UID + 1}.service/app.slice/steam-launcher.service",
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/steam-launcher.service/child",
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/steam-launcher.service.scope",
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/steam_launcher.service",
        f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice/../app.slice/steam-launcher.service",
    ],
)
def test_launcher_service_near_misses_are_immediate_hard_failures(
    scope_fs: ScopeFixture,
    relative: str,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    waits: list[float] = []
    signals: list[int] = []
    commands: list[list[str]] = []
    (scope_fs.proc_dir / "cgroup").write_text(f"0::/{relative}\n", encoding="utf-8")

    result = LaunchScopeAcquirer(
        scope_fs.controller(
            command_runner=lambda argv, **kwargs: commands.append(argv)  # type: ignore[arg-type]
        ),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
        wait=waits.append,
    ).acquire(PID)

    assert result.success is False
    assert waits == []
    assert signals == [signal.SIGSTOP, signal.SIGCONT]
    assert commands == []


def test_delayed_scope_acquisition_stops_then_freezes_then_releases(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    clock = FakeClock()
    events: list[str] = []
    scope_fs.set_scope_not_ready()

    def wait(seconds: float) -> None:
        events.append("wait")
        clock.wait(seconds)
        (scope_fs.proc_dir / "cgroup").write_text(
            f"0::/{scope_fs.relative.as_posix()}\n", encoding="utf-8"
        )

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        events.append(argv[2])
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def send(pid: int, sig: int) -> None:
        assert pid == PID
        if sig == signal.SIGCONT:
            assert (scope_fs.scope_dir / "cgroup.freeze").read_text().strip() == "1"
            assert "frozen 1" in (scope_fs.scope_dir / "cgroup.events").read_text()
        events.append(_signal_name(sig))

    controller = scope_fs.controller(command_runner=runner)
    acquirer = LaunchScopeAcquirer(
        controller,
        signal_sender=send,
        proc_root=scope_fs.proc_root,
        uid=UID,
        monotonic=clock.monotonic,
        wait=wait,
        acquisition_timeout_seconds=0.2,
    )

    acquired = acquirer.acquire(PID)

    assert acquired.success is True
    assert acquired.scope is not None
    assert acquired.scope.unit == UNIT
    assert events == ["SIGSTOP", "wait", "freeze", "SIGCONT"]
    assert controller.freeze_requested(acquired.scope)
    assert controller.wait_for_frozen(acquired.scope, expected=True).success


def test_immediate_scope_acquisition_has_no_execution_window(scope_fs: ScopeFixture) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    events: list[str] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        events.append(argv[2])
        scope_fs.set_state(1, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def send(pid: int, sig: int) -> None:
        if sig == signal.SIGCONT:
            assert events == ["SIGSTOP", "freeze"]
            assert (scope_fs.scope_dir / "cgroup.freeze").read_text().strip() == "1"
        events.append(_signal_name(sig))

    result = LaunchScopeAcquirer(
        scope_fs.controller(command_runner=runner),
        signal_sender=send,
        proc_root=scope_fs.proc_root,
        uid=UID,
    ).acquire(PID)

    assert result.success is True
    assert events == ["SIGSTOP", "freeze", "SIGCONT"]


def test_scope_acquisition_timeout_is_bounded_and_releases_original_pid(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    clock = FakeClock()
    signals: list[int] = []
    scope_fs.set_scope_not_ready()

    result = LaunchScopeAcquirer(
        scope_fs.controller(),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
        monotonic=clock.monotonic,
        wait=clock.wait,
        acquisition_timeout_seconds=0.05,
        poll_seconds=0.02,
    ).acquire(PID)

    assert result.success is False
    assert "timed out" in result.reason.casefold()
    assert len(result.reason) <= 180
    assert signals == [signal.SIGSTOP, signal.SIGCONT]


@pytest.mark.parametrize(
    "cgroup_text",
    [
        "not-a-cgroup-entry\n",
        "0::/system.slice/not-steam.scope\n",
        f"0::/user.slice/user-{UID}.slice/user@{UID}.service/app.slice/{UNIT}/child\n",
    ],
)
def test_scope_acquisition_does_not_retry_invalid_membership(
    scope_fs: ScopeFixture,
    cgroup_text: str,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    signals: list[int] = []
    waits: list[float] = []
    (scope_fs.proc_dir / "cgroup").write_text(cgroup_text)

    result = LaunchScopeAcquirer(
        scope_fs.controller(),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
        wait=waits.append,
    ).acquire(PID)

    assert result.success is False
    assert waits == []
    assert signals == [signal.SIGSTOP, signal.SIGCONT]


def test_scope_acquisition_rejects_wrong_owner_before_signaling(scope_fs: ScopeFixture) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    signals: list[int] = []

    result = LaunchScopeAcquirer(
        scope_fs.controller(),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID + 1,
    ).acquire(PID)

    assert result.success is False
    assert "owner" in result.reason.casefold()
    assert signals == []


@pytest.mark.parametrize("replacement", ["reuse", "exit"])
def test_scope_acquisition_never_resumes_replaced_or_exited_pid(
    scope_fs: ScopeFixture,
    replacement: str,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    clock = FakeClock()
    signals: list[int] = []
    scope_fs.set_scope_not_ready()

    def replace_process() -> None:
        if replacement == "reuse":
            scope_fs.set_process_identity(start_ticks=987655)
        else:
            (scope_fs.proc_dir / "stat").unlink()

    clock.on_wait = replace_process
    result = LaunchScopeAcquirer(
        scope_fs.controller(),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
        monotonic=clock.monotonic,
        wait=clock.wait,
        acquisition_timeout_seconds=0.2,
    ).acquire(PID)

    assert result.success is False
    assert any(word in result.reason.casefold() for word in ("identity", "exited"))
    assert signals == [signal.SIGSTOP]


def test_scope_acquisition_handles_stop_signal_failure_without_cleanup_signal(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    signals: list[int] = []

    def send(pid: int, sig: int) -> None:
        signals.append(sig)
        raise OSError("signal unavailable")

    result = LaunchScopeAcquirer(
        scope_fs.controller(), signal_sender=send, proc_root=scope_fs.proc_root, uid=UID
    ).acquire(PID)

    assert result.success is False
    assert "signal" in result.reason.casefold()
    assert signals == [signal.SIGSTOP]


def test_scope_acquisition_continue_signal_failure_retries_cleanup_and_reports_failure(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    signals: list[int] = []
    commands: list[str] = []

    def send(pid: int, sig: int) -> None:
        signals.append(sig)
        if sig == signal.SIGCONT:
            raise OSError("continue signal unavailable")

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(argv[2])
        scope_fs.set_state(1, 1) if argv[2] == "freeze" else scope_fs.set_state(0, 0)
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = LaunchScopeAcquirer(
        scope_fs.controller(command_runner=runner),
        signal_sender=send,
        proc_root=scope_fs.proc_root,
        uid=UID,
    ).acquire(PID)

    assert result.success is False
    assert "continue signal unavailable" in result.reason
    assert "Unable to release bootstrap signal" in result.reason
    assert signals == [signal.SIGSTOP, signal.SIGCONT, signal.SIGCONT]
    assert commands == ["freeze", "thaw"]


def test_same_scope_sigcont_failure_preserves_existing_frozen_lease(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    existing_scope = scope_fs.controller().discover(PID)
    scope_fs.set_state(1, 1)
    thaw_calls: list[SteamAppScope] = []
    signals: list[int] = []

    class Controller:
        def discover(self, pid: int) -> SteamAppScope:
            return existing_scope

        def freeze(self, target: SteamAppScope):
            raise AssertionError("same-scope acquisition must not freeze again")

        def freeze_requested(self, target: SteamAppScope) -> bool:
            return True

        def wait_for_frozen(self, target: SteamAppScope, expected: bool):
            return SimpleNamespace(success=True, reason="")

        def thaw(self, target: SteamAppScope):
            thaw_calls.append(target)
            return SimpleNamespace(success=True, reason="")

    def send(pid: int, sig: int) -> None:
        signals.append(sig)
        if sig == signal.SIGCONT and signals.count(signal.SIGCONT) == 1:
            raise OSError("continue signal unavailable")

    result = LaunchScopeAcquirer(
        Controller(),
        signal_sender=send,
        proc_root=scope_fs.proc_root,
        uid=UID,
    ).acquire(PID, existing_scope=existing_scope)

    assert result.success is False
    assert signals == [signal.SIGSTOP, signal.SIGCONT, signal.SIGCONT]
    assert thaw_calls == []


def test_same_scope_post_handoff_failure_preserves_existing_frozen_lease(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    existing_scope = scope_fs.controller().discover(PID)
    freeze_checks = iter([True, False])
    thaw_calls: list[SteamAppScope] = []

    class Controller:
        def discover(self, pid: int) -> SteamAppScope:
            return existing_scope

        def freeze(self, target: SteamAppScope):
            raise AssertionError("same-scope acquisition must not freeze again")

        def freeze_requested(self, target: SteamAppScope) -> bool:
            return next(freeze_checks)

        def wait_for_frozen(self, target: SteamAppScope, expected: bool):
            return SimpleNamespace(success=True, reason="")

        def thaw(self, target: SteamAppScope):
            thaw_calls.append(target)
            return SimpleNamespace(success=True, reason="")

    result = LaunchScopeAcquirer(
        Controller(),
        signal_sender=lambda pid, sig: None,
        proc_root=scope_fs.proc_root,
        uid=UID,
    ).acquire(PID, existing_scope=existing_scope)

    assert result.success is False
    assert "handoff" in result.reason.casefold()
    assert thaw_calls == []


def test_scope_acquisition_freeze_failure_thaws_and_releases_pid(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    signals: list[int] = []
    commands: list[str] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(argv[2])
        if argv[2] == "thaw":
            scope_fs.set_state(0, 0)
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 1, "", "manager failed")

    result = LaunchScopeAcquirer(
        scope_fs.controller(command_runner=runner),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
    ).acquire(PID)

    assert result.success is False
    assert "systemctl freeze failed" in result.reason
    assert commands == ["freeze", "thaw"]
    assert signals == [signal.SIGSTOP, signal.SIGCONT]


def test_scope_acquisition_freezer_verification_failure_releases_pid(
    scope_fs: ScopeFixture,
) -> None:
    LaunchScopeAcquirer, _ = _acquisition_types()
    clock = FakeClock()
    signals: list[int] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        scope_fs.set_state(1, 0) if argv[2] == "freeze" else scope_fs.set_state(0, 0)
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = LaunchScopeAcquirer(
        scope_fs.controller(
            command_runner=runner,
            monotonic=clock.monotonic,
            wait=clock.wait,
            transition_timeout_seconds=0.05,
        ),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
    ).acquire(PID)

    assert result.success is False
    assert "verification timed out" in result.reason
    assert signals == [signal.SIGSTOP, signal.SIGCONT]


def test_scope_acquisition_post_handoff_failure_thaws_once(scope_fs: ScopeFixture) -> None:
    LaunchScopeAcquirer, ScopeAcquisitionResult = _acquisition_types()
    scope = scope_fs.controller().discover(PID)

    class Controller:
        def __init__(self) -> None:
            self.thaw_calls: list[object] = []

        def discover(self, pid: int) -> SteamAppScope:
            return scope

        def freeze(self, target: SteamAppScope):
            return SimpleNamespace(success=True, reason="")

        def freeze_requested(self, target: SteamAppScope) -> bool:
            return False

        def wait_for_frozen(self, target: SteamAppScope, expected: bool):
            return SimpleNamespace(success=False, reason="scope thawed during handoff")

        def thaw(self, target: SteamAppScope):
            self.thaw_calls.append(target)
            return SimpleNamespace(success=True, reason="")

    controller = Controller()
    signals: list[int] = []
    result = LaunchScopeAcquirer(
        controller,
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=scope_fs.proc_root,
        uid=UID,
    ).acquire(PID)

    assert isinstance(result, ScopeAcquisitionResult)
    assert result.success is False
    assert "handoff" in result.reason.casefold()
    assert signals == [signal.SIGSTOP, signal.SIGCONT]
    assert controller.thaw_calls == [scope]


def test_synthetic_conflict_launch_stays_frozen_until_one_verified_thaw(
    scope_fs: ScopeFixture,
) -> None:
    from sdh_ludusavi.launch_gate_acquire import LaunchScopeAcquirer
    from sdh_ludusavi.watchdog import ProcessWatchdog

    clock = FakeClock()
    events: list[str] = []
    captured_environment: dict[str, str] = {}
    scope_fs.set_scope_not_ready()

    def wait(seconds: float) -> None:
        events.append("scope_not_ready")
        clock.wait(seconds)
        (scope_fs.proc_dir / "cgroup").write_text(
            f"0::/{scope_fs.relative.as_posix()}\n", encoding="utf-8"
        )

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        action = argv[2]
        events.append(action)
        captured_environment.update(kwargs["env"])
        scope_fs.set_state(1, 1) if action == "freeze" else scope_fs.set_state(0, 0)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def send(pid: int, sig: int) -> None:
        events.append(_signal_name(sig))
        if sig == signal.SIGCONT:
            assert (scope_fs.scope_dir / "cgroup.freeze").read_text().strip() == "1"

    controller = scope_fs.controller(
        command_runner=runner,
        environ={
            "LD_LIBRARY_PATH": "/tmp/_MEI-synthetic",
            "XDG_RUNTIME_DIR": "/run/user/test",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/test/bus",
        },
    )
    acquirer = LaunchScopeAcquirer(
        controller,
        signal_sender=send,
        proc_root=scope_fs.proc_root,
        uid=UID,
        monotonic=clock.monotonic,
        wait=wait,
    )
    watchdog = ProcessWatchdog(
        lambda *args: None,
        scope_controller=controller,
        scope_acquirer=acquirer,
        monotonic=clock.monotonic,
    )
    watchdog._ensure_watchdog_running = lambda: None  # type: ignore[method-assign]

    paused = watchdog.pause(PID)
    assert paused["status"] == "paused"
    assert (scope_fs.scope_dir / "cgroup.freeze").read_text().strip() == "1"
    events.extend(["conflict_detected", "restore_selected"])
    assert watchdog.resume(PID, paused["lease_id"]) == {"status": "resumed", "pid": PID}

    assert events == [
        "SIGSTOP",
        "scope_not_ready",
        "freeze",
        "SIGCONT",
        "conflict_detected",
        "restore_selected",
        "thaw",
    ]
    assert captured_environment["LD_LIBRARY_PATH"] == ""
    assert (scope_fs.scope_dir / "cgroup.freeze").read_text().strip() == "0"
