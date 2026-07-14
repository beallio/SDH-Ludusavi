from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sdh_ludusavi.launch_gate import (
    ScopeDiscoveryError,
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
        self.scope_dir = self.cgroup_root / self.relative
        self.proc_dir.mkdir(parents=True)
        self.scope_dir.mkdir(parents=True)
        (self.proc_dir / "cgroup").write_text(f"0::/{self.relative.as_posix()}\n")
        self.set_state(0, 0)

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
