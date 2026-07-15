from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SYSTEMCTL_TIMEOUT_SECONDS = 3.0
FREEZER_TRANSITION_TIMEOUT_SECONDS = 1.0
FREEZER_POLL_SECONDS = 0.02
MAX_PID = 2_147_483_647
MAX_REASON_LENGTH = 180
_UNIT_RE = re.compile(r"app-steam-app[0-9]+-[0-9]+\.scope\Z")
_STEAM_LAUNCHER_UNIT = "steam-launcher.service"


class ScopeDiscoveryError(ValueError):
    """The launch PID cannot be mapped to a safe Steam app scope."""


class ScopeNotReadyError(ScopeDiscoveryError):
    """The launch PID is in an exact allowed pre-app-scope handoff path."""


@dataclass(frozen=True)
class SteamAppScope:
    unit: str
    cgroup_path: str
    device: int
    inode: int
    root_pid: int


@dataclass(frozen=True)
class ScopeTransitionResult:
    success: bool
    reason: str = ""
    disappeared: bool = False


class SystemdScopeController:
    """Discovers and transitions one exact Steam app cgroup through user systemd."""

    def __init__(
        self,
        *,
        proc_root: str | Path = "/proc",
        cgroup_root: str | Path = "/sys/fs/cgroup",
        uid: int | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        monotonic: Callable[[], float] = time.monotonic,
        wait: Callable[[float], None] = time.sleep,
        command_timeout_seconds: float = SYSTEMCTL_TIMEOUT_SECONDS,
        transition_timeout_seconds: float = FREEZER_TRANSITION_TIMEOUT_SECONDS,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._proc_root = Path(proc_root)
        self._cgroup_root = Path(cgroup_root)
        self._uid = os.geteuid() if uid is None else uid
        self._run = command_runner
        self._monotonic = monotonic
        self._wait = wait
        self._command_timeout = command_timeout_seconds
        self._transition_timeout = transition_timeout_seconds
        self._environ = environ

    def discover(self, pid: object) -> SteamAppScope:
        valid_pid = _coerce_pid(pid)
        proc_dir = self._proc_root / str(valid_pid)
        try:
            if proc_dir.stat().st_uid != self._uid:
                raise ScopeDiscoveryError("Launch PID owner does not match the plugin user")
            cgroup_text = (proc_dir / "cgroup").read_text(encoding="utf-8")
        except ScopeDiscoveryError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ScopeDiscoveryError("Unable to read launch PID cgroup membership") from exc

        cgroup_path = _unified_cgroup_path(cgroup_text)
        parts = _validated_scope_parts(cgroup_path, self._uid)
        unit = parts[-1]
        scope_dir = self._resolved_scope_dir(parts)
        self._require_state_files(scope_dir)
        try:
            identity = scope_dir.stat()
        except OSError as exc:
            raise ScopeDiscoveryError("Unable to identify Steam app scope") from exc
        return SteamAppScope(
            unit=unit,
            cgroup_path="/" + "/".join(parts),
            device=identity.st_dev,
            inode=identity.st_ino,
            root_pid=valid_pid,
        )

    def freeze(self, scope: SteamAppScope) -> ScopeTransitionResult:
        state, reason = self._scope_state(scope)
        if state != "live":
            return ScopeTransitionResult(False, reason)
        command = self._run_unit_command("freeze", scope.unit)
        if not command.success:
            self._best_effort_thaw(scope)
            return command
        verified = self.wait_for_frozen(scope, expected=True)
        if not verified.success:
            self._best_effort_thaw(scope)
        return verified

    def thaw(self, scope: SteamAppScope) -> ScopeTransitionResult:
        state, reason = self._scope_state(scope)
        if state == "missing":
            return ScopeTransitionResult(True, disappeared=True)
        if state != "live":
            return ScopeTransitionResult(False, reason)

        command = self._run_unit_command("thaw", scope.unit)
        if not command.success:
            post_state, _ = self._scope_state(scope)
            if post_state == "missing":
                return ScopeTransitionResult(True, disappeared=True)
            return command
        return self.wait_for_frozen(scope, expected=False)

    def freeze_requested(self, scope: SteamAppScope) -> bool:
        state, _ = self._scope_state(scope)
        if state != "live":
            return False
        try:
            return self._read_requested(scope) == 1
        except (OSError, ValueError, RuntimeError):
            return False

    def wait_for_frozen(self, scope: SteamAppScope, expected: bool) -> ScopeTransitionResult:
        expected_value = int(expected)
        deadline = self._monotonic() + self._transition_timeout
        while True:
            state, reason = self._scope_state(scope)
            if state == "missing" and not expected:
                return ScopeTransitionResult(True, disappeared=True)
            if state != "live":
                return ScopeTransitionResult(False, reason)
            try:
                requested = self._read_requested(scope)
                completed = self._read_completed(scope)
            except (OSError, ValueError, RuntimeError):
                return ScopeTransitionResult(False, "Malformed or unreadable cgroup freezer state")
            if requested == expected_value and completed == expected_value:
                return ScopeTransitionResult(True)
            now = self._monotonic()
            if now >= deadline:
                action = "freeze" if expected else "thaw"
                return ScopeTransitionResult(False, f"Cgroup {action} verification timed out")
            self._wait(min(FREEZER_POLL_SECONDS, max(0.0, deadline - now)))

    def _resolved_scope_dir(self, parts: tuple[str, ...]) -> Path:
        try:
            root = self._cgroup_root.resolve(strict=True)
            expected = root.joinpath(*parts)
            resolved = expected.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ScopeDiscoveryError("Steam app scope is unavailable") from exc
        if resolved != expected or not resolved.is_relative_to(root):
            raise ScopeDiscoveryError("Steam app scope escapes the cgroup root")
        return resolved

    def _require_state_files(self, scope_dir: Path) -> None:
        try:
            for name in ("cgroup.freeze", "cgroup.events"):
                state_file = scope_dir / name
                if not state_file.is_file():
                    raise ScopeDiscoveryError("Steam app scope has no readable freezer state")
                state_file.read_text(encoding="utf-8")
        except ScopeDiscoveryError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ScopeDiscoveryError("Steam app scope has no readable freezer state") from exc

    def _scope_dir(self, scope: SteamAppScope) -> Path:
        parts = _validated_scope_parts(scope.cgroup_path, self._uid)
        if parts[-1] != scope.unit:
            raise ValueError("Scope unit does not match its cgroup path")
        root = self._cgroup_root.resolve(strict=True)
        expected = root.joinpath(*parts)
        resolved = expected.resolve(strict=True)
        if resolved != expected or not resolved.is_relative_to(root):
            raise ValueError("Scope path no longer resolves exactly")
        return resolved

    def _scope_state(self, scope: SteamAppScope) -> tuple[str, str]:
        try:
            path = self._scope_dir(scope)
            identity = path.stat()
        except FileNotFoundError:
            return "missing", "Steam app scope disappeared"
        except (OSError, ValueError, RuntimeError, ScopeDiscoveryError):
            return "invalid", "Steam app scope path is invalid"
        if (identity.st_dev, identity.st_ino) != (scope.device, scope.inode):
            return "stale", "Steam app scope identity changed"
        return "live", ""

    def _read_requested(self, scope: SteamAppScope) -> int:
        value = (self._scope_dir(scope) / "cgroup.freeze").read_text(encoding="utf-8").strip()
        if value not in {"0", "1"}:
            raise ValueError("invalid cgroup.freeze")
        return int(value)

    def _read_completed(self, scope: SteamAppScope) -> int:
        events = (self._scope_dir(scope) / "cgroup.events").read_text(encoding="utf-8")
        values: list[str] = []
        for line in events.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[0] == "frozen":
                values.append(fields[1])
        if len(values) != 1 or values[0] not in {"0", "1"}:
            raise ValueError("invalid cgroup.events")
        return int(values[0])

    def _run_unit_command(self, action: str, unit: str) -> ScopeTransitionResult:
        if action not in {"freeze", "thaw"} or _UNIT_RE.fullmatch(unit) is None:
            return ScopeTransitionResult(False, "Refusing invalid scope transition")
        argv = ["systemctl", "--user", action, unit]
        env = dict(os.environ if self._environ is None else self._environ)
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{self._uid}")
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{self._uid}/bus")
        if "LD_LIBRARY_PATH" in env:
            env["LD_LIBRARY_PATH"] = ""
        try:
            completed = self._run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self._command_timeout,
                env=env,
            )
        except FileNotFoundError:
            return ScopeTransitionResult(False, "systemctl is unavailable")
        except subprocess.TimeoutExpired as exc:
            detail = _bounded_line(exc.stderr)
            suffix = f": {detail}" if detail else ""
            return ScopeTransitionResult(False, f"systemctl {action} timed out{suffix}")
        except OSError as exc:
            return ScopeTransitionResult(False, f"systemctl {action} failed: {_bounded_line(exc)}")
        if completed.returncode != 0:
            detail = _bounded_line(completed.stderr) or f"exit {completed.returncode}"
            return ScopeTransitionResult(False, f"systemctl {action} failed: {detail}")
        return ScopeTransitionResult(True)

    def _best_effort_thaw(self, scope: SteamAppScope) -> None:
        state, _ = self._scope_state(scope)
        if state != "live":
            return
        command = self._run_unit_command("thaw", scope.unit)
        if command.success:
            self.wait_for_frozen(scope, expected=False)


def _coerce_pid(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScopeDiscoveryError("PID must be a safe integer")
    if value <= 1 or value > MAX_PID:
        raise ScopeDiscoveryError("PID is outside the safe process range")
    return value


def _unified_cgroup_path(content: str) -> str:
    paths = [line[3:] for line in content.splitlines() if line.startswith("0::")]
    if len(paths) != 1 or not paths[0].startswith("/"):
        raise ScopeDiscoveryError("Launch PID has no unique unified cgroup entry")
    return paths[0]


def _validated_scope_parts(cgroup_path: str, uid: int) -> tuple[str, ...]:
    pure = PurePosixPath(cgroup_path)
    parts = pure.parts[1:] if pure.is_absolute() else ()
    unit = parts[-1] if parts else ""
    expected_prefix = (
        "user.slice",
        f"user-{uid}.slice",
        f"user@{uid}.service",
        "app.slice",
    )
    allowed_prescope_paths = (expected_prefix, (*expected_prefix, _STEAM_LAUNCHER_UNIT))
    if parts in allowed_prescope_paths and cgroup_path == "/" + "/".join(parts):
        raise ScopeNotReadyError("Exact Steam app scope is not ready")
    if (
        len(parts) != 5
        or parts[:4] != expected_prefix
        or any(part in {"", ".", ".."} for part in parts)
        or _UNIT_RE.fullmatch(unit) is None
        or cgroup_path != "/" + "/".join(parts)
    ):
        raise ScopeDiscoveryError("Launch PID is not in an exact Steam app scope")
    return tuple(parts)


def _bounded_line(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    else:
        text = str(value)
    return " ".join(text.split())[:MAX_REASON_LENGTH]
