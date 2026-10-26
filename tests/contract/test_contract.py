from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Iterator

import pytest

from harness import ContractHarness, FAKE_BIN


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
        len(record["argv"]) > 2 and record["argv"][2] == verb and "--preview" not in record["argv"]
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
class _Child:
    pid: int
    process: subprocess.Popen[bytes]
    unit: str
    tick_file: Path


def _start_systemd_child(root: Path, unit: str, systemd_args: list[str]) -> _Child:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        pytest.fail("systemd-run is required to create an isolated child")
    pid_file = root / f"{unit}.pid"
    tick_file = root / f"{unit}.tick"
    code = (
        "import os,sys,time\n"
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

    def read_pid() -> int | None:
        if not pid_file.exists():
            return None
        try:
            return int(pid_file.read_text(encoding="ascii"))
        except ValueError:
            return None

    pid = _wait_for(
        read_pid,
        10,
        f"systemd-run did not start {unit}: "
        f"{process.stderr.read().decode(errors='replace') if process.poll() is not None else ''}",
    )
    _wait_for(lambda: tick_file.exists(), 5, "systemd child heartbeat did not start")
    return _Child(pid, process, unit, tick_file)


def _start_scoped_child(root: Path) -> _Child:
    unit = f"app-steam-app{APP_ID}-{time.time_ns() % 1_000_000_000}.scope"
    return _start_systemd_child(
        root,
        unit,
        ["--user", "--scope", "--slice=app.slice", f"--unit={unit}", "--quiet"],
    )


def _start_prescope_child(root: Path) -> _Child:
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        pytest.fail("systemctl is required to verify the exact pre-scope path")
    existing = subprocess.run(
        [
            systemctl,
            "--user",
            "show",
            "steam-launcher.service",
            "--property=LoadState",
            "--value",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if existing.returncode != 0:
        pytest.fail(f"cannot verify pre-scope unit availability: {existing.stderr.strip()}")
    if existing.stdout.strip() not in {"", "not-found"}:
        pytest.fail("steam-launcher.service is already loaded; refusing to replace it")
    return _start_systemd_child(
        root,
        "steam-launcher.service",
        [
            "--user",
            "--unit=steam-launcher.service",
            "--slice=app.slice",
            "--wait",
            "--collect",
            "--quiet",
        ],
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


def _force_scope_thaw(harness: ContractHarness, child: _Child) -> None:
    subprocess.run(
        [str(FAKE_BIN / "systemctl"), "--user", "thaw", child.unit],
        env=harness.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _stop_child(child: _Child) -> None:
    if child.process.poll() is None:
        for signum in (signal.SIGCONT, signal.SIGTERM):
            try:
                os.kill(child.pid, signum)
            except ProcessLookupError:
                pass
        try:
            child.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.kill(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.process.wait(timeout=2)


class _SyncthingServer:
    def __init__(self, backup_path: Path) -> None:
        self.backup_path = backup_path
        self.requests: list[str] = []
        self._request_lock = threading.Lock()
        self._status_request_count = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = self.path.split("?", 1)[0]
                with owner._request_lock:
                    owner.requests.append(self.path)
                    if route == "/rest/db/status":
                        owner._status_request_count += 1
                    status_request_count = owner._status_request_count
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
                responses["/rest/db/status"]["state"] = (
                    "scanning" if status_request_count == 1 else "idle"
                )
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
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@contextmanager
def _syncthing(harness: ContractHarness) -> Iterator[_SyncthingServer]:
    server = _SyncthingServer(harness.backup_root).start()
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


def test_settings_cache_shortcut_theme_protocol_and_concurrent_calls(
    backend: ContractHarness,
) -> None:
    settings = rpc(backend, "get_settings")
    assert settings["auto_sync_enabled"] is False
    assert settings["selected_game"] == ""
    assert settings["update_channel"] == "stable"
    assert rpc(backend, "consume_theme_refresh_needed") is True
    assert rpc(backend, "consume_theme_refresh_needed") is False

    theme = backend.decky_home / "themes" / "SDH-Ludusavi Status"
    assert (theme / "theme.json").is_file()
    unrelated_theme = backend.decky_home / "themes" / "Keep Existing Theme"
    unrelated_theme.mkdir(parents=True)
    (unrelated_theme / "keep.css").write_text("owned elsewhere", encoding="utf-8")

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

    backend.uninstall()
    assert not theme.exists()
    assert (unrelated_theme / "keep.css").read_text(encoding="utf-8") == "owned elsewhere"

    theme.mkdir()
    unowned_file = theme / "owned-by-someone-else.txt"
    unowned_file.write_text("preserve this theme", encoding="utf-8")
    backend.start()
    backend.uninstall()
    assert unowned_file.read_text(encoding="utf-8") == "preserve this theme"


def test_operations_logs_status_lock_and_local_update_state(backend: ContractHarness) -> None:
    versions = rpc(backend, "get_versions")
    assert versions["ludusavi"] == "0.31.0"
    assert "pyludusavi" in versions
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
        len(record["argv"]) > 2
        and record["argv"][2] == "restore"
        and "--force" in record["argv"][2:]
        for record in records
    )
    assert any(
        len(record["argv"]) > 2
        and record["argv"][2] == "restore"
        and _option_value(record["argv"][2:], "--backup") == backup_id
        for record in records
    )

    backend.set_scenario({"flatpak": {"responses": {"backup": {"delay_seconds": 0.8}}}})
    prior_record_count = len(backend.fake_processes())
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(backend.call, "force_backup", GAME)
        _wait_for(
            lambda: any(
                "backup" in record["argv"] and "--preview" not in record["argv"]
                for record in backend.fake_processes()[prior_record_count:]
            ),
            5,
            "slow fake backup did not start",
        )
        locked = rpc(backend, "force_restore", GAME)
        assert locked["status"] == "skipped"
        assert locked["reason"] == "operation_running"
        status = rpc(backend, "get_operation_status")
        assert status["is_running"] is True
        assert status["name"] == "backup"
        assert status["game_name"] == GAME
        success, result = first.result(timeout=10)
    assert success is True and result["status"] == "backed_up"
    assert rpc(backend, "get_operation_status")["is_running"] is False

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


def test_lifecycle_newer_save_guard_and_launch_gate_contract(backend: ContractHarness) -> None:
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
        record["argv"][2] == "restore" and "--preview" not in record["argv"]
        for record in backend.fake_processes()
        if len(record["argv"]) > 2
    )
    start_check = rpc(backend, "check_game_start", GAME, APP_ID)
    assert start_check["status"] == "conflict"
    after_restore = sum(
        record["argv"][2] == "restore" and "--preview" not in record["argv"]
        for record in backend.fake_processes()
        if len(record["argv"]) > 2
    )
    assert after_restore == before_restore, "a newer local save triggered a real restore"

    exit_check = rpc(backend, "check_game_exit", GAME, APP_ID)
    assert exit_check["status"] == "needed"
    assert exit_check["operation"] == "backup"
    before_exit_backup = len(backend.fake_processes())
    assert rpc(backend, "backup_game_on_exit", GAME, APP_ID)["status"] == "backed_up"
    _assert_command_after(backend, before_exit_backup, "backup")
    _assert_history_entry(backend, "last_backup", "backup", "auto_exit", "backed_up")
    child = _start_scoped_child(backend.root)
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
        _force_scope_thaw(backend, child)
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


def test_hanging_ludusavi_exits_and_reaps_process_group(backend: ContractHarness) -> None:
    child = _start_prescope_child(backend.root)
    scoped_child: _Child | None = None
    try:
        scoped_child = _start_scoped_child(backend.root)
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
                        if len(record["argv"]) > 2
                        and record["argv"][2] == "backup"
                        and "--preview" not in record["argv"]
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
            scoped_paused = rpc(backend, "pause_game_process", scoped_child.pid)
            assert scoped_paused["status"] == "paused", scoped_paused
            assert scoped_paused["pid"] == scoped_child.pid
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
            assert _wait_for(
                lambda: not _scope_frozen(scoped_child),
                scoped_paused["lease_ttl_seconds"] + 5,
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
        if scoped_child is not None:
            _force_scope_thaw(backend, scoped_child)
            _stop_child(scoped_child)
        _stop_child(child)


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_unload_kills_restore_group_before_releasing_paused_child() -> None:
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
    harness = ContractHarness(scenario=scenario).start()
    child = _start_prescope_child(harness.root)
    operation_pool = ThreadPoolExecutor(max_workers=1)
    shutdown_pool = ThreadPoolExecutor(max_workers=1)
    stop_future: Future[None] | None = None
    scoped_child: _Child | None = None
    try:
        scoped_child = _start_scoped_child(harness.root)
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
                    if len(record["argv"]) > 2
                    and record["argv"][2] == "restore"
                    and "--preview" not in record["argv"]
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
        stop_future = shutdown_pool.submit(harness.stop)
        observed_unsafe_release = False
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if (
                _proc_state(child.pid) != "T" or not _scope_frozen(scoped_child)
            ) and _process_group_exists(hanging["pgid"]):
                observed_unsafe_release = True
                break
            if stop_future.done():
                break
            time.sleep(0.01)
        stop_future.result(timeout=6)
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
        if scoped_child is not None:
            _force_scope_thaw(harness, scoped_child)
            _stop_child(scoped_child)
        _stop_child(child)
        try:
            harness.close()
        finally:
            operation_pool.shutdown(wait=True, cancel_futures=True)
            shutdown_pool.shutdown(wait=True, cancel_futures=True)


@pytest.mark.real_ludusavi
def test_real_ludusavi_backup_restore_versions_and_newer_local_guard(
    monkeypatch: pytest.MonkeyPatch,
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
        assert rpc(harness, "get_versions")["ludusavi"] == "0.31.0"
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
            record["argv"][2] == "restore" and "--preview" not in record["argv"]
            for record in harness.fake_processes()
            if len(record["argv"]) > 2
        )
        check = rpc(harness, "check_game_start", GAME, APP_ID)
        if check["status"] == "needed":
            child = _start_scoped_child(harness.root)
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
                _force_scope_thaw(harness, child)
                _stop_child(child)
        else:
            assert check["status"] == "conflict"
        assert save.read_bytes() == b"newer local version C\x00\n"
        assert (
            sum(
                record["argv"][2] == "restore" and "--preview" not in record["argv"]
                for record in harness.fake_processes()
                if len(record["argv"]) > 2
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
