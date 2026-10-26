from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


@dataclass
class _Child:
    pid: int
    process: subprocess.Popen[bytes]
    unit: str
    tick_file: Path


def _start_scoped_child(root: Path) -> _Child:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        pytest.fail("systemd-run is required to create an isolated Steam app scope")
    unit = f"app-steam-app{APP_ID}-{time.time_ns() % 1_000_000_000}.scope"
    pid_file = root / "scoped-child.pid"
    tick_file = root / "scoped-child.tick"
    code = (
        "import os,sys,time\n"
        "pid_file, tick_file = sys.argv[1:]\n"
        "open(pid_file, 'w').write(str(os.getpid()))\n"
        "tick = 0\n"
        "while True:\n"
        "    with open(tick_file, 'w') as stream:\n"
        "        stream.write(str(tick))\n"
        "    tick += 1\n"
        "    time.sleep(0.01)\n"
    )
    process = subprocess.Popen(
        [
            systemd_run,
            "--user",
            "--scope",
            "--slice=app.slice",
            f"--unit={unit}",
            "--quiet",
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
    _wait_for(lambda: tick_file.exists(), 5, "scoped child heartbeat did not start")
    return _Child(pid, process, unit, tick_file)


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
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = self.path.split("?", 1)[0]
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
    assert history[GAME]["last_backup"]["operation"] == "backup"
    cache = json.loads((backend.runtime_dir / "cache.json").read_text(encoding="utf-8"))
    assert cache["game_history"][GAME]["last_backup"]["status"] == "backed_up"

    backend.uninstall()
    assert not theme.exists()
    assert (unrelated_theme / "keep.css").read_text(encoding="utf-8") == "owned elsewhere"


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
    assert backups["game"] == GAME
    assert len(backups["backups"]) == 2
    backup_id = backups["backups"][-1]["id"]
    assert rpc(backend, "restore_backup_version", GAME, backup_id)["status"] == "restored"
    assert any(
        record["argv"][2:4] == ["restore", "--force"] and backup_id in record["argv"]
        for record in backend.fake_processes()
    )

    backend.set_scenario({"flatpak": {"responses": {"backup": {"delay_seconds": 0.8}}}})
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(backend.call, "force_backup", GAME)
        _wait_for(
            lambda: any(
                "backup" in record["argv"] and "--preview" not in record["argv"]
                for record in backend.fake_processes()
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
    assert rpc(backend, "backup_game_on_exit", GAME, APP_ID)["status"] == "backed_up"
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
        lease_id = paused["lease_id"]
        assert _scope_frozen(child), "scope freezer did not hold the child"
        frozen_ticks = _tick_count(child)
        time.sleep(0.1)
        assert _tick_count(child) == frozen_ticks, "scope child continued running while frozen"

        wrong = rpc(backend, "renew_game_process_pause", child.pid, "wrong-contract-lease")
        assert wrong["status"] in {"skipped", "failed"}
        renewed = rpc(backend, "renew_game_process_pause", child.pid, lease_id)
        assert renewed["status"] == "renewed"
        assert (
            rpc(
                backend,
                "resolve_game_start_conflict",
                GAME,
                APP_ID,
                "keep_local",
                child.pid,
                lease_id,
            )["status"]
            == "backed_up"
        )
        assert (
            rpc(
                backend,
                "resolve_game_start_conflict",
                GAME,
                APP_ID,
                "restore_backup",
                child.pid,
                lease_id,
            )["status"]
            == "restored"
        )
        assert (
            rpc(
                backend,
                "restore_game_on_start",
                GAME,
                APP_ID,
                child.pid,
                lease_id,
            )["status"]
            == "restored"
        )
        ticks_before_resume = _tick_count(child)
        assert rpc(backend, "resume_game_process", child.pid, lease_id)["status"] == "resumed"
        assert not _scope_frozen(child), "resume left the scope frozen"
        assert _wait_for(
            lambda: _tick_count(child) > ticks_before_resume,
            2,
            "resumed child did not make progress",
        )

        expiring = rpc(backend, "pause_game_process", child.pid)
        assert expiring["status"] == "paused"
        assert _scope_frozen(child)
        ticks_at_expiry = _tick_count(child)
        ttl = expiring["lease_ttl_seconds"]
        _wait_for(
            lambda: not _scope_frozen(child),
            ttl + 5,
            "an unrenewed pause lease did not resume within its TTL",
        )
        assert _wait_for(
            lambda: _tick_count(child) > ticks_at_expiry,
            2,
            "expired lease did not allow child progress",
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
    with _syncthing(backend):
        started = rpc(
            backend,
            "start_syncthing_activity_watch",
            "pre_game",
            GAME,
            APP_ID,
        )
        assert started["status"] == "watching"

        def read_sample() -> dict[str, Any] | None:
            current = rpc(backend, "get_syncthing_activity", started["watch_id"])
            return current if current.get("sample") else None

        activity = _wait_for(read_sample, 5, "Syncthing watch did not produce an activity sample")
        stopped = rpc(backend, "stop_syncthing_activity_watch", started["watch_id"])
        assert stopped["status"] == "stopped"
        results = [started, activity, stopped, rpc(backend, "get_recent_logs")]
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
            }
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


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_unload_kills_restore_group_before_releasing_paused_child() -> None:
    harness = ContractHarness(
        scenario={
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
    ).start()
    child = _start_scoped_child(harness.root)
    harness.set_scenario(
        {
            "flatpak": {
                "responses": {
                    "restore": {
                        "delay_seconds": 600,
                        "ignore_term": True,
                        "spawn_child": True,
                    }
                }
            },
            "systemctl": {
                "simulate_scope_freeze": True,
                "scope_unit": child.unit,
                "response_delay_seconds": 0.3,
            },
        }
    )
    try:
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
        assert _scope_frozen(child)
        operation_pool = ThreadPoolExecutor(max_workers=1)
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

        deadline = time.monotonic() + 10
        hanging = None
        while time.monotonic() < deadline:
            hanging = restore_started()
            if hanging is not None:
                break
            time.sleep(0.01)
        if hanging is None:
            status = rpc(harness, "get_operation_status")
            raise AssertionError(
                f"slow restore did not start; operation_done={operation.done()}, "
                f"status={status!r}, fake_processes={harness.fake_processes()!r}"
            )
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
        observed_unsafe_release = threading.Event()

        def stop_backend() -> None:
            harness.stop()

        stopper = threading.Thread(target=stop_backend)
        stopper.start()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if not _scope_frozen(child) and _process_group_exists(hanging["pgid"]):
                observed_unsafe_release.set()
                break
            if not stopper.is_alive():
                break
            time.sleep(0.01)
        stopper.join(timeout=6)
        assert not stopper.is_alive(), "backend exceeded its SIGTERM shutdown deadline"
        assert not observed_unsafe_release.is_set(), (
            "paused child resumed while its Ludusavi process group was still alive"
        )
        assert not _process_group_exists(hanging["pgid"])
        assert not _scope_frozen(child)
        with pytest.raises(Exception):
            operation.result(timeout=1)
        operation_pool.shutdown(wait=True)
    finally:
        _force_scope_thaw(harness, child)
        _stop_child(child)
        harness.close()


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
    backend = os.environ.get("SDH_CONTRACT_BACKEND", "python")
    if backend == "python":
        pytest.skip("set SDH_CONTRACT_BACKEND to the compiled SDK example")
    harness = ContractHarness().start()
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
