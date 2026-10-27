from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from harness import ContractHarness, REPO_ROOT, native_backend_path


GAME = "Contract Fixture Game"
APP_ID = "123456"
DEVICE_ID = "CONTRACT-SECRET-DEVICE-ID"
API_KEY = "contract-secret-api-key"


@pytest.fixture
def backend() -> Iterator[ContractHarness]:
    harness = ContractHarness().start()
    try:
        yield harness
    finally:
        harness.close()


def rpc(harness: ContractHarness, method: str, *args: Any) -> Any:
    success, result = harness.call(method, *args)
    assert success, f"{method} returned protocol failure: {result!r}"
    return result


def _load_fixture(name: str) -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "ludusavi" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_for(predicate: Any, timeout: float, message: str) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError(message)


def _option_value(arguments: list[str], option: str) -> str | None:
    try:
        index = arguments.index(option)
    except ValueError:
        return None
    return arguments[index + 1] if index + 1 < len(arguments) else None


def _assert_history_map(history: Any) -> None:
    assert isinstance(history, dict)
    entry_fields = {"operation", "trigger", "status", "reason", "message", "timestamp"}
    for game_name, game_history in history.items():
        assert isinstance(game_name, str)
        assert isinstance(game_history, dict)
        assert {
            "last_backup",
            "last_restore",
            "last_skip",
            "last_failure",
            "last_operation",
        } <= game_history.keys()
        for entry in game_history.values():
            if entry is None:
                continue
            assert isinstance(entry, dict)
            assert entry_fields <= entry.keys()
            assert entry["operation"] in {"backup", "restore", "start", "exit"}
            assert entry["trigger"] in {
                "manual_backup",
                "manual_restore",
                "auto_start",
                "auto_exit",
            }
            assert entry["status"] in {"backed_up", "restored", "skipped", "failed"}
            assert entry["reason"] is None or isinstance(entry["reason"], str)
            assert entry["message"] is None or isinstance(entry["message"], str)
            assert isinstance(entry["timestamp"], str) and entry["timestamp"]


def _assert_refresh_result(result: Any) -> None:
    assert isinstance(result, dict)
    assert {"games", "aliases", "history", "dependency_error"} <= result.keys()
    assert isinstance(result["games"], list)
    assert isinstance(result["aliases"], dict)
    assert all(
        isinstance(alias, str) and isinstance(canonical, str)
        for alias, canonical in result["aliases"].items()
    )
    _assert_history_map(result["history"])
    assert result["dependency_error"] is None or isinstance(result["dependency_error"], str)
    for game in result["games"]:
        assert isinstance(game, dict)
        assert {
            "name",
            "configured",
            "has_backup",
            "needs_first_backup",
            "error",
            "status",
        } <= game.keys()
        assert isinstance(game["name"], str)
        assert isinstance(game["configured"], bool)
        assert isinstance(game["has_backup"], bool)
        assert isinstance(game["needs_first_backup"], bool)
        assert game["error"] is None or isinstance(game["error"], str)
        assert game["status"] in {"configured", "has_backup", "needs_first_backup", "error"}
        steam_id = game.get("steam_id")
        assert steam_id is None or (
            isinstance(steam_id, str)
            or isinstance(steam_id, int)
            and not isinstance(steam_id, bool)
        )


def _assert_backup_list(result: Any) -> None:
    assert isinstance(result, dict)
    assert {"game", "backup_path", "total_size_bytes", "backups"} <= result.keys()
    assert isinstance(result["game"], str)
    assert result["backup_path"] is None or isinstance(result["backup_path"], str)
    total_size = result["total_size_bytes"]
    assert total_size is None or isinstance(total_size, int) and not isinstance(total_size, bool)
    assert isinstance(result["backups"], list)
    for backup in result["backups"]:
        assert isinstance(backup, dict)
        assert {
            "id",
            "when",
            "locked",
            "os",
            "comment",
            "size_bytes",
            "file_count",
        } <= backup.keys()
        assert isinstance(backup["id"], str) and backup["id"]
        assert isinstance(backup["when"], str) and backup["when"]
        assert isinstance(backup["locked"], bool)
        assert backup["os"] is None or isinstance(backup["os"], str)
        assert backup["comment"] is None or isinstance(backup["comment"], str)
        for field in ("size_bytes", "file_count"):
            value = backup[field]
            assert value is None or isinstance(value, int) and not isinstance(value, bool)


def _assert_command_after(backend: ContractHarness, first_record: int, verb: str) -> None:
    assert any(
        record["command_args"][:1] == [verb] and "--preview" not in record["command_args"]
        for record in backend.fake_processes()[first_record:]
    ), f"lifecycle result had no real Ludusavi {verb} command"


def _assert_history_entry(
    backend: ContractHarness,
    field: str,
    operation: str,
    trigger: str,
    status: str,
) -> None:
    history = rpc(backend, "get_game_history")
    _assert_history_map(history)
    entry = history[GAME][field]
    assert entry is not None
    assert entry["operation"] == operation
    assert entry["trigger"] == trigger
    assert entry["status"] == status


@dataclass
class _OwnedUnit:
    unit: str
    description: str
    process: subprocess.Popen[bytes] | None = None
    invocation_id: str | None = None
    cleaned: bool = False


def _unit_state(unit: str) -> dict[str, str]:
    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            unit,
            "--property=LoadState",
            "--property=Description",
            "--property=InvocationID",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if "LoadState" not in values:
        raise RuntimeError(f"Cannot identify transient unit {unit}")
    return values


def _is_owned_unit(owner: _OwnedUnit) -> bool:
    state = _unit_state(owner.unit)
    if state["LoadState"] == "not-found" or state.get("Description") != owner.description:
        return False
    invocation = state.get("InvocationID", "")
    if not invocation or (owner.invocation_id is not None and invocation != owner.invocation_id):
        return False
    if owner.invocation_id is None:
        owner.invocation_id = invocation
    return True


def _owned_unit_gone(owner: _OwnedUnit) -> bool:
    state = _unit_state(owner.unit)
    invocation = state.get("InvocationID", "")
    return (
        state["LoadState"] == "not-found"
        or state.get("Description") != owner.description
        or bool(owner.invocation_id and invocation and invocation != owner.invocation_id)
    )


def _stop_owned_unit(owner: _OwnedUnit) -> None:
    if owner.cleaned or owner.process is None:
        return
    process = owner.process
    try:
        if owner.invocation_id is None and not _is_owned_unit(owner):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not _is_owned_unit(owner):
                time.sleep(0.02)
        if _is_owned_unit(owner):
            try:
                subprocess.run(
                    ["systemctl", "--user", "thaw", owner.unit],
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                pass
            if _is_owned_unit(owner):
                try:
                    stopped = (
                        subprocess.run(
                            ["systemctl", "--user", "stop", owner.unit],
                            capture_output=True,
                            timeout=8,
                            check=False,
                        ).returncode
                        == 0
                    )
                except subprocess.TimeoutExpired:
                    stopped = False
                if not stopped and _is_owned_unit(owner):
                    subprocess.run(
                        ["systemctl", "--user", "--signal=SIGKILL", "kill", owner.unit],
                        capture_output=True,
                        timeout=3,
                        check=False,
                    )
                    if _is_owned_unit(owner):
                        subprocess.run(
                            ["systemctl", "--user", "stop", owner.unit],
                            capture_output=True,
                            timeout=8,
                            check=False,
                        )
        _wait_for(lambda: _owned_unit_gone(owner), 5, f"owned unit {owner.unit} survived cleanup")
        owner.cleaned = True
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        else:
            process.wait(timeout=2)


@dataclass
class _Child:
    pid: int
    process: subprocess.Popen[bytes]
    unit: str
    tick_file: Path
    owner: _OwnedUnit


def _start_systemd_child(
    root: Path,
    unit: str,
    systemd_args: list[str],
    request: pytest.FixtureRequest,
    *,
    thread_count: int = 0,
) -> _Child:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        pytest.fail("systemd-run is required to create an isolated child")
    if _unit_state(unit)["LoadState"] != "not-found":
        pytest.fail(f"{unit} is already loaded; refusing to replace it")
    owner = _OwnedUnit(unit, f"sdh-contract-{uuid4().hex}")
    request.addfinalizer(lambda: _stop_owned_unit(owner))
    pid_file = root / f"{unit}.pid"
    tick_file = root / f"{unit}.tick"
    code = (
        "import os,sys,time,threading\n"
        f"for _ in range({thread_count}):\n"
        "    threading.Thread(target=time.sleep, args=(600,), daemon=True).start()\n"
        "pid_file, tick_file = sys.argv[1:]\n"
        "temporary_file = tick_file + '.tmp'\n"
        "open(pid_file, 'w').write(str(os.getpid()))\n"
        "tick = 0\n"
        "while True:\n"
        "    with open(temporary_file, 'w') as stream:\n"
        "        stream.write(str(tick))\n"
        "    os.replace(temporary_file, tick_file)\n"
        "    tick += 1\n"
        "    time.sleep(0.01)\n"
    )
    process = subprocess.Popen(
        [
            systemd_run,
            *systemd_args,
            f"--unit={unit}",
            f"--description={owner.description}",
            "--property=RuntimeMaxSec=600s",
            "--property=TimeoutStopSec=3s",
            "--property=SendSIGKILL=yes",
            "--collect",
            "--",
            sys.executable,
            "-c",
            code,
            str(pid_file),
            str(tick_file),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    owner.process = process
    assert process.stderr is not None

    def read_pid() -> int | None:
        if not pid_file.exists():
            return None
        try:
            return int(pid_file.read_text(encoding="ascii"))
        except ValueError:
            return None

    try:

        def capture_unit() -> bool:
            state = _unit_state(unit)
            if state["LoadState"] == "not-found":
                return False
            if state.get("Description") != owner.description:
                raise RuntimeError(f"{unit} is not the owned transient unit")
            invocation = state.get("InvocationID", "")
            if not invocation:
                return False
            owner.invocation_id = invocation
            return True

        _wait_for(capture_unit, 10, f"systemd-run did not register owned unit {unit}")
        pid = _wait_for(
            read_pid,
            10,
            f"systemd-run did not start {unit}: "
            f"{process.stderr.read().decode(errors='replace') if process.poll() is not None else ''}",
        )
        _wait_for(lambda: tick_file.exists(), 5, "systemd child heartbeat did not start")
        return _Child(pid, process, unit, tick_file, owner)
    except BaseException:
        try:
            _stop_owned_unit(owner)
        except BaseException as cleanup_error:
            raise RuntimeError(
                f"Could not clean up failed systemd fixture {unit}"
            ) from cleanup_error
        raise


def _start_scoped_child(root: Path, request: pytest.FixtureRequest) -> _Child:
    unit = f"app-steam-app{APP_ID}-{time.time_ns() % 1_000_000_000}.scope"
    return _start_systemd_child(
        root,
        unit,
        ["--user", "--scope", "--slice=app.slice", "--quiet"],
        request,
    )


def _start_prescope_child(
    root: Path, request: pytest.FixtureRequest, *, thread_count: int = 0
) -> _Child:
    return _start_systemd_child(
        root,
        "steam-launcher.service",
        [
            "--user",
            "--slice=app.slice",
            "--wait",
            "--quiet",
        ],
        request,
        thread_count=thread_count,
    )


def _proc_state(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    close_paren = stat.rfind(")")
    fields = stat[close_paren + 1 :].split() if close_paren >= 0 else []
    return fields[0] if fields else None


def _scope_frozen(child: _Child) -> bool:
    cgroup = (
        Path("/sys/fs/cgroup/user.slice")
        / f"user-{os.geteuid()}.slice"
        / f"user@{os.geteuid()}.service/app.slice"
        / child.unit
        / "cgroup.events"
    )
    return any(line == "frozen 1" for line in cgroup.read_text(encoding="ascii").splitlines())


def _tick_count(child: _Child) -> int:
    return int(child.tick_file.read_text(encoding="ascii"))


def _stop_child(child: _Child) -> None:
    _stop_owned_unit(child.owner)


def _stop_children(*children: _Child | None) -> None:
    with ExitStack() as cleanup:
        for child in children:
            if child is not None:
                cleanup.callback(_stop_child, child)


class _SyncthingServer:
    def __init__(
        self,
        backup_path: Path,
        *,
        redirect_non_loopback: bool = False,
        hold_watch_events: bool = False,
        hold_second_status: bool = False,
        reset_event_cursor: bool = False,
        refresh_on_config: bool = False,
    ) -> None:
        self.backup_path = backup_path
        self.redirect_non_loopback = redirect_non_loopback
        self.hold_watch_events = hold_watch_events
        self.hold_second_status = hold_second_status
        self.reset_event_cursor = reset_event_cursor
        self.refresh_on_config = refresh_on_config
        self.config_event_sent = threading.Event()
        self.config_refresh_waiting = threading.Event()
        self.release_config_refresh = threading.Event()
        self.second_status_waiting = threading.Event()
        self.release_second_status = threading.Event()
        self.watch_event_waiting = threading.Event()
        self.release_watch_event = threading.Event()
        self._events_request_count = 0
        self.requests: list[str] = []
        self.response_overrides: dict[str, Any] = {}
        self._request_lock = threading.Lock()
        self._status_request_count = 0
        self._system_status_count = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = self.path.split("?", 1)[0]
                with owner._request_lock:
                    owner.requests.append(self.path)
                    if route == "/rest/system/status":
                        owner._system_status_count += 1
                    if route == "/rest/db/status":
                        owner._status_request_count += 1
                    if route == "/rest/events":
                        owner._events_request_count += 1
                    events_request_count = owner._events_request_count
                    system_status_count = owner._system_status_count
                    status_request_count = owner._status_request_count
                if self.headers.get("X-API-Key") != API_KEY:
                    self.send_error(401)
                    return
                if (
                    route == "/rest/system/status"
                    and owner.redirect_non_loopback
                    and system_status_count == 1
                ):
                    self.send_response(302)
                    self.send_header(
                        "Location",
                        f"http://0.0.0.0:{owner.port}/rest/system/status",
                    )
                    self.end_headers()
                    return
                if route == "/rest/events" and owner.hold_watch_events and events_request_count > 1:
                    owner.watch_event_waiting.set()
                    owner.release_watch_event.wait(timeout=4)
                if (
                    route == "/rest/db/status"
                    and owner.hold_second_status
                    and status_request_count == 2
                ):
                    owner.second_status_waiting.set()
                    owner.release_second_status.wait(timeout=4)
                if route == "/rest/db/status" and owner.config_event_sent.is_set():
                    owner.config_refresh_waiting.set()
                    owner.release_config_refresh.wait(timeout=4)
                responses: dict[str, Any] = {
                    "/rest/system/status": {"myID": "CONTRACT-LOCAL-DEVICE"},
                    "/rest/config/folders": [
                        {
                            "id": "contract-folder",
                            "label": "Contract Folder",
                            "path": str(owner.backup_path),
                            "devices": [
                                {"deviceID": "CONTRACT-LOCAL-DEVICE"},
                                {"deviceID": DEVICE_ID},
                            ],
                            "fsWatcherEnabled": False,
                            "rescanIntervalS": 60,
                        }
                    ],
                    "/rest/system/connections": {"connections": {DEVICE_ID: {"connected": True}}},
                    "/rest/db/status": {
                        "state": "idle",
                        "sequence": 1,
                        "needBytes": 0,
                        "needTotalItems": 0,
                    },
                    "/rest/db/completion": {
                        "completion": 100,
                        "needBytes": 0,
                        "needItems": 0,
                        "needDeletes": 0,
                    },
                    "/rest/events": [],
                }
                responses.update(owner.response_overrides)
                if owner.hold_second_status:
                    responses["/rest/db/status"]["sequence"] = 0 if status_request_count == 1 else 2
                elif not owner.refresh_on_config:
                    responses["/rest/db/status"]["state"] = (
                        "scanning" if status_request_count == 1 else "idle"
                    )
                if owner.reset_event_cursor and route == "/rest/events":
                    since = parse_qs(urlsplit(self.path).query).get("since", ["0"])[0]
                    event_id = {"0": 100, "100": 1, "1": 2}.get(since)
                    if event_id is not None:
                        responses["/rest/events"] = [
                            {
                                "id": event_id,
                                "type": "StateChanged",
                                "data": {"folder": "contract-folder", "to": "idle"},
                            }
                        ]
                if (
                    owner.refresh_on_config
                    and route == "/rest/events"
                    and events_request_count == 2
                ):
                    responses["/rest/events"] = [
                        {
                            "id": 1,
                            "type": "StateChanged",
                            "data": {"folder": "contract-folder", "to": "scanning"},
                        },
                        {"id": 2, "type": "ConfigSaved", "data": {}},
                    ]
                    owner.config_event_sent.set()
                if route not in responses:
                    self.send_error(404)
                    return
                payload = json.dumps(responses[route]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: Any) -> None:
                del format, args

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> _SyncthingServer:
        self.thread.start()
        return self

    def close(self) -> None:
        self.release_watch_event.set()
        self.release_second_status.set()
        self.release_config_refresh.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@contextmanager
def _syncthing(
    harness: ContractHarness,
    *,
    redirect_non_loopback: bool = False,
    hold_second_status: bool = False,
    reset_event_cursor: bool = False,
    refresh_on_config: bool = False,
) -> Iterator[_SyncthingServer]:
    server = _SyncthingServer(
        harness.backup_root,
        redirect_non_loopback=redirect_non_loopback,
        hold_second_status=hold_second_status,
        reset_event_cursor=reset_event_cursor,
        refresh_on_config=refresh_on_config,
    ).start()
    config = harness.xdg_state / "syncthing" / "config.xml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        '<configuration><gui enabled="true" tls="false">'
        f"<address>127.0.0.1:{server.port}</address><apikey>{API_KEY}</apikey>"
        "</gui></configuration>",
        encoding="utf-8",
    )
    try:
        yield server
    finally:
        server.close()


@pytest.mark.contract_core
def test_core_settings_and_logging_contract(backend: ContractHarness) -> None:
    settings = rpc(backend, "get_settings")
    assert settings == {
        "auto_sync_enabled": False,
        "sync_disabled_games": [],
        "selected_game": "",
        "notifications": {
            "enabled": True,
            "auto_sync_progress": True,
            "auto_sync_results": True,
            "manual_operations": True,
            "refresh_status": True,
            "failures_errors": True,
            "update_available": True,
        },
        "update_channel": "stable",
        "automatic_update_checks": True,
        "debug_logging": True,
    }
    assert rpc(backend, "get_operation_status") == {
        "is_running": False,
        "name": None,
        "game_name": None,
        "last_result": None,
        "last_error": None,
    }
    assert rpc(backend, "get_ludusavi_launcher_shortcut_id") == -1
    assert rpc(backend, "set_ludusavi_launcher_shortcut_id", 7654321) is True
    assert rpc(backend, "get_ludusavi_launcher_shortcut_id") == 7654321

    updated = rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    assert updated["auto_sync_enabled"] is True
    saved = json.loads((backend.settings_dir / "settings.json").read_text(encoding="utf-8"))
    assert saved["auto_sync_enabled"] is True
    disabled = rpc(
        backend,
        "update_settings",
        {"kind": "game_sync", "game_name": "  Core   Game  ", "enabled": False},
    )
    assert disabled["sync_disabled_games"] == ["Core Game"]
    unchanged = rpc(
        backend, "update_settings", {"kind": "game_sync", "game_name": "", "enabled": "invalid"}
    )
    assert unchanged["sync_disabled_games"] == ["Core Game"]
    enabled = rpc(
        backend,
        "update_settings",
        {"kind": "game_sync", "game_name": "Core Game", "enabled": True},
    )
    assert enabled["sync_disabled_games"] == []
    assert (
        rpc(backend, "update_settings", {"kind": "selected_game", "game_name": "  Core   Game "})[
            "selected_game"
        ]
        == "Core Game"
    )
    assert (
        rpc(
            backend,
            "update_settings",
            {"kind": "notification", "key": "manual_operations", "enabled": False},
        )["notifications"]["manual_operations"]
        is False
    )
    assert (
        rpc(backend, "update_settings", {"kind": "update_channel", "channel": "development"})[
            "update_channel"
        ]
        == "development"
    )
    assert (
        rpc(backend, "update_settings", {"kind": "automatic_update_checks", "enabled": False})[
            "automatic_update_checks"
        ]
        is False
    )
    assert (
        rpc(backend, "update_settings", {"kind": "debug_logging", "enabled": False})[
            "debug_logging"
        ]
        is False
    )
    failed = rpc(backend, "update_settings", {"kind": "unknown_contract_patch"})
    assert failed["status"] == "failed"
    assert "Unknown settings patch kind" in failed["message"]
    failed = rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": "not a boolean"})
    assert failed["status"] == "failed"
    assert "requires boolean enabled" in failed["message"]

    assert rpc(backend, "log", "debug", "debug while disabled", None, GAME) is None
    logs = rpc(backend, "get_recent_logs")
    assert any(
        entry["message"] == "debug while disabled"
        and entry["level"] == "debug"
        and entry["operation"] == "frontend"
        and entry["game_name"] == GAME
        for entry in logs
    )
    plugin_logs = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in backend.log_dir.rglob("*")
        if path.is_file()
    )
    assert "debug while disabled" not in plugin_logs
    assert (
        rpc(backend, "update_settings", {"kind": "debug_logging", "enabled": True})["debug_logging"]
        is True
    )
    rpc(backend, "log", "debug", "debug while enabled", None, GAME)
    plugin_logs = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in backend.log_dir.rglob("*")
        if path.is_file()
    )
    assert "debug while enabled" in plugin_logs

    for index in range(105):
        rpc(backend, "log", "info", f"ring-{index}")
    logs = rpc(backend, "get_recent_logs")
    assert len(logs) == 100
    assert logs[0]["message"] == "ring-5"
    assert logs[-1]["message"] == "ring-104"
    assert set(logs[0]) == {"level", "message", "timestamp", "operation", "game_name"}
    assert len(logs[0]["timestamp"]) == 19
    assert logs[0]["operation"] == "frontend"
    assert logs[0]["game_name"] is None

    history = rpc(backend, "get_game_history")
    _assert_history_map(history)
    assert history == {}
    success, error = backend.call("unknown_contract_method")
    assert success is False
    assert "Plugin has no method unknown_contract_method" in error

    assert backend.settings_dir.stat().st_mode & 0o777 == 0o700
    assert backend.runtime_dir.stat().st_mode & 0o777 == 0o700
    cache_path = backend.runtime_dir / "cache.json"
    assert cache_path.stat().st_mode & 0o777 == 0o600
    assert (backend.runtime_dir / ".sdh_ludusavi.state.lock").stat().st_mode & 0o777 == 0o600


@pytest.mark.contract_core
def test_native_shutdown_drains_inflight_persistence_call() -> None:
    native_backend = str(native_backend_path())

    with tempfile.TemporaryDirectory(
        prefix="sdh-shutdown-", dir="/var/tmp/sdh_ludusavi"
    ) as temporary_root:
        backend = ContractHarness(backend=native_backend, root=Path(temporary_root)).start()
        process = backend.process
        assert process is not None
        lock_file = (backend.runtime_dir / ".sdh_ludusavi.state.lock").open("r+b")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    backend.call, "set_ludusavi_launcher_shortcut_id", 8765432
                )
                try:
                    time.sleep(0.1)
                    process.send_signal(signal.SIGTERM)
                    time.sleep(0.1)
                    assert process.poll() is None, "native backend exited before draining the call"
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()

                try:
                    success, result = pending.result(timeout=1)
                except ConnectionError:
                    pass
                else:
                    assert success and result is True
                process.wait(timeout=5)
                assert process.returncode == 0
            cache = json.loads((backend.runtime_dir / "cache.json").read_text(encoding="utf-8"))
            assert cache["ludusaviLauncherShortcutAppId"] == 8765432
        finally:
            if not lock_file.closed:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            backend.close()


@pytest.mark.contract_core
def test_native_sigterm_during_startup_lock_contention_is_prompt() -> None:
    native_backend = str(native_backend_path())

    with tempfile.TemporaryDirectory(
        prefix="sdh-startup-lock-", dir="/var/tmp/sdh_ludusavi"
    ) as temporary_root:
        backend = ContractHarness(backend=native_backend, root=Path(temporary_root))
        lock_path = backend.runtime_dir / ".sdh_ludusavi.state.lock"
        lock_path.touch(mode=0o600)
        lock_file = lock_path.open("r+b")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            backend._check_fakes()
            with (
                backend.stdout_path.open("ab") as stdout_file,
                backend.stderr_path.open("ab") as stderr_file,
            ):
                process = subprocess.Popen(
                    [native_backend],
                    cwd=REPO_ROOT,
                    env=backend.env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=True,
                )
            backend.process = process
            time.sleep(0.25)
            assert process.poll() is None
            assert not backend.socket_path.exists()

            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=3)
            assert process.returncode == 0
            assert time.monotonic() - started < 5
        finally:
            if not lock_file.closed:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            backend.close()


@pytest.mark.contract_theme
def test_theme_installation_and_uninstall_ownership(backend: ContractHarness) -> None:
    assert rpc(backend, "consume_theme_refresh_needed") is True
    assert rpc(backend, "consume_theme_refresh_needed") is False
    theme = backend.decky_home / "themes" / "SDH-Ludusavi Status"
    assert (theme / "theme.json").is_file()
    unrelated_theme = backend.decky_home / "themes" / "Keep Existing Theme"
    unrelated_theme.mkdir(parents=True)
    (unrelated_theme / "keep.css").write_text("owned elsewhere", encoding="utf-8")

    backend.uninstall()
    assert not theme.exists()
    assert (unrelated_theme / "keep.css").read_text(encoding="utf-8") == "owned elsewhere"

    theme.mkdir()
    unowned_file = theme / "owned-by-someone-else.txt"
    unowned_file.write_text("preserve this theme", encoding="utf-8")
    backend.start()
    backend.uninstall()
    assert unowned_file.read_text(encoding="utf-8") == "preserve this theme"


@pytest.mark.contract_theme
def test_uninstall_only_theme_cleanup_needs_no_backend_state() -> None:
    native_backend = str(native_backend_path())

    with tempfile.TemporaryDirectory(
        prefix="sdh-contract-uninstall-", dir="/var/tmp/sdh_ludusavi"
    ) as temporary_root:
        harness = ContractHarness(backend=native_backend, root=Path(temporary_root))
        theme = harness.decky_home / "themes" / "SDH-Ludusavi Status"
        theme.mkdir(parents=True)
        (theme / ".sdh-ludusavi-status-theme").write_text(
            "sdh-ludusavi-status-theme-1\n", encoding="ascii"
        )
        (theme / "config_USER.json").write_text('{"active":true}\n', encoding="utf-8")
        unrelated = harness.decky_home / "themes" / "Unrelated Theme"
        unrelated.mkdir()
        (unrelated / "keep.css").write_text("keep", encoding="utf-8")
        environment = harness.env.copy()
        environment["DECKY_PLUGIN_HOOK"] = "uninstall"
        environment.pop("DECKY_PLUGIN_SOCKET", None)

        result = subprocess.run(
            [native_backend],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5,
            check=False,
        )

        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert not theme.exists()
        assert (harness.runtime_dir / "status-theme-choices.json").read_text(
            encoding="utf-8"
        ) == '{"active":true}\n'
        assert (unrelated / "keep.css").read_text(encoding="utf-8") == "keep"
        assert not (harness.runtime_dir / "cache.json").exists()
        assert not (harness.settings_dir / "settings.json").exists()


@pytest.mark.contract_operations
def test_bundled_runner_is_preferred_and_reused_until_its_target_changes() -> None:
    harness = ContractHarness()
    bundled = harness.install_bundled_fake()
    first = harness.root / "ludusavi-first"
    second = harness.root / "ludusavi-second"
    bundled.rename(first)
    shutil.copyfile(first, second)
    second.chmod(0o755)
    bundled.symlink_to(first)
    harness.start()
    try:
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        assert rpc(harness, "get_ludusavi_command") == {
            "commandPath": str(bundled),
            "args": ["--config", str(harness.config_dir)],
            "compatTool": "",
        }
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None
        before = len(harness.fake_processes())
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None
        reused = harness.fake_processes()[before:]
        assert reused and all(record["runner"] == "bundled" for record in reused)
        assert not any(record["command_args"] == ["--version"] for record in reused)
        assert all(record["argv"][:2] == ["--config", str(harness.config_dir)] for record in reused)

        bundled.unlink()
        bundled.symlink_to(second)
        before = len(harness.fake_processes())
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None
        assert (
            sum(
                record["command_args"] == ["--version"]
                for record in harness.fake_processes()[before:]
            )
            == 1
        )
    finally:
        harness.close()


@pytest.mark.contract_operations
def test_failing_bundled_runner_falls_back_to_flatpak_with_config() -> None:
    harness = ContractHarness(scenario={"bundled": {"responses": {"version": {"exit_code": 1}}}})
    harness.install_bundled_fake()
    harness.start()
    try:
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        assert rpc(harness, "get_ludusavi_command") == {
            "commandPath": "flatpak",
            "args": ["run", "com.github.mtkennerly.ludusavi", "--config", str(harness.config_dir)],
            "compatTool": "",
        }
        records = harness.fake_processes()
        assert [record["runner"] for record in records] == ["bundled", "flatpak"]
        assert records[0]["argv"] == ["--config", str(harness.config_dir), "--version"]
        assert records[1]["argv"] == [
            "run",
            "com.github.mtkennerly.ludusavi",
            "--config",
            str(harness.config_dir),
            "--version",
        ]
    finally:
        harness.close()


@pytest.mark.contract_operations
@pytest.mark.parametrize("bundled", [False, True])
def test_config_and_matching_manifest_migrate_once_for_either_runner(bundled: bool) -> None:
    scenario = {
        runner: {
            "responses": {
                "config_show": {"json": {"manifest": {"url": "https://example.test/list"}}}
            }
        }
        for runner in ("flatpak", "bundled")
    }
    harness = ContractHarness(scenario=scenario)
    if bundled:
        harness.install_bundled_fake()
    source = harness.home / ".var/app/com.github.mtkennerly.ludusavi/config/ludusavi"
    source.mkdir(parents=True)
    expected = {
        "config.yaml": "source config",
        "manifest.yaml": "source manifest",
        "cache.yaml": "source cache",
    }
    for name, content in expected.items():
        (source / name).write_text(content, encoding="utf-8")
    (harness.config_dir / "config.yaml").unlink()
    harness.start()
    try:
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        for name, content in expected.items():
            assert (harness.config_dir / name).read_text(encoding="utf-8") == content
            (source / name).write_text("changed source", encoding="utf-8")
        lookups = [
            record
            for record in harness.fake_processes()
            if record["command_args"] == ["config", "show", "--api"]
        ]
        assert len(lookups) == 2
        for record in lookups:
            # `config show` writes default files, so each address is read from a private copy.
            scratch = Path(record["config"])
            assert scratch.parent == harness.config_dir
            assert scratch.name.startswith(".sdh-ludusavi-")
            assert not scratch.exists()
        assert sorted(path.name for path in source.iterdir()) == sorted(expected)
        harness.restart()
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        for name, content in expected.items():
            assert (harness.config_dir / name).read_text(encoding="utf-8") == content
    finally:
        harness.close()


@pytest.mark.contract_operations
def test_version_discovery_cache_tracks_the_active_flatpak_deployment() -> None:
    harness = ContractHarness()
    old_deployment = harness.root / "deployment-old"
    new_deployment = harness.root / "deployment-new"
    old_deployment.mkdir()
    new_deployment.mkdir()
    active = harness.root / "active"
    active.symlink_to(old_deployment, target_is_directory=True)
    harness.env["SDH_CONTRACT_FLATPAK_LOCATION"] = str(active)
    harness.start()
    try:
        assert harness.fake_processes() == []
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        assert [record["command_args"] for record in harness.fake_processes()] == [["--version"]]

        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None
        before = len(harness.fake_processes())
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None
        commands = [record["command_args"] for record in harness.fake_processes()[before:]]
        assert len(commands) == 3, commands
        assert not any(command == ["--version"] for command in commands)

        active.unlink()
        active.symlink_to(new_deployment, target_is_directory=True)
        harness.set_scenario(
            {"flatpak": {"responses": {"version": {"stdout": "ludusavi 0.32.0\n"}}}}
        )
        before = len(harness.fake_processes())
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None
        assert rpc(harness, "get_versions")["ludusavi"] == "0.32.0"
        commands = [record["command_args"] for record in harness.fake_processes()[before:]]
        assert commands.count(["--version"]) == 1, commands

        active.unlink()
        harness.set_scenario({"flatpak": {"responses": {"version": {"exit_code": 1}}}})
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"]
        assert rpc(harness, "get_ludusavi_command") is None

        active.symlink_to(new_deployment, target_is_directory=True)
        harness.set_scenario(
            {"flatpak": {"responses": {"version": {"stdout": "ludusavi 0.32.0\n"}}}}
        )
        harness.restart()
        before = len(harness.fake_processes())
        assert rpc(harness, "get_versions")["ludusavi"] == "0.32.0"
        assert [record["command_args"] for record in harness.fake_processes()[before:]] == [
            ["--version"]
        ]
    finally:
        harness.close()


@pytest.mark.contract_operations
@pytest.mark.parametrize("failed_operation", ["refresh", "text", "backup"])
def test_ludusavi_execution_failure_invalidates_cached_availability(
    failed_operation: str,
) -> None:
    harness = ContractHarness()
    deployment = harness.root / "deployment"
    deployment.mkdir()
    active = harness.root / "active"
    active.symlink_to(deployment, target_is_directory=True)
    harness.env["SDH_CONTRACT_FLATPAK_LOCATION"] = str(active)
    harness.start()
    try:
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        assert rpc(harness, "get_ludusavi_command")["commandPath"] == "flatpak"
        if failed_operation != "text":
            assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None

        command = {
            "refresh": "backup_preview",
            "text": "config_path",
            "backup": "backup",
        }[failed_operation]
        harness.set_scenario(
            {
                "flatpak": {
                    "responses": {
                        command: {"exit_code": 23, "stderr": "Flatpak runtime unavailable"},
                        "version": {"exit_code": 23, "stderr": "Flatpak runtime unavailable"},
                    }
                }
            }
        )
        if failed_operation == "refresh":
            assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"]
        elif failed_operation == "text":
            assert rpc(harness, "get_ludusavi_logs")["status"] == "failed"
        else:
            assert rpc(harness, "force_backup", GAME)["status"] == "failed"

        before = len(harness.fake_processes())
        assert rpc(harness, "get_versions")["status"] == "failed"
        assert rpc(harness, "get_ludusavi_command") is None
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"]
        commands = [record["command_args"] for record in harness.fake_processes()[before:]]
        assert commands.count(["--version"]) >= 3, commands
        assert all(command == ["--version"] for command in commands), commands

        harness.set_scenario({})
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        assert rpc(harness, "get_ludusavi_command")["commandPath"] == "flatpak"
        assert rpc(harness, "refresh_games", True, APP_ID)["dependency_error"] is None
    finally:
        harness.close()


@pytest.mark.contract_operations
def test_version_discovery_rechecks_when_deployment_cannot_be_identified(
    backend: ContractHarness,
) -> None:
    assert rpc(backend, "get_versions")["ludusavi"] == "0.31.0"
    assert [record["command_args"] for record in backend.fake_processes()] == [["--version"]]
    backend.set_scenario({"flatpak": {"responses": {"version": {"exit_code": 1}}}})
    assert rpc(backend, "refresh_games", True, APP_ID)["dependency_error"]
    assert rpc(backend, "get_ludusavi_command") is None
    backend.set_scenario({})
    assert rpc(backend, "get_versions")["ludusavi"] == "0.31.0"


@pytest.mark.contract_operations
def test_ludusavi_child_environment_is_sanitized() -> None:
    harness = ContractHarness()
    inherited_library_path = "/contract/parent-only-libraries"
    harness.env["LD_LIBRARY_PATH"] = inherited_library_path
    harness.env.pop("XDG_RUNTIME_DIR", None)
    try:
        harness.start()
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
        records = harness.fake_processes()
        version_calls = [record for record in records if record["argv"][-1] == "--version"]
        assert version_calls
        for record in version_calls:
            assert record["child_environment"]["LD_LIBRARY_PATH"] == ""
            assert record["child_environment"]["XDG_RUNTIME_DIR"] == (
                f"/run/user/{os.getuid()}"
                if Path(f"/run/user/{os.getuid()}").is_dir()
                else "/run/user/1000"
            )
            assert record["child_environment"]["LD_LIBRARY_PATH"] != inherited_library_path
    finally:
        harness.close()


@pytest.mark.contract_operations
def test_unload_cancels_and_reaps_ludusavi_process_group() -> None:
    harness = ContractHarness()
    ready_file = harness.root / "fake-child-ready"
    harness.set_scenario(
        {
            "flatpak": {
                "responses": {
                    "backup": {
                        "delay_seconds": 600,
                        "ignore_term": True,
                        "spawn_child": True,
                        "child_ready_file": str(ready_file),
                    },
                }
            }
        }
    )
    harness.start()
    assert harness.process is not None
    operations = ThreadPoolExecutor(max_workers=1)
    try:
        result = operations.submit(harness.call, "force_backup", GAME, timeout=30)
        record = _wait_for(
            lambda: next(
                (
                    item
                    for item in harness.fake_processes()
                    if item["command_args"][:1] == ["backup"]
                    and "--preview" not in item["command_args"]
                ),
                None,
            ),
            10,
            "slow backup did not start",
        )
        child_pid = int(
            _wait_for(
                lambda: ready_file.read_text(encoding="utf-8") if ready_file.is_file() else None,
                10,
                "fake child did not become ready",
            )
        )
        assert os.getpgid(child_pid) == record["pgid"]
        assert record["pgid"] != os.getpgid(harness.process.pid)
        started = time.monotonic()
        harness.stop()
        stop_seconds = time.monotonic() - started
        assert stop_seconds < 5, f"backend shutdown took {stop_seconds:.3f}s"
        assert not _process_group_exists(record["pgid"])
        cache = json.loads((harness.runtime_dir / "cache.json").read_text(encoding="utf-8"))
        entry = cache["game_history"][GAME]
        assert entry["last_skip"]["status"] == "skipped"
        assert entry["last_skip"]["reason"] == "cancelled"
        assert entry["last_failure"] is None
        assert entry["last_operation"]["status"] == "skipped"
        with pytest.raises(ConnectionError, match="backend is shutting down"):
            result.result(timeout=1)
    finally:
        harness.close()
        operations.shutdown(wait=True, cancel_futures=True)


@pytest.mark.contract_operations
def test_force_backup_skips_unknown_game_without_starting_backup(
    backend: ContractHarness,
) -> None:
    result = rpc(backend, "force_backup", "  Unknown   Fixture ")
    assert result == {
        "status": "skipped",
        "game": "Unknown Fixture",
        "reason": "unmatched_game",
    }
    assert not any(
        record["command_args"][:1] == ["backup"] and "--preview" not in record["command_args"]
        for record in backend.fake_processes()
    )


@pytest.mark.contract_operations
def test_lazy_game_lookup_propagates_refresh_failures(backend: ContractHarness) -> None:
    backend.set_scenario(
        {
            "flatpak": {
                "responses": {"backup_preview": {"exit_code": 23, "stderr": "preview failed"}}
            }
        }
    )
    for method in ("force_backup", "list_backups"):
        result = rpc(backend, method, GAME)
        assert result["status"] == "failed"
        assert "exit code 23" in result["message"]


@pytest.mark.contract_operations
@pytest.mark.parametrize("payload", [None, []])
def test_non_object_ludusavi_roots_preserve_the_existing_registry(
    backend: ContractHarness, payload: Any
) -> None:
    before = rpc(backend, "refresh_games", True, APP_ID)
    assert any(game["name"] == GAME for game in before["games"])
    backend.set_scenario({"flatpak": {"responses": {"backup_preview": {"json": payload}}}})

    refreshed = rpc(backend, "refresh_games", True, APP_ID)

    assert refreshed["dependency_error"]
    assert any(game["name"] == GAME for game in refreshed["games"])


@pytest.mark.contract_operations
def test_successful_operations_keep_history_when_followup_refresh_fails(
    backend: ContractHarness,
) -> None:
    refreshed = rpc(backend, "refresh_games", True, APP_ID)
    assert any(game["name"] == GAME and game["has_backup"] for game in refreshed["games"])
    backend.set_scenario(
        {"flatpak": {"responses": {"backup_preview": {"exit_code": 23, "stderr": "offline"}}}}
    )

    assert rpc(backend, "force_backup", GAME)["status"] == "backed_up"
    assert rpc(backend, "force_restore", GAME)["status"] == "restored"
    previews = [
        record
        for record in backend.fake_processes()
        if record["command_args"][:1] == ["backup"] and "--preview" in record["command_args"]
    ]
    assert len(previews) >= 3
    history = rpc(backend, "get_game_history")[GAME]
    assert history["last_backup"]["status"] == "backed_up"
    assert history["last_restore"]["status"] == "restored"
    backend.restart()
    history = rpc(backend, "get_game_history")[GAME]
    assert history["last_backup"]["status"] == "backed_up"
    assert history["last_restore"]["status"] == "restored"


@pytest.mark.contract_lifecycle
def test_ignored_refresh_entries_and_missing_backup_are_safe(backend: ContractHarness) -> None:
    preview = _load_fixture("backup-preview.json")
    ignored = dict(preview["games"][GAME])
    ignored["decision"] = "Ignored"
    preview["games"]["Ignored Fixture"] = ignored
    backend.set_scenario(
        {
            "flatpak": {
                "responses": {
                    "backup_preview": {"json": preview},
                    "backups": {"json": {"games": {}}},
                }
            }
        }
    )
    refreshed = rpc(backend, "refresh_games", True, APP_ID)
    assert all(game["name"] != "Ignored Fixture" for game in refreshed["games"])
    assert any(game["name"] == GAME and not game["has_backup"] for game in refreshed["games"])
    rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    assert rpc(backend, "check_game_start", GAME, APP_ID)["reason"] == "no_backup"


@pytest.mark.contract_operations
def test_refresh_omits_backup_only_and_empty_preview_games(backend: ContractHarness) -> None:
    preview = _load_fixture("backup-preview.json")
    preview["games"]["Empty Preview"] = {"files": {}, "registry": {}}
    preview["games"]["Registry Only"] = {"files": {}, "registry": {"HKCU/example": {}}}
    backups = _load_fixture("backups.json")
    backups["games"]["Backup Only"] = {"backups": [{"name": "old"}]}
    backups["games"]["Empty Preview"] = {"backups": [{"name": "old"}]}
    backend.set_scenario(
        {
            "flatpak": {
                "responses": {"backup_preview": {"json": preview}, "backups": {"json": backups}}
            }
        }
    )

    result = rpc(backend, "refresh_games", True, APP_ID)
    assert {game["name"] for game in result["games"]} == {GAME, "Registry Only"}


@pytest.mark.contract_operations
def test_refresh_orders_unicode_titles_after_refresh_cache_and_restart(
    backend: ContractHarness,
) -> None:
    titles = ["Ñandú", "Straw", "Brotato", "Straße", "apico"]
    preview = {"games": {title: {"files": {"save": {}}, "registry": {}} for title in titles}}
    backend.set_scenario({"flatpak": {"responses": {"backup_preview": {"json": preview}}}})
    expected = ["apico", "Brotato", "Straße", "Straw", "Ñandú"]

    def names(force: bool) -> list[str]:
        result = rpc(backend, "refresh_games", force, APP_ID)
        assert result["dependency_error"] is None
        return [game["name"] for game in result["games"]]

    assert names(True) == expected
    before = len(backend.fake_processes())
    assert names(False) == expected
    backend.restart()
    assert names(False) == expected
    commands = [record["command_args"] for record in backend.fake_processes()[before:]]
    assert not any(
        command and command[0] == "backup" and "--preview" in command for command in commands
    )


@pytest.mark.contract_operations
def test_list_backups_sorts_and_prefers_api_sizes(backend: ContractHarness) -> None:
    backup_path = backend.backup_root / GAME
    for name in ("older", "newer", "disk"):
        (backup_path / name).mkdir(parents=True)
        (backup_path / name / "save").write_bytes(b"abc")
    backups = {
        "games": {
            GAME: {
                "backupPath": str(backup_path),
                "backups": [
                    {"name": "older", "when": "2000-01-01T00:00:00Z", "size": 900, "file_count": 9},
                    {
                        "name": "newer",
                        "when": "2020-01-01T00:00:00Z",
                        "size": 12345,
                        "file_count": 42,
                    },
                    {"name": "disk", "when": "2010-01-01T00:00:00Z"},
                ],
            }
        }
    }
    backend.set_scenario({"flatpak": {"responses": {"backups": {"json": backups}}}})
    rpc(backend, "refresh_games", True, APP_ID)
    result = rpc(backend, "list_backups", GAME)
    assert result["backup_path"] == str(backup_path)
    assert [item["id"] for item in result["backups"]] == ["newer", "disk", "older"]
    assert [(item["size_bytes"], item["file_count"]) for item in result["backups"]] == [
        (12345, 42),
        (3, 1),
        (900, 9),
    ]
    assert result["total_size_bytes"] == 13248


@pytest.mark.contract_operations
def test_aliases_refresh_on_config_change_and_drop_stale_on_failure(
    backend: ContractHarness,
) -> None:
    alias, other = "Unique Shortcut", "Another Game"
    preview = _load_fixture("backup-preview.json")
    preview["games"][other] = dict(preview["games"][GAME])

    def scenario(target: str | None) -> dict[str, Any]:
        config = (
            {"json": {"customGames": [{"name": alias, "alias": target}]}}
            if target is not None
            else {"exit_code": 23, "stderr": "config unavailable"}
        )
        return {
            "flatpak": {"responses": {"backup_preview": {"json": preview}, "config_show": config}}
        }

    def change_config() -> None:
        config = backend.config_dir / "config.yaml"
        modified = config.stat().st_mtime_ns + 1_000_000_000
        os.utime(config, ns=(modified, modified))

    backend.set_scenario(scenario(GAME))
    assert rpc(backend, "refresh_games", True, APP_ID)["aliases"] == {alias: GAME}
    first_record = len(backend.fake_processes())
    assert rpc(backend, "refresh_games", True, APP_ID)["aliases"] == {alias: GAME}
    commands = [record["command_args"] for record in backend.fake_processes()[first_record:]]
    assert len(commands) == 4, commands
    assert not any(command[:2] == ["config", "show"] for command in commands)
    assert rpc(backend, "list_backups", alias)["game"] == GAME
    assert rpc(backend, "refresh_games", False, APP_ID)["aliases"] == {alias: GAME}

    change_config()
    backend.set_scenario(scenario(other))
    first_record = len(backend.fake_processes())
    assert rpc(backend, "refresh_games", False, APP_ID)["aliases"] == {alias: other}
    assert (
        sum(
            record["command_args"][:2] == ["config", "show"]
            for record in backend.fake_processes()[first_record:]
        )
        == 1
    )
    assert rpc(backend, "list_backups", alias)["game"] == other

    change_config()
    backend.set_scenario(scenario(None))
    first_record = len(backend.fake_processes())
    assert rpc(backend, "refresh_games", False, APP_ID)["aliases"] == {}
    assert (
        sum(
            record["command_args"][:2] == ["config", "show"]
            for record in backend.fake_processes()[first_record:]
        )
        == 1
    )
    assert rpc(backend, "list_backups", alias)["reason"] == "unmatched_game"
    backend.set_scenario(scenario(other))
    assert rpc(backend, "refresh_games", True, APP_ID)["aliases"] == {alias: other}


@pytest.mark.contract_lifecycle
@pytest.mark.parametrize("fallback", ["originalPath", "redirectedPath"])
def test_conflict_metadata_falls_back_to_original_and_redirected_paths(
    backend: ContractHarness, fallback: str
) -> None:
    save = backend.root / f"{fallback}.sav"
    save.write_bytes(b"local")
    os.utime(save, (1_800_000_000, 1_800_000_000))
    preview = _load_fixture("backup-preview.json")
    preview["games"][GAME]["files"] = {
        str(backend.root / "missing.sav"): {
            "originalPath": str(save) if fallback == "originalPath" else "relative.sav",
            "redirectedPath": str(save) if fallback == "redirectedPath" else "/missing.sav",
        }
    }
    backups = _load_fixture("backups.json")
    for item in backups["games"][GAME]["backups"]:
        item["when"] = "2000-01-01T00:00:00Z"
    backend.set_scenario(
        {
            "flatpak": {
                "responses": {"backup_preview": {"json": preview}, "backups": {"json": backups}}
            }
        }
    )
    rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    rpc(backend, "refresh_games", True, APP_ID)
    result = rpc(backend, "check_game_start", GAME, APP_ID)
    assert result["status"] == "conflict"
    assert datetime.fromisoformat(result["localModifiedAt"]) == datetime.fromtimestamp(
        1_800_000_000, tz=timezone.utc
    )
    assert result["backupModifiedAt"] == "2000-01-01T00:00:00Z"
    assert result["backupPath"] == str(backend.backup_root / GAME)
    assert result["localLabel"] == "Keep Local Save"
    assert result["backupLabel"] == "Restore Backup Save"


@pytest.mark.contract_lifecycle
@pytest.mark.parametrize(
    ("preview_response", "expected_reason", "expects_backups_lookup"),
    [
        pytest.param("same", "local_current", False, id="preview-decides"),
        # Registry says a backup exists but Ludusavi reports none: still ask the user,
        # whose conflict details come from the backup listing.
        pytest.param("empty", "ambiguous_recency", True, id="stale-registry-still-prompts"),
        pytest.param("failed", "ambiguous_recency", True, id="failed-preview-falls-back"),
        pytest.param("other-game", "ambiguous_recency", True, id="unexpected-preview-falls-back"),
    ],
)
def test_game_start_check_uses_one_restore_preview(
    backend: ContractHarness,
    preview_response: str,
    expected_reason: str,
    expects_backups_lookup: bool,
) -> None:
    # Each Ludusavi launch reloads its manifest; a start check must not pay for a backup
    # listing when the restore preview already answers.
    preview = _load_fixture("restore-preview.json")
    responses: dict[str, Any] = {}
    if preview_response == "same":
        preview["games"][GAME]["change"] = "Same"
        responses["restore_preview"] = {"json": preview}
    elif preview_response == "empty":
        responses["restore_preview"] = {"json": {"overall": preview["overall"], "games": {}}}
    elif preview_response == "failed":
        responses["restore_preview"] = {"exit_code": 1, "stderr": "preview failed"}
    else:
        preview["games"] = {"Some Other Game": preview["games"][GAME]}
        responses["restore_preview"] = {"json": preview}
    rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    rpc(backend, "refresh_games", True, APP_ID)
    backend.set_scenario({"flatpak": {"responses": responses}})
    first_record = len(backend.fake_processes())

    result = rpc(backend, "check_game_start", GAME, APP_ID)

    commands = [record["command_args"] for record in backend.fake_processes()[first_record:]]
    assert result["reason"] == expected_reason, result
    if expected_reason == "ambiguous_recency":
        assert result["status"] == "conflict", result
    restore_previews = [command for command in commands if command[:2] == ["restore", "--preview"]]
    assert len(restore_previews) == 1, commands
    used_backups = any(command[:1] == ["backups"] for command in commands)
    assert used_backups == expects_backups_lookup, commands
    assert not any(
        command[:1] == ["restore"] and "--preview" not in command for command in commands
    ), "a start check ran a real restore"


@pytest.mark.contract_lifecycle
def test_disabled_sync_blocks_all_automatic_operations(backend: ContractHarness) -> None:
    rpc(backend, "refresh_games", True, APP_ID)
    calls = [
        ("check_game_start", (GAME, APP_ID)),
        ("restore_game_on_start", (GAME, APP_ID)),
        ("resolve_game_start_conflict", (GAME, APP_ID, "restore_backup")),
        ("check_game_exit", (GAME, APP_ID)),
        ("backup_game_on_exit", (GAME, APP_ID)),
    ]
    for method, args in calls:
        assert rpc(backend, method, *args)["reason"] == "auto_sync_disabled"
    rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    rpc(backend, "update_settings", {"kind": "game_sync", "game_name": GAME, "enabled": False})
    for method, args in calls:
        assert rpc(backend, method, *args)["reason"] == "game_sync_disabled"
    assert not any(
        record["command_args"][:1] in (["backup"], ["restore"])
        and "--preview" not in record["command_args"]
        for record in backend.fake_processes()
    )


@pytest.mark.contract_lifecycle
@pytest.mark.parametrize("decision", ["Ignored", "Cancelled"])
def test_exit_preview_not_processed_never_requests_backup(
    backend: ContractHarness, decision: str
) -> None:
    rpc(backend, "refresh_games", True, APP_ID)
    rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    preview = _load_fixture("backup-preview.json")
    preview["games"][GAME]["decision"] = decision
    backend.set_scenario({"flatpak": {"responses": {"backup_preview": {"json": preview}}}})
    assert rpc(backend, "check_game_exit", GAME, APP_ID)["reason"] == "not_processed"
    assert not any(
        record["command_args"][:1] == ["backup"] and "--preview" not in record["command_args"]
        for record in backend.fake_processes()
    )


@pytest.mark.contract_operations
def test_no_change_operations_record_skips(backend: ContractHarness) -> None:
    rpc(backend, "refresh_games", True, APP_ID)
    unchanged = {"games": {GAME: {"decision": "Processed", "change": "Same", "files": {}}}}
    backend.set_scenario(
        {"flatpak": {"responses": {"backup": {"json": unchanged}, "restore": {"json": unchanged}}}}
    )
    for method, args in [
        ("force_backup", (GAME,)),
        ("force_restore", (GAME,)),
        ("restore_backup_version", (GAME, "backup.zip")),
    ]:
        result = rpc(backend, method, *args)
        assert result["status"] == "skipped" and result["reason"] == "local_current"
        assert rpc(backend, "get_game_history")[GAME]["last_skip"]["reason"] == "local_current"


@pytest.mark.contract_lifecycle
def test_auto_exit_history_survives_failed_followup_refresh(backend: ContractHarness) -> None:
    rpc(backend, "refresh_games", True, APP_ID)
    rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    backend.set_scenario(
        {"flatpak": {"responses": {"backup_preview": {"exit_code": 23, "stderr": "offline"}}}}
    )
    assert rpc(backend, "backup_game_on_exit", GAME, APP_ID)["status"] == "backed_up"
    history = rpc(backend, "get_game_history")[GAME]["last_backup"]
    assert history["status"] == "backed_up" and history["trigger"] == "auto_exit"
    backend.restart()
    assert rpc(backend, "get_game_history")[GAME]["last_backup"]["trigger"] == "auto_exit"


@pytest.mark.contract_core
@pytest.mark.parametrize("bad_id", [None, "not-an-id"])
def test_malformed_legacy_notification_and_shortcut_values(bad_id: Any) -> None:
    harness = ContractHarness()
    (harness.settings_dir / "settings.json").write_text(
        json.dumps({"notifications": {"manual_operations": "invalid", "failures_errors": False}})
    )
    (harness.runtime_dir / "cache.json").write_text(
        json.dumps({"ludusaviLauncherShortcutAppId": bad_id})
    )
    try:
        harness.start()
        settings = rpc(harness, "get_settings")
        assert settings["notifications"]["manual_operations"] is True
        assert settings["notifications"]["failures_errors"] is False
        assert settings["notifications"]["update_available"] is True
        assert rpc(harness, "get_ludusavi_launcher_shortcut_id") == -1
    finally:
        harness.close()


@pytest.mark.contract_operations
def test_restore_backup_version_rejects_unsafe_id(backend: ContractHarness) -> None:
    backup = rpc(backend, "refresh_games", True, APP_ID)
    assert any(game["name"] == GAME for game in backup["games"])
    success, result = backend.call("restore_backup_version", GAME, "../outside")
    assert success is True
    assert result["status"] == "failed"
    assert "Invalid backup ID" in result["message"]


@pytest.mark.contract_core
def test_existing_unknown_settings_and_cache_keys_survive_updates() -> None:
    harness = ContractHarness()
    settings_path = harness.settings_dir / "settings.json"
    cache_path = harness.runtime_dir / "cache.json"
    settings_path.write_text(json.dumps({"future_setting": {"nested": [1, 2]}}))
    cache_path.write_text(json.dumps({"future_cache": {"nested": [3, 4]}}))
    try:
        harness.start()
        assert rpc(harness, "update_settings", {"kind": "auto_sync", "enabled": True})[
            "auto_sync_enabled"
        ]
        assert rpc(harness, "set_ludusavi_launcher_shortcut_id", 7654321) is True
        assert json.loads(settings_path.read_text())["future_setting"] == {"nested": [1, 2]}
        assert json.loads(cache_path.read_text())["future_cache"] == {"nested": [3, 4]}
        harness.restart()
        assert rpc(harness, "get_settings")["auto_sync_enabled"] is True
        assert rpc(harness, "get_ludusavi_launcher_shortcut_id") == 7654321
        assert json.loads(settings_path.read_text())["future_setting"] == {"nested": [1, 2]}
        assert json.loads(cache_path.read_text())["future_cache"] == {"nested": [3, 4]}
    finally:
        harness.close()


@pytest.mark.contract_operations
def test_settings_cache_shortcut_protocol_and_concurrent_calls(
    backend: ContractHarness,
) -> None:
    settings = rpc(backend, "get_settings")
    assert settings["auto_sync_enabled"] is False
    assert settings["selected_game"] == ""
    assert settings["update_channel"] == "stable"
    assert rpc(backend, "get_ludusavi_launcher_shortcut_id") == -1
    assert rpc(backend, "set_ludusavi_launcher_shortcut_id", 7654321) is True
    assert rpc(backend, "get_ludusavi_launcher_shortcut_id") == 7654321

    updated = rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})
    assert updated["auto_sync_enabled"] is True
    saved = json.loads((backend.settings_dir / "settings.json").read_text(encoding="utf-8"))
    assert saved["auto_sync_enabled"] is True
    failed = rpc(backend, "update_settings", {"kind": "unknown_contract_patch"})
    assert failed["status"] == "failed"
    assert "Unknown settings patch kind" in failed["message"]

    refreshed = rpc(backend, "refresh_games", True, "42,43")
    _assert_refresh_result(refreshed)
    assert refreshed["dependency_error"] is None
    assert any(game["name"] == GAME and game["has_backup"] for game in refreshed["games"])
    assert rpc(backend, "is_game_cache_current", "42,43") is True
    backup = rpc(backend, "force_backup", GAME)
    assert backup["status"] == "backed_up"

    cache = json.loads((backend.runtime_dir / "cache.json").read_text(encoding="utf-8"))
    assert {"games", "aliases", "ids", "installed_app_ids", "game_history"} <= cache.keys()
    assert cache["ludusaviLauncherShortcutAppId"] == 7654321
    assert cache["game_history"][GAME]["last_backup"]["operation"] == "backup"

    with ThreadPoolExecutor(max_workers=2) as pool:
        settings_call = pool.submit(backend.call, "get_settings")
        versions_call = pool.submit(backend.call, "get_versions")
        settings_reply = settings_call.result(timeout=10)
        versions_reply = versions_call.result(timeout=10)
    assert settings_reply[0] is True and settings_reply[1]["auto_sync_enabled"] is True
    assert versions_reply[0] is True and versions_reply[1]["ludusavi"] == "0.31.0"

    backend.restart()
    success, error = backend.call("unknown_contract_method")
    assert success is False
    assert "Plugin has no method unknown_contract_method" in error
    settings = rpc(backend, "get_settings")
    assert settings["auto_sync_enabled"] is True
    assert rpc(backend, "get_ludusavi_launcher_shortcut_id") == 7654321
    history = rpc(backend, "get_game_history")
    _assert_history_map(history)
    assert history[GAME]["last_backup"]["operation"] == "backup"
    cache = json.loads((backend.runtime_dir / "cache.json").read_text(encoding="utf-8"))
    assert cache["game_history"][GAME]["last_backup"]["status"] == "backed_up"


@pytest.mark.contract_operations
def test_operations_logs_status_lock_and_local_update_state(backend: ContractHarness) -> None:
    versions = rpc(backend, "get_versions")
    assert versions["ludusavi"] == "0.31.0"
    assert "pyludusavi" not in versions
    command = rpc(backend, "get_ludusavi_command")
    assert command["commandPath"] == "flatpak"
    assert command["args"][:2] == ["run", "com.github.mtkennerly.ludusavi"]
    assert command["compatTool"] == ""

    assert rpc(backend, "log", "warning", "contract log entry", "rpc", GAME) is None
    logs = rpc(backend, "get_recent_logs")
    assert any(
        entry["message"] == "contract log entry" and entry["game_name"] == GAME for entry in logs
    )
    ludusavi_log = backend.config_dir / "ludusavi_rCURRENT.log"
    ludusavi_log.write_text("real Ludusavi log from isolated HOME\n", encoding="utf-8")
    assert rpc(backend, "get_ludusavi_logs") == "real Ludusavi log from isolated HOME\n"

    assert rpc(backend, "force_backup", GAME)["status"] == "backed_up"
    assert rpc(backend, "force_restore", GAME)["status"] == "restored"
    backups = rpc(backend, "list_backups", GAME)
    _assert_backup_list(backups)
    assert backups["game"] == GAME
    assert len(backups["backups"]) == 2
    backup_id = backups["backups"][-1]["id"]
    selected = rpc(backend, "restore_backup_version", GAME, backup_id)
    assert selected["status"] == "restored"
    records = backend.fake_processes()
    assert any(
        record["command_args"][:1] == ["restore"] and "--force" in record["command_args"]
        for record in records
    )
    assert any(
        record["command_args"][:1] == ["restore"]
        and _option_value(record["command_args"], "--backup") == backup_id
        for record in records
    )

    backend.set_scenario({"flatpak": {"responses": {"backup": {"delay_seconds": 0.8}}}})
    prior_record_count = len(backend.fake_processes())
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(backend.call, "force_backup", GAME)
        _wait_for(
            lambda: any(
                "backup" in record["command_args"] and "--preview" not in record["command_args"]
                for record in backend.fake_processes()[prior_record_count:]
            ),
            5,
            "slow fake backup did not start",
        )
        locked = rpc(backend, "force_restore", GAME)
        assert locked["status"] == "skipped"
        assert locked["reason"] == "operation_running"
        locked_list = rpc(backend, "list_backups", GAME)
        assert locked_list["status"] == "skipped"
        assert locked_list["reason"] == "operation_running"
        status = rpc(backend, "get_operation_status")
        assert status["is_running"] is True
        assert status["name"] == "backup"
        assert status["game_name"] == GAME
        success, result = first.result(timeout=10)
    assert success is True and result["status"] == "backed_up"
    assert rpc(backend, "get_operation_status")["is_running"] is False


@pytest.mark.contract_updater
def test_update_install_handoff_persistence_contract(backend: ContractHarness) -> None:
    candidate = {
        "version": "0.4.11",
        "tag": "v0.4.11",
        "channel": "stable",
        "artifact_url": "https://example.invalid/plugin.zip",
        "sha256": "0" * 64,
        "release_url": "https://example.invalid/release",
        "published_at": "2026-10-01T00:00:00Z",
        "action": "update",
        "updateTraceId": "contract-trace-1",
    }
    recorded = rpc(backend, "record_update_install_requested", candidate)
    assert recorded["pending_update_install"]["version"] == candidate["version"]
    confirmed = rpc(backend, "confirm_update_install_handoff", candidate["version"])
    assert confirmed["pending_update_install"]["handoff_confirmed_at"]
    notified = rpc(backend, "mark_update_notified", candidate["tag"])
    assert notified["last_notified_tag"] == candidate["tag"]

    backend.restart()
    context = rpc(backend, "get_update_check_context")
    assert context["last_notified_tag"] == candidate["tag"]
    assert context["pending_update_install"]["handoff_confirmed_at"]
    cleared = rpc(backend, "clear_pending_update_install", candidate["version"])
    assert cleared["pending_update_install"] is None
    backend.restart()
    assert rpc(backend, "get_update_check_context")["pending_update_install"] is None


@pytest.mark.contract_updater
def test_main_reconciles_pending_install_with_loaded_version() -> None:
    harness = ContractHarness()
    version = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
    harness.env["DECKY_PLUGIN_VERSION"] = version
    pending = {
        "version": version,
        "tag": f"v{version}",
        "channel": "stable",
        "published_at": "2026-10-01T00:00:00Z",
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (harness.runtime_dir / "cache.json").write_text(
        json.dumps({"update_check_cache": {"pending_update_install": pending}}),
        encoding="utf-8",
    )
    try:
        harness.start()

        def reconciled() -> dict[str, Any] | None:
            context = rpc(harness, "get_update_check_context")
            saved = json.loads((harness.runtime_dir / "cache.json").read_text(encoding="utf-8"))
            if (
                context["pending_update_install"] is not None
                or saved["update_check_cache"].get("installed_release_tag") != pending["tag"]
            ):
                return None
            return context

        context = _wait_for(reconciled, 5, "startup did not reconcile the installed update")
        assert context["installed_release_tag"] == pending["tag"]
        assert context["installed_release_published_at"] == pending["published_at"]
        saved = json.loads((harness.runtime_dir / "cache.json").read_text(encoding="utf-8"))
        assert saved["update_check_cache"]["installed_release_tag"] == pending["tag"]
        assert "pending_update_install" not in saved["update_check_cache"]
    finally:
        harness.close()


@pytest.mark.contract_lifecycle
@pytest.mark.contract_gate
def test_lifecycle_newer_save_guard_and_launch_gate_contract(
    backend: ContractHarness, request: pytest.FixtureRequest
) -> None:
    (backend.root / "save.dat").write_bytes(b"newer local save\n")
    scenario_backups = _load_fixture("backups.json")
    for snapshot in scenario_backups["games"][GAME]["backups"]:
        snapshot["when"] = "2000-01-01T00:00:00Z"
    backend.set_scenario({"flatpak": {"responses": {"backups": {"json": scenario_backups}}}})

    assert rpc(backend, "update_settings", {"kind": "auto_sync", "enabled": True})[
        "auto_sync_enabled"
    ]
    assert rpc(
        backend,
        "update_settings",
        {"kind": "game_sync", "game_name": GAME, "enabled": True},
    )["auto_sync_enabled"]
    rpc(backend, "refresh_games", True, APP_ID)

    before_restore = sum(
        record["command_args"][:1] == ["restore"] and "--preview" not in record["command_args"]
        for record in backend.fake_processes()
    )
    start_check = rpc(backend, "check_game_start", GAME, APP_ID)
    assert start_check["status"] == "conflict"
    assert datetime.fromisoformat(start_check["localModifiedAt"]).timestamp() == pytest.approx(
        (backend.root / "save.dat").stat().st_mtime
    )
    assert start_check["backupModifiedAt"] == "2000-01-01T00:00:00Z"
    assert start_check["backupPath"] == str(backend.backup_root / GAME)
    assert start_check["localLabel"] == "Keep Local Save"
    assert start_check["backupLabel"] == "Restore Backup Save"
    after_restore = sum(
        record["command_args"][:1] == ["restore"] and "--preview" not in record["command_args"]
        for record in backend.fake_processes()
    )
    assert after_restore == before_restore, "a newer local save triggered a real restore"

    exit_check = rpc(backend, "check_game_exit", GAME, APP_ID)
    assert exit_check["status"] == "needed"
    assert exit_check["operation"] == "backup"
    before_exit_backup = len(backend.fake_processes())
    assert rpc(backend, "backup_game_on_exit", GAME, APP_ID)["status"] == "backed_up"
    _assert_command_after(backend, before_exit_backup, "backup")
    _assert_history_entry(backend, "last_backup", "backup", "auto_exit", "backed_up")
    child = _start_scoped_child(backend.root, request)
    backend.set_scenario(
        {
            "flatpak": {"responses": {"backups": {"json": scenario_backups}}},
            "systemctl": {"simulate_scope_freeze": True, "scope_unit": child.unit},
        }
    )
    try:
        paused = rpc(backend, "pause_game_process", child.pid)
        assert paused["status"] == "paused", paused
        assert type(paused["pid"]) is int and paused["pid"] == child.pid
        assert isinstance(paused["lease_id"], str) and paused["lease_id"]
        assert (
            isinstance(paused["lease_ttl_seconds"], int | float)
            and not isinstance(paused["lease_ttl_seconds"], bool)
            and paused["lease_ttl_seconds"] > 0
        )
        lease_id = paused["lease_id"]
        pid = paused["pid"]
        assert _scope_frozen(child), "scope freezer did not hold the child"
        frozen_ticks = _tick_count(child)
        time.sleep(0.1)
        assert _tick_count(child) == frozen_ticks, "scope child continued running while frozen"

        wrong = rpc(backend, "renew_game_process_pause", pid, "wrong-contract-lease")
        assert wrong["status"] in {"skipped", "failed"}
        renewed = rpc(backend, "renew_game_process_pause", pid, lease_id)
        assert renewed["status"] == "renewed"
        assert renewed["pid"] == pid
        assert (
            isinstance(renewed["lease_ttl_seconds"], int | float)
            and not isinstance(renewed["lease_ttl_seconds"], bool)
            and renewed["lease_ttl_seconds"] > 0
        )

        first_record = len(backend.fake_processes())
        kept = rpc(
            backend,
            "resolve_game_start_conflict",
            GAME,
            APP_ID,
            "keep_local",
            pid,
            lease_id,
        )
        assert kept["status"] == "backed_up"
        _assert_command_after(backend, first_record, "backup")
        _assert_history_entry(backend, "last_backup", "backup", "auto_start", "backed_up")

        first_record = len(backend.fake_processes())
        restored = rpc(
            backend,
            "resolve_game_start_conflict",
            GAME,
            APP_ID,
            "restore_backup",
            pid,
            lease_id,
        )
        assert restored["status"] == "restored"
        _assert_command_after(backend, first_record, "restore")
        _assert_history_entry(backend, "last_restore", "restore", "auto_start", "restored")

        first_record = len(backend.fake_processes())
        restored = rpc(backend, "restore_game_on_start", GAME, APP_ID, pid, lease_id)
        assert restored["status"] == "restored"
        _assert_command_after(backend, first_record, "restore")
        _assert_history_entry(backend, "last_restore", "restore", "auto_start", "restored")

        ticks_before_resume = _tick_count(child)
        resumed = rpc(backend, "resume_game_process", pid, lease_id)
        assert resumed["status"] == "resumed"
        assert resumed["pid"] == pid
        assert not _scope_frozen(child), "resume left the scope frozen"
        assert _wait_for(
            lambda: _tick_count(child) > ticks_before_resume,
            2,
            "resumed child did not make progress",
        )
    finally:
        _stop_child(child)
    calls = backend.systemctl_calls()
    assert any(call["argv"] == ["--user", "freeze", child.unit] for call in calls)
    assert any(call["argv"] == ["--user", "thaw", child.unit] for call in calls)
    nonexistent = rpc(backend, "pause_game_process", 2147483647)
    assert nonexistent["status"] in {"skipped", "failed"}
    foreign_pid = next(
        int(path.name)
        for path in Path("/proc").iterdir()
        if path.name.isdigit() and int(path.name) > 1 and path.stat().st_uid != os.geteuid()
    )
    foreign = rpc(backend, "pause_game_process", foreign_pid)
    assert foreign["status"] in {"skipped", "failed"}


@pytest.mark.contract_gate
def test_prescope_gate_stops_every_thread_in_real_multithreaded_child(
    backend: ContractHarness,
    request: pytest.FixtureRequest,
) -> None:
    child = _start_prescope_child(backend.root, request, thread_count=4)
    try:
        threads = [int(path.name) for path in Path(f"/proc/{child.pid}/task").iterdir()]
        assert len(threads) >= 5
        paused = rpc(backend, "pause_game_process", child.pid)
        assert paused["status"] == "paused", paused
        assert all(_proc_state(tid) == "T" for tid in threads)
        frozen_ticks = _tick_count(child)
        time.sleep(0.1)
        assert _tick_count(child) == frozen_ticks
        assert (
            rpc(backend, "resume_game_process", child.pid, paused["lease_id"])["status"]
            == "resumed"
        )
        assert _wait_for(lambda: _tick_count(child) > frozen_ticks, 2, "child did not resume")
    finally:
        _stop_child(child)


@pytest.mark.contract_gate
def test_pause_fails_closed_when_scope_discovery_fails(
    backend: ContractHarness, request: pytest.FixtureRequest
) -> None:
    unit = f"non-steam-{time.time_ns() % 1_000_000_000}.scope"
    child = _start_systemd_child(
        backend.root, unit, ["--user", "--scope", "--slice=app.slice", "--quiet"], request
    )
    try:
        paused = rpc(backend, "pause_game_process", child.pid)
        assert paused["status"] == "failed"
        assert "exact Steam app scope" in paused["message"]
        assert "lease_id" not in paused
        ticks = _tick_count(child)
        assert _wait_for(
            lambda: _tick_count(child) > ticks, 2, "failed discovery left child stopped"
        )
        assert not backend.systemctl_calls()
    finally:
        _stop_child(child)


@pytest.mark.contract_gate
def test_partial_freeze_failure_thaws_and_pause_fails_closed(
    backend: ContractHarness,
    request: pytest.FixtureRequest,
) -> None:
    child = _start_scoped_child(backend.root, request)
    backend.set_scenario(
        {
            "systemctl": {
                "simulate_scope_freeze": True,
                "scope_unit": child.unit,
                "partial_freeze_failure": True,
            }
        }
    )
    try:
        failed = rpc(backend, "pause_game_process", child.pid)
        assert failed["status"] == "failed", failed
        assert "freeze" in failed["message"]
        assert "lease_id" not in failed
        assert not _scope_frozen(child)
        assert [call["argv"][1] for call in backend.systemctl_calls()] == ["freeze", "thaw"]
        ticks = _tick_count(child)
        assert _wait_for(lambda: _tick_count(child) > ticks, 2, "failed freeze left child stopped")

        backend.set_scenario(
            {"systemctl": {"simulate_scope_freeze": True, "scope_unit": child.unit}}
        )
        paused = rpc(backend, "pause_game_process", child.pid)
        assert paused["status"] == "paused", paused
        assert _scope_frozen(child)
        assert (
            rpc(backend, "resume_game_process", child.pid, paused["lease_id"])["status"]
            == "resumed"
        )
    finally:
        _stop_child(child)


@pytest.mark.contract_gate
def test_fixture_cleanup_thaws_a_frozen_owned_scope(
    backend: ContractHarness, request: pytest.FixtureRequest
) -> None:
    child = _start_scoped_child(backend.root, request)
    backend.set_scenario({"systemctl": {"simulate_scope_freeze": True, "scope_unit": child.unit}})
    try:
        assert rpc(backend, "pause_game_process", child.pid)["status"] == "paused"
        assert _scope_frozen(child)
        _stop_child(child)
        assert _unit_state(child.unit)["LoadState"] == "not-found"
    finally:
        _stop_child(child)


@pytest.mark.contract_syncthing
@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_syncthing_watch_supports_local_https(
    backend: ContractHarness, version: ssl.TLSVersion
) -> None:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required to generate the local TLS fixture")
    certificate = backend.root / "syncthing-cert.pem"
    key = backend.root / "syncthing-key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    server = _SyncthingServer(backend.backup_root)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = version
    context.maximum_version = version
    context.load_cert_chain(certificate, key)
    server.server.socket = context.wrap_socket(server.server.socket, server_side=True)
    server.start()
    try:
        config = backend.xdg_state / "syncthing" / "config.xml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            '<configuration><gui enabled="true" tls="true">'
            f"<address>127.0.0.1:{server.port}</address><apikey>{API_KEY}</apikey>"
            "</gui></configuration>",
            encoding="utf-8",
        )
        started = rpc(backend, "start_syncthing_activity_watch", "pre_game", GAME, APP_ID)
        assert started["status"] == "watching", started
        assert (
            rpc(backend, "stop_syncthing_activity_watch", started["watch_id"])["status"]
            == "stopped"
        )
        assert any(path.startswith("/rest/system/status") for path in server.requests)
    finally:
        server.close()


@pytest.mark.contract_syncthing
def test_syncthing_watch_start_classifies_configuration_and_peer_failures(
    backend: ContractHarness,
) -> None:
    def start() -> dict[str, Any]:
        return rpc(backend, "start_syncthing_activity_watch", "pre_game", GAME, APP_ID)

    assert start()["reason"] == "not_configured"
    config = backend.xdg_state / "syncthing" / "config.xml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("<configuration><gui><address>127.0.0.1:8384</address></gui></configuration>")
    assert start()["reason"] == "api_unavailable"

    with _syncthing(backend) as server:
        folder = {
            "id": "contract-folder",
            "path": str(backend.backup_root),
            "devices": [{"deviceID": "CONTRACT-LOCAL-DEVICE"}],
        }
        server.response_overrides["/rest/config/folders"] = [folder]
        assert start()["reason"] == "folder_not_shared"
        folder["devices"].append({"deviceID": DEVICE_ID})
        server.response_overrides["/rest/system/connections"] = {
            "connections": {DEVICE_ID: {"connected": False}, "UNRELATED": {"connected": True}}
        }
        result = start()
        assert result["reason"] == "no_connected_peers"
        assert DEVICE_ID not in result["message"]
        assert "UNRELATED" not in result["message"]

    assert start()["reason"] == "api_unavailable"


@pytest.mark.contract_syncthing
@pytest.mark.contract_theme
def test_syncthing_watch_redacts_device_ids_and_uninstall_is_scoped(
    backend: ContractHarness,
) -> None:
    keep_dir = backend.decky_home / "themes" / "Keep Existing Theme"
    keep_dir.mkdir(parents=True)
    (keep_dir / "keep.css").write_text("owned elsewhere", encoding="utf-8")
    with _syncthing(backend) as server:
        started = rpc(
            backend,
            "start_syncthing_activity_watch",
            "pre_game",
            GAME,
            APP_ID,
        )
        assert started["status"] == "watching"
        assert isinstance(started["watch_id"], str) and started["watch_id"]
        assert started["folder_id"] == "contract-folder"
        assert started["label"] == "Contract Folder"
        assert started["path"] == str(backend.backup_root.resolve())
        assert type(started["detection_grace_ms"]) is int

        def read_settled() -> dict[str, Any] | None:
            current = rpc(backend, "get_syncthing_activity", started["watch_id"])
            sample = current.get("sample")
            if (
                isinstance(sample, dict)
                and sample.get("status") == "IDLE"
                and sample.get("folder_state") == "idle"
                and sample.get("settled") is True
            ):
                return current
            return None

        activity = _wait_for(
            read_settled,
            5,
            "Syncthing watch did not poll through scanning to a settled idle sample",
        )
        sample = activity["sample"]
        assert activity["status"] == "activity"
        assert activity["watch_id"] == started["watch_id"]
        assert type(sample["update_in_progress"]) is bool
        assert sample["update_in_progress"] is False
        assert sample["settled"] is True
        assert type(sample["downloading"]) is bool and sample["downloading"] is False
        assert type(sample["uploading"]) is bool and sample["uploading"] is False
        assert isinstance(sample["timestamp_unix"], int | float)
        assert not isinstance(sample["timestamp_unix"], bool)
        with server._request_lock:
            requested_routes = {path.split("?", 1)[0] for path in server.requests}
            status_requests = server._status_request_count
        assert status_requests >= 2, "Syncthing returned only its initialization state"
        assert {
            "/rest/system/status",
            "/rest/config/folders",
            "/rest/system/connections",
            "/rest/db/status",
            "/rest/events",
        } <= requested_routes

        stopped = rpc(backend, "stop_syncthing_activity_watch", started["watch_id"])
        assert stopped["status"] == "stopped"
        final_activity = rpc(backend, "get_syncthing_activity", started["watch_id"])
        assert final_activity["status"] == "stopped"
        assert final_activity["watch_id"] == started["watch_id"]
        results = [started, activity, stopped, final_activity, rpc(backend, "get_recent_logs")]
        serialized_results = json.dumps(results)
        assert DEVICE_ID not in serialized_results
        assert API_KEY not in serialized_results
        plugin_logs = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in backend.log_dir.rglob("*")
            if path.is_file()
        )
        assert DEVICE_ID not in plugin_logs
        assert API_KEY not in plugin_logs

    managed_theme = backend.decky_home / "themes" / "SDH-Ludusavi Status"
    assert managed_theme.is_dir()
    backend.uninstall()
    assert not managed_theme.exists()
    assert (keep_dir / "keep.css").read_text(encoding="utf-8") == "owned elsewhere"


@pytest.mark.contract_syncthing
def test_syncthing_does_not_follow_non_loopback_redirect(backend: ContractHarness) -> None:
    with _syncthing(backend, redirect_non_loopback=True) as server:
        result = rpc(
            backend,
            "start_syncthing_activity_watch",
            "pre_game",
            GAME,
            APP_ID,
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "api_unavailable"
        with server._request_lock:
            status_requests = sum(
                path.split("?", 1)[0] == "/rest/system/status" for path in server.requests
            )
        assert status_requests == 1


@pytest.mark.contract_syncthing
def test_syncthing_falls_back_to_home_config_when_xdg_is_set(backend: ContractHarness) -> None:
    with _syncthing(backend):
        original = backend.xdg_state / "syncthing" / "config.xml"
        fallback = backend.home / ".local" / "state" / "syncthing" / "config.xml"
        fallback.parent.mkdir(parents=True)
        original.rename(fallback)
        watch = rpc(backend, "start_syncthing_activity_watch", "pre_game", GAME, APP_ID)
        assert watch["status"] == "watching", watch
        rpc(backend, "stop_syncthing_activity_watch", watch["watch_id"])


@pytest.mark.contract_syncthing
def test_syncthing_prefers_current_flatpak_config() -> None:
    harness = ContractHarness()
    harness.env["FLATPAK_ID"] = "z.contract.syncthing"
    current = _SyncthingServer(harness.backup_root).start()
    other = _SyncthingServer(harness.backup_root).start()
    try:
        for app_id, server in [
            ("z.contract.syncthing", current),
            ("com.github.zocker_160.SyncThingy", other),
        ]:
            config = harness.home / ".var" / "app" / app_id / "config" / "syncthing" / "config.xml"
            config.parent.mkdir(parents=True)
            config.write_text(
                f"<configuration><gui><address>127.0.0.1:{server.port}</address>"
                f"<apikey>{API_KEY}</apikey></gui></configuration>",
                encoding="utf-8",
            )
        harness.start()
        watch = rpc(harness, "start_syncthing_activity_watch", "pre_game", GAME, APP_ID)
        assert watch["status"] == "watching", watch
        assert current.requests, "current Flatpak configuration was not selected"
        assert not other.requests, "another Flatpak configuration took precedence"
        rpc(harness, "stop_syncthing_activity_watch", watch["watch_id"])
    finally:
        harness.close()
        current.close()
        other.close()


@pytest.mark.contract_syncthing
def test_post_game_baseline_observes_second_folder_status(backend: ContractHarness) -> None:
    with _syncthing(backend, hold_second_status=True) as server:
        watch = rpc(backend, "start_syncthing_activity_watch", "post_game", GAME, APP_ID)
        assert watch["status"] == "watching", watch
        assert server.second_status_waiting.wait(timeout=3)
        sample = rpc(backend, "get_syncthing_activity", watch["watch_id"])
        assert sample["sample"].get("settled") is not True, "baseline settled before second status"
        server.release_second_status.set()

        def uploading() -> dict[str, Any] | None:
            activity = rpc(backend, "get_syncthing_activity", watch["watch_id"])
            return activity if activity.get("sample", {}).get("uploading") is True else None

        _wait_for(uploading, 3, "new local sequence did not require a fresh peer confirmation")
        rpc(backend, "stop_syncthing_activity_watch", watch["watch_id"])


@pytest.mark.contract_syncthing
def test_syncthing_event_cursor_recovers_after_subscription_reset(backend: ContractHarness) -> None:
    with _syncthing(backend, reset_event_cursor=True) as server:
        watch = rpc(backend, "start_syncthing_activity_watch", "pre_game", GAME, APP_ID)
        assert watch["status"] == "watching", watch

        def recovered() -> bool:
            with server._request_lock:
                return any(
                    parse_qs(urlsplit(path).query).get("since") == ["1"]
                    for path in server.requests
                    if path.startswith("/rest/events?")
                )

        assert _wait_for(recovered, 4, "event subscription did not recover its reset cursor")
        rpc(backend, "stop_syncthing_activity_watch", watch["watch_id"])


@pytest.mark.contract_syncthing
def test_config_saved_refreshes_folder_before_publishing_events(backend: ContractHarness) -> None:
    with _syncthing(backend, refresh_on_config=True) as server:
        watch = rpc(backend, "start_syncthing_activity_watch", "pre_game", GAME, APP_ID)
        assert watch["status"] == "watching", watch
        assert server.config_refresh_waiting.wait(timeout=3), "config change did not refresh status"
        activity = rpc(backend, "get_syncthing_activity", watch["watch_id"])
        assert activity["sample"]["folder_state"] == "idle"
        server.release_config_refresh.set()
        rpc(backend, "stop_syncthing_activity_watch", watch["watch_id"])


@pytest.mark.contract_operations
@pytest.mark.contract_lifecycle
@pytest.mark.contract_gate
def test_hanging_ludusavi_exits_and_reaps_process_group(
    backend: ContractHarness, request: pytest.FixtureRequest
) -> None:
    child = _start_prescope_child(backend.root, request)
    scoped_child: _Child | None = None
    try:
        scoped_child = _start_scoped_child(backend.root, request)
        backend.set_scenario(
            {
                "flatpak": {
                    "responses": {
                        "backup": {
                            "delay_seconds": 600,
                            "ignore_term": True,
                            "spawn_child": True,
                        }
                    }
                },
                "systemctl": {
                    "simulate_scope_freeze": True,
                    "scope_unit": scoped_child.unit,
                },
            }
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            operation = pool.submit(backend.call, "force_backup", GAME, timeout=190)
            hanging = _wait_for(
                lambda: next(
                    (
                        record
                        for record in backend.fake_processes()
                        if record["command_args"][:1] == ["backup"]
                        and "--preview" not in record["command_args"]
                    ),
                    None,
                ),
                10,
                "hanging Ludusavi command did not start",
            )
            paused = rpc(backend, "pause_game_process", child.pid)
            assert paused["status"] == "paused", paused
            assert paused["pid"] == child.pid
            assert isinstance(paused["lease_id"], str) and paused["lease_id"]
            assert _proc_state(child.pid) == "T", "pre-scope launch PID did not enter SIGSTOP state"
            lease_id = paused["lease_id"]
            original_deadline = time.monotonic() + paused["lease_ttl_seconds"]
            frozen_ticks = _tick_count(child)
            scoped_pause_started = time.monotonic()
            scoped_paused = rpc(backend, "pause_game_process", scoped_child.pid)
            assert scoped_paused["status"] == "paused", scoped_paused
            assert scoped_paused["pid"] == scoped_child.pid
            scoped_expiry_deadline = scoped_pause_started + scoped_paused["lease_ttl_seconds"] + 5
            assert _scope_frozen(scoped_child), "scoped lease did not freeze its cgroup"
            scoped_ticks_at_expiry = _tick_count(scoped_child)

            time.sleep(max(0.0, paused["lease_ttl_seconds"] - 2.0))
            renewed = rpc(backend, "renew_game_process_pause", child.pid, lease_id)
            assert renewed["status"] == "renewed"
            assert renewed["pid"] == child.pid
            assert renewed["lease_ttl_seconds"] > 0
            _wait_for(
                lambda: time.monotonic() >= original_deadline + 1,
                5,
                "original pause lease deadline was not reached after renewal",
            )
            assert _proc_state(child.pid) == "T", "renewal did not extend the pre-scope lease"
            assert _tick_count(child) == frozen_ticks, (
                "renewed pre-scope PID progressed while stopped"
            )
            assert not _scope_frozen(scoped_child) or _wait_for(
                lambda: not _scope_frozen(scoped_child),
                max(0.0, scoped_expiry_deadline - time.monotonic()),
                "expired scoped lease did not thaw its cgroup",
            )
            assert _wait_for(
                lambda: _tick_count(scoped_child) > scoped_ticks_at_expiry,
                3,
                "expired scoped lease did not allow child progress",
            )

            resumed = rpc(backend, "resume_game_process", child.pid, lease_id)
            assert resumed["status"] == "resumed"
            assert resumed["pid"] == child.pid
            assert _wait_for(
                lambda: _proc_state(child.pid) != "T" and _tick_count(child) > frozen_ticks,
                3,
                "explicit resume did not release the pre-scope launch PID",
            )

            expiring = rpc(backend, "pause_game_process", child.pid)
            assert expiring["status"] == "paused"
            assert _proc_state(child.pid) == "T"
            ticks_at_expiry = _tick_count(child)
            _wait_for(
                lambda: _proc_state(child.pid) != "T",
                expiring["lease_ttl_seconds"] + 5,
                "unrenewed pre-scope pause lease did not release SIGSTOP at expiry",
            )
            assert _wait_for(
                lambda: _tick_count(child) > ticks_at_expiry,
                3,
                "expired pre-scope lease did not allow child progress",
            )

            success, result = operation.result(timeout=190)
        assert success is True
        assert result["status"] == "failed"
        assert "timeout" in result["message"].lower()
        pgid = hanging["pgid"]
        _wait_for(
            lambda: not _process_group_exists(pgid),
            3,
            f"fake Ludusavi process group {pgid} survived the operation timeout",
        )
    finally:
        _stop_children(child, scoped_child)


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.contract_operations
@pytest.mark.contract_lifecycle
@pytest.mark.contract_gate
@pytest.mark.contract_syncthing
def test_unload_kills_restore_group_before_releasing_paused_child(
    request: pytest.FixtureRequest,
) -> None:
    scenario: dict[str, Any] = {
        "flatpak": {
            "responses": {
                "restore": {
                    "delay_seconds": 600,
                    "ignore_term": True,
                    "spawn_child": True,
                }
            }
        }
    }
    harness = ContractHarness(scenario=scenario)
    request.addfinalizer(harness.close)
    server = _SyncthingServer(harness.backup_root, hold_watch_events=True).start()
    request.addfinalizer(server.close)
    harness.env.update(
        {"SYNCTHING_API_KEY": API_KEY, "SYNCTHING_API_URL": f"http://127.0.0.1:{server.port}"}
    )
    harness.start()
    child = _start_prescope_child(harness.root, request)
    operation_pool = ThreadPoolExecutor(max_workers=1)
    shutdown_pool = ThreadPoolExecutor(max_workers=1)
    stop_future: Future[None] | None = None
    scoped_child: _Child | None = None
    try:
        scoped_child = _start_scoped_child(harness.root, request)
        scenario["systemctl"] = {
            "simulate_scope_freeze": True,
            "scope_unit": scoped_child.unit,
        }
        harness.set_scenario(scenario)
        assert rpc(harness, "update_settings", {"kind": "auto_sync", "enabled": True})[
            "auto_sync_enabled"
        ]
        assert rpc(
            harness,
            "update_settings",
            {"kind": "game_sync", "game_name": GAME, "enabled": True},
        )["auto_sync_enabled"]
        refreshed = rpc(harness, "refresh_games", True, APP_ID)
        assert any(game["name"] == GAME and game["has_backup"] for game in refreshed["games"]), (
            refreshed
        )
        paused = rpc(harness, "pause_game_process", child.pid)
        assert paused["status"] == "paused", paused
        assert paused["pid"] == child.pid
        assert isinstance(paused["lease_id"], str) and paused["lease_id"]
        assert _proc_state(child.pid) == "T", "pre-scope launch PID was not held by SIGSTOP"
        scoped_paused = rpc(harness, "pause_game_process", scoped_child.pid)
        assert scoped_paused["status"] == "paused", scoped_paused
        assert scoped_paused["pid"] == scoped_child.pid
        assert _scope_frozen(scoped_child), "scoped game child was not frozen before unload"
        scoped_frozen_ticks = _tick_count(scoped_child)
        operation = operation_pool.submit(harness.call, "force_restore", GAME, timeout=30)

        def restore_started() -> dict[str, Any] | None:
            record = next(
                (
                    record
                    for record in harness.fake_processes()
                    if record["command_args"][:1] == ["restore"]
                    and "--preview" not in record["command_args"]
                ),
                None,
            )
            if record is not None:
                return record
            if operation.done():
                return {"reply": operation.result()}
            return None

        hanging = _wait_for(restore_started, 10, "slow restore did not start")
        assert "argv" in hanging, f"restore returned before command spawn: {hanging['reply']!r}"
        fake_pid = hanging["pid"]
        _wait_for(
            lambda: bool(
                Path(f"/proc/{fake_pid}/task/{fake_pid}/children")
                .read_text(encoding="ascii")
                .strip()
            ),
            5,
            "fake Ludusavi did not install its TERM handler and spawn its child",
        )
        assert not operation.done(), "restore RPC unexpectedly completed before backend shutdown"
        watch = rpc(harness, "start_syncthing_activity_watch", "post_game", GAME, APP_ID)
        assert watch["status"] == "watching", watch
        assert server.watch_event_waiting.wait(timeout=3), (
            "post-game watch did not enter event poll"
        )
        stop_started = time.monotonic()
        stop_future = shutdown_pool.submit(harness.stop)
        observed_unsafe_release = False
        observed_ordered_release = False
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if (
                _proc_state(child.pid) != "T" or not _scope_frozen(scoped_child)
            ) and _process_group_exists(hanging["pgid"]):
                observed_unsafe_release = True
                break
            if _proc_state(child.pid) != "T" and not _scope_frozen(scoped_child):
                observed_ordered_release = True
                assert not stop_future.done(), "watch stopped before launch gates were released"
                server.release_watch_event.set()
                break
            if stop_future.done():
                break
            time.sleep(0.01)
        stop_future.result(timeout=6)
        stop_seconds = time.monotonic() - stop_started
        assert stop_seconds < 5, f"SIGTERM unload with post-game watch took {stop_seconds:.3f}s"
        print(f"SIGTERM unload with post-game watch and both launch gates: {stop_seconds:.3f}s")
        assert observed_ordered_release, "launch gates did not release while the watch was active"
        assert not observed_unsafe_release, (
            "a launch gate was released while its Ludusavi process group was still alive"
        )
        assert not _process_group_exists(hanging["pgid"])
        assert _proc_state(child.pid) != "T", "backend unload left the launch PID stopped"
        assert not _scope_frozen(scoped_child), "backend unload left the scoped app cgroup frozen"
        assert _wait_for(
            lambda: _tick_count(scoped_child) > scoped_frozen_ticks,
            3,
            "unloaded backend did not release scoped child progress",
        )
        with pytest.raises(ConnectionError, match="backend is shutting down"):
            operation.result(timeout=1)
    finally:
        with ExitStack() as cleanup:
            cleanup.callback(server.close)
            cleanup.callback(shutdown_pool.shutdown, wait=True, cancel_futures=True)
            cleanup.callback(operation_pool.shutdown, wait=True, cancel_futures=True)
            cleanup.callback(harness.close)
            cleanup.callback(_stop_children, child, scoped_child)
            cleanup.callback(server.release_watch_event.set)


@pytest.mark.contract_operations
@pytest.mark.contract_lifecycle
@pytest.mark.real_ludusavi
def test_real_ludusavi_backup_restore_versions_and_newer_local_guard(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    binary = os.environ.get("SDH_CONTRACT_LUDUSAVI_BIN")
    if not binary:
        message = "SDH_CONTRACT_LUDUSAVI_BIN is required for the real_ludusavi tier"
        if os.environ.get("SDH_CONTRACT_REQUIRE_REAL") == "1":
            pytest.fail(message)
        pytest.skip(message)

    monkeypatch.setenv("SDH_CONTRACT_LUDUSAVI_BIN", binary)
    harness = ContractHarness(scenario={"flatpak": {"mode": "real"}})
    save = Path(harness.env["SDH_CONTRACT_SAVE_FILE"])
    config = harness.config_dir / "config.yaml"
    config_data = _load_fixture("config-show.json")
    config_data["backup"]["path"] = str(harness.backup_root)
    config_data["restore"]["path"] = str(harness.backup_root)
    config_data["customGames"][0]["name"] = GAME
    config_data["customGames"][0]["files"] = [str(save)]
    config.write_text(json.dumps(config_data), encoding="utf-8")
    harness.start()
    try:
        versions = rpc(harness, "get_versions")
        assert versions.get("ludusavi") == "0.31.0", versions
        save.write_bytes(b"contract save version A\x00\n")
        assert rpc(harness, "force_backup", GAME)["status"] == "backed_up"

        save.write_bytes(b"contract save version B\x00\n")
        restore_result = rpc(harness, "force_restore", GAME)
        assert restore_result["status"] == "restored", restore_result
        assert save.read_bytes() == b"contract save version A\x00\n", (
            f"real force_restore returned {restore_result!r}; argv={harness.fake_processes()!r}"
        )

        save.write_bytes(b"contract save version B\x00\n")
        # Ludusavi backup IDs only carry seconds; keep these real snapshots distinct.
        time.sleep(1.1)
        assert rpc(harness, "force_backup", GAME)["status"] == "backed_up"
        backups = rpc(harness, "list_backups", GAME)["backups"]
        assert len(backups) >= 2
        oldest = min(backups, key=lambda snapshot: snapshot["when"])
        version_restore_ok, selected_restore = harness.call(
            "restore_backup_version", GAME, oldest["id"]
        )
        assert save.read_bytes() == b"contract save version A\x00\n", (
            f"selected-version restore returned success={version_restore_ok}, "
            f"result={selected_restore!r}"
        )
        assert version_restore_ok
        assert selected_restore["status"] == "restored"

        history = rpc(harness, "get_game_history")[GAME]
        assert history["last_backup"]["operation"] == "backup"
        assert history["last_restore"]["operation"] == "restore"

        save.write_bytes(b"newer local version C\x00\n")
        future = time.time() + 300
        os.utime(save, (future, future))
        assert rpc(harness, "update_settings", {"kind": "auto_sync", "enabled": True})[
            "auto_sync_enabled"
        ]
        rpc(
            harness,
            "update_settings",
            {"kind": "game_sync", "game_name": GAME, "enabled": True},
        )
        rpc(harness, "refresh_games", True, APP_ID)
        restore_count = sum(
            record["command_args"][:1] == ["restore"] and "--preview" not in record["command_args"]
            for record in harness.fake_processes()
        )
        check = rpc(harness, "check_game_start", GAME, APP_ID)
        if check["status"] == "needed":
            child = _start_scoped_child(harness.root, request)
            harness.set_scenario(
                {
                    "flatpak": {"mode": "real"},
                    "systemctl": {
                        "simulate_scope_freeze": True,
                        "scope_unit": child.unit,
                    },
                }
            )
            try:
                gate = rpc(harness, "pause_game_process", child.pid)
                assert gate["status"] == "paused", gate
                assert (
                    rpc(
                        harness,
                        "restore_game_on_start",
                        GAME,
                        APP_ID,
                        child.pid,
                        gate["lease_id"],
                    )["status"]
                    == "restored"
                )
            finally:
                _stop_child(child)
        else:
            assert check["status"] == "conflict"
        assert save.read_bytes() == b"newer local version C\x00\n"
        assert (
            sum(
                record["command_args"][:1] == ["restore"]
                and "--preview" not in record["command_args"]
                for record in harness.fake_processes()
            )
            == restore_count
        )
    finally:
        harness.close()


def test_native_sdk_protocol_positive_control() -> None:
    backend = os.environ.get("SDH_CONTRACT_SDK_EXAMPLE")
    if not backend:
        pytest.skip("set SDH_CONTRACT_SDK_EXAMPLE to the compiled SDK example")
    harness = ContractHarness(backend=backend).start()
    process = harness.process
    try:
        assert rpc(harness, "echo", "contract", 42) == ["contract", 42]
        environment = rpc(harness, "environment")
        assert environment["name"] == "SDH-Ludusavi"
        assert environment["user"] == "contract-user"
        assert environment["settings"] == str(harness.settings_dir)
        assert rpc(harness, "notify", "native", "event") is None
        assert harness.events[-1] == {
            "type": 2,
            "event": "example_event",
            "args": ["native", "event"],
        }
    finally:
        try:
            if harness.process is not None:
                harness.stop()
        finally:
            harness.close()
    assert process is not None and process.returncode == 0
