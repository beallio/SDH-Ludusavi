from __future__ import annotations

import ast
import json
import logging
import signal
import threading
import time
from pathlib import Path

import pytest

from sdh_ludusavi.service import JsonSettingsStore, OperationLockedError, SDHLudusaviService


class FakeAdapter:
    def __init__(self) -> None:
        self.games = [
            {
                "name": "Hades",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
            },
            {
                "name": "Celeste",
                "configured": True,
                "has_backup": False,
                "needs_first_backup": True,
                "error": None,
            },
        ]
        self.recency = {"Hades": "local_current"}
        self.backups: list[str] = []
        self.restores: list[str] = []
        self.versions = {"ludusavi": "ludusavi 0.31.0", "rclone": "rclone v1.66.0"}
        self.conflict_metadata = {
            "localModifiedAt": "2026-05-19T09:00:00",
            "backupModifiedAt": "2026-05-19T10:00:00",
            "backupPath": "/home/deck/ludusavi-backups/Hades",
        }
        self.diagnostics = {
            "version": "0.31.0",
            "type": "flatpak",
            "path": "com.github.mtkennerly.ludusavi",
            "configPath": "/home/deck/.var/app/com.github.mtkennerly.ludusavi/config/ludusavi/config.yaml",
            "backupPath": "/home/deck/ludusavi-backups",
        }
        self.refresh_error: Exception | None = None
        self.config_mtime_ns: int | None = 100
        self.refresh_count = 0

    def refresh_statuses(self) -> list[dict[str, object]]:
        self.refresh_count += 1
        if self.refresh_error:
            raise self.refresh_error
        return [dict(game) for game in self.games]

    def compare_recency(self, game_name: str) -> str:
        return self.recency.get(game_name, "ambiguous")

    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return {
                "games": {
                    game_name: {
                        "change": "Different",
                        "files": {"save.dat": {}},
                        "registry": {},
                    }
                }
            }
        self.backups.append(game_name)
        return {"ok": True, "game": game_name}

    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return {"games": {game_name: {"change": "Different", "files": {"save.dat": {}}}}}
        self.restores.append(game_name)
        return {"ok": True, "game": game_name}

    def get_conflict_metadata(self, game_name: str) -> dict[str, object]:
        return dict(self.conflict_metadata)

    def get_versions(self) -> dict[str, str]:
        return dict(self.versions)

    def get_diagnostics(self) -> dict[str, object]:
        return dict(self.diagnostics)

    def get_log_contents(self) -> str:
        return ""

    def get_config_mtime_ns(self) -> int | None:
        return self.config_mtime_ns


class RaisingConfigMarkerAdapter(FakeAdapter):
    def get_config_mtime_ns(self) -> int | None:
        raise RuntimeError("config marker unavailable")


def service_with_state(tmp_path: Path, adapter: FakeAdapter | None = None) -> SDHLudusaviService:
    return SDHLudusaviService(
        adapter=adapter or FakeAdapter(),
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )


DEFAULT_NOTIFICATIONS = {
    "enabled": True,
    "auto_sync_progress": True,
    "auto_sync_results": True,
    "manual_operations": True,
    "refresh_status": True,
    "failures_errors": True,
}


def expected_settings(
    *,
    auto_sync_enabled: bool = False,
    selected_game: str = "",
    notifications: dict[str, bool] | None = None,
) -> dict[str, object]:
    return {
        "auto_sync_enabled": auto_sync_enabled,
        "selected_game": selected_game,
        "notifications": notifications or dict(DEFAULT_NOTIFICATIONS),
    }


def test_decky_log_uses_cached_module_level_logger() -> None:
    tree = ast.parse(Path("py_modules/sdh_ludusavi/service.py").read_text(encoding="utf-8"))
    decky_log = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_decky_log"
    )
    imports = [
        node for node in ast.walk(decky_log) if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    names = {node.id for node in ast.walk(decky_log) if isinstance(node, ast.Name)}

    assert imports == []
    assert "_DECKY_LOGGER" in names


def test_settings_do_not_initialize_ludusavi_adapter(tmp_path: Path) -> None:
    def fail_factory() -> FakeAdapter:
        raise RuntimeError("Ludusavi should not be initialized")

    service = SDHLudusaviService(
        adapter_factory=fail_factory,
        state_path=tmp_path / "state.json",
    )

    assert service.get_settings() == expected_settings()
    assert service.set_auto_sync_enabled(True) == expected_settings(auto_sync_enabled=True)


def test_notification_settings_default_to_enabled_and_persist(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    assert service.get_settings() == expected_settings()

    updated = service.set_notification_settings(
        {
            "enabled": False,
            "auto_sync_progress": False,
            "manual_operations": False,
        }
    )

    expected_notifications = {
        **DEFAULT_NOTIFICATIONS,
        "enabled": False,
        "auto_sync_progress": False,
        "manual_operations": False,
    }
    assert updated == expected_settings(notifications=expected_notifications)

    reloaded = service_with_state(tmp_path)
    assert reloaded.get_settings() == expected_settings(notifications=expected_notifications)


def test_notification_settings_load_malformed_settings_safely(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "auto_sync_enabled": True,
                "selected_game": "Hades",
                "notifications": {
                    "enabled": False,
                    "auto_sync_progress": "yes",
                    "unknown": False,
                },
            }
        ),
        encoding="utf-8",
    )

    service = service_with_state(tmp_path)

    expected_notifications = {
        **DEFAULT_NOTIFICATIONS,
        "enabled": False,
    }
    assert service.get_settings() == expected_settings(
        auto_sync_enabled=True,
        selected_game="Hades",
        notifications=expected_notifications,
    )


def test_refresh_reports_ludusavi_adapter_initialization_failure(tmp_path: Path) -> None:
    def fail_factory() -> FakeAdapter:
        raise RuntimeError("Ludusavi Flatpak is not available to Decky")

    service = SDHLudusaviService(
        adapter_factory=fail_factory,
        state_path=tmp_path / "state.json",
    )

    result = service.refresh_games()

    assert result == {
        "games": [],
        "aliases": {},
        "history": {},
        "dependency_error": "Ludusavi Flatpak is not available to Decky",
    }
    assert service.get_recent_logs()[-1]["level"] == "error"
    assert "Ludusavi Flatpak" in service.get_recent_logs()[-1]["message"]


def test_ludusavi_adapter_factory_is_reused_after_success(tmp_path: Path) -> None:
    calls = 0

    def factory() -> FakeAdapter:
        nonlocal calls
        calls += 1
        return FakeAdapter()

    service = SDHLudusaviService(
        adapter_factory=factory,
        state_path=tmp_path / "state.json",
    )

    service.refresh_games()
    service.get_versions()

    assert calls == 1


def test_game_cache_current_uses_installed_app_and_config_markers(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    assert service.is_game_cache_current("222,111") is False

    service.refresh_games(installed_app_ids="222,111")
    assert service.is_game_cache_current("111,222") is True

    adapter.config_mtime_ns = 200
    assert service.is_game_cache_current("111,222") is False


def test_game_cache_current_returns_false_on_config_stat_failure(tmp_path: Path) -> None:
    adapter = RaisingConfigMarkerAdapter()
    service = service_with_state(tmp_path, adapter)

    # Populate cache first
    service._games = {"Hades": {"name": "Hades", "configured": True}}
    service._installed_app_ids = "111,222"
    service._ludusavi_config_mtime_ns = 100

    # Since the adapter raises an exception on config mtime check, it should return False
    assert service.is_game_cache_current("111,222") is False


def test_ludusavi_adapter_initialization_is_thread_safe(tmp_path: Path) -> None:
    calls = 0
    factory_entered = threading.Event()
    release_factory = threading.Event()

    def factory() -> FakeAdapter:
        nonlocal calls
        calls += 1
        factory_entered.set()
        release_factory.wait(timeout=1)
        return FakeAdapter()

    service = SDHLudusaviService(
        adapter_factory=factory,
        state_path=tmp_path / "state.json",
    )
    adapters: list[FakeAdapter] = []
    errors: list[BaseException] = []

    def initialize_adapter() -> None:
        try:
            adapters.append(service._ludusavi())
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=initialize_adapter)
    second = threading.Thread(target=initialize_adapter)
    first.start()
    assert factory_entered.wait(timeout=1)
    second.start()
    release_factory.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert calls == 1
    assert len({id(adapter) for adapter in adapters}) == 1


def test_pause_and_resume_game_process_signal_process_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_with_state(tmp_path)
    signals: list[tuple[int, signal.Signals]] = []

    monkeypatch.setattr("sdh_ludusavi.service._process_tree", lambda pid: [100, 101, 201, 102])
    monkeypatch.setattr("sdh_ludusavi.service.os.kill", lambda pid, sig: signals.append((pid, sig)))

    assert service.pause_game_process(100) == {"status": "paused", "pid": 100}
    assert service.resume_game_process(100) == {"status": "resumed", "pid": 100}

    assert signals == [
        (100, signal.SIGSTOP),
        (101, signal.SIGSTOP),
        (201, signal.SIGSTOP),
        (102, signal.SIGSTOP),
        (100, signal.SIGCONT),
        (101, signal.SIGCONT),
        (201, signal.SIGCONT),
        (102, signal.SIGCONT),
    ]


def test_signal_process_tree_snapshots_process_table_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_with_state(tmp_path)
    listdir_calls: list[str] = []
    signals: list[tuple[int, signal.Signals]] = []

    # Simulate /proc with PIDs: 100 (ppid=1), 101 (ppid=100), 102 (ppid=100), 201 (ppid=101)
    proc_status: dict[str, str] = {
        "100": "Name:\tbash\nPid:\t100\nPPid:\t1\n",
        "101": "Name:\tgame\nPid:\t101\nPPid:\t100\n",
        "102": "Name:\twine\nPid:\t102\nPPid:\t100\n",
        "201": "Name:\tchild\nPid:\t201\nPPid:\t101\n",
    }

    def fake_listdir(path: str) -> list[str]:
        listdir_calls.append(path)
        return ["1", "100", "101", "102", "201", "self", "sys"]

    import sdh_ludusavi.service as svc_mod

    monkeypatch.setattr(svc_mod, "_read_ppid", lambda pid_str: _parse_ppid(proc_status, pid_str))
    monkeypatch.setattr("sdh_ludusavi.service.os.listdir", fake_listdir)
    monkeypatch.setattr("sdh_ludusavi.service.os.kill", lambda pid, sig: signals.append((pid, sig)))

    assert service.pause_game_process(100) == {"status": "paused", "pid": 100}

    assert len(listdir_calls) == 1
    assert signals == [
        (100, signal.SIGSTOP),
        (101, signal.SIGSTOP),
        (201, signal.SIGSTOP),
        (102, signal.SIGSTOP),
    ]


def test_signal_process_tree_falls_back_to_root_when_snapshot_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_with_state(tmp_path)
    signals: list[tuple[int, signal.Signals]] = []

    def fail_listdir(path: str) -> list[str]:
        raise OSError("/proc unavailable")

    monkeypatch.setattr("sdh_ludusavi.service.os.listdir", fail_listdir)
    monkeypatch.setattr("sdh_ludusavi.service.os.kill", lambda pid, sig: signals.append((pid, sig)))

    assert service.pause_game_process(100) == {"status": "paused", "pid": 100}

    assert signals == [(100, signal.SIGSTOP)]


def _parse_ppid(proc_status: dict[str, str], pid_str: str) -> int | None:
    """Test helper: extract PPid from fake /proc status content."""
    content = proc_status.get(pid_str)
    if content is None:
        return None
    for line in content.splitlines():
        if line.startswith("PPid:"):
            return int(line.split(":")[1])
    return None


def test_process_tree_reads_proc_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify _process_tree builds a correct tree from mocked /proc entries."""
    import sdh_ludusavi.service as svc_mod

    proc_status: dict[str, str] = {
        "1": "Name:\tinit\nPid:\t1\nPPid:\t0\n",
        "100": "Name:\tbash\nPid:\t100\nPPid:\t1\n",
        "101": "Name:\tgame\nPid:\t101\nPPid:\t100\n",
        "102": "Name:\twine\nPid:\t102\nPPid:\t100\n",
        "201": "Name:\tchild\nPid:\t201\nPPid:\t101\n",
    }

    monkeypatch.setattr(
        "sdh_ludusavi.service.os.listdir",
        lambda path: ["1", "100", "101", "102", "201", "self", "sys"],
    )
    monkeypatch.setattr(svc_mod, "_read_ppid", lambda pid_str: _parse_ppid(proc_status, pid_str))

    result = svc_mod._process_tree(100)

    assert result == [100, 101, 201, 102]


def test_process_tree_skips_vanished_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Processes that vanish between listdir and read are silently skipped."""
    import sdh_ludusavi.service as svc_mod

    proc_status: dict[str, str] = {
        "100": "Name:\tbash\nPid:\t100\nPPid:\t1\n",
        "101": "Name:\tgame\nPid:\t101\nPPid:\t100\n",
        # 102 intentionally missing — simulates vanished process
    }

    monkeypatch.setattr(
        "sdh_ludusavi.service.os.listdir",
        lambda path: ["100", "101", "102"],
    )
    monkeypatch.setattr(svc_mod, "_read_ppid", lambda pid_str: _parse_ppid(proc_status, pid_str))

    result = svc_mod._process_tree(100)

    assert result == [100, 101]


def test_process_tree_falls_back_on_listdir_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If os.listdir('/proc') raises OSError, fall back to [pid]."""
    import sdh_ludusavi.service as svc_mod

    monkeypatch.setattr(
        "sdh_ludusavi.service.os.listdir",
        lambda path: (_ for _ in ()).throw(OSError("/proc unavailable")),
    )

    result = svc_mod._process_tree(42)

    assert result == [42]


def test_read_ppid_parses_status_file(tmp_path: Path) -> None:
    """_read_ppid correctly extracts PPid from a /proc status file."""
    from sdh_ludusavi.service import _read_ppid

    status_file = tmp_path / "status"
    status_file.write_text(
        "Name:\tbash\n"
        "Umask:\t0022\n"
        "State:\tS (sleeping)\n"
        "Tgid:\t12345\n"
        "Pid:\t12345\n"
        "PPid:\t100\n"
        "TracerPid:\t0\n",
        encoding="utf-8",
    )

    # _read_ppid reads /proc/{pid_str}/status, so we construct a fake /proc tree
    proc_dir = tmp_path / "proc" / "12345"
    proc_dir.mkdir(parents=True)
    (proc_dir / "status").write_text(
        status_file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # We test _read_ppid by monkeypatching the path prefix — but since _read_ppid
    # uses a hardcoded "/proc/" prefix, we test it indirectly through _process_tree
    # or directly if it accepts a path. For now, test the parsing logic:
    assert _read_ppid("12345", proc_root=str(tmp_path / "proc")) == 100


def test_read_ppid_returns_none_on_missing_file() -> None:
    """_read_ppid returns None for a nonexistent PID."""
    from sdh_ludusavi.service import _read_ppid

    assert _read_ppid("999999999") is None


def test_process_tree_has_no_subprocess_usage() -> None:
    """Static regression: _process_tree and _read_ppid must not use subprocess."""
    source = Path("py_modules/sdh_ludusavi/service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    target_funcs = {"_process_tree", "_read_ppid"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            assert "subprocess" not in names, f"{node.name} must not reference subprocess"
            assert "Popen" not in attrs, f"{node.name} must not reference Popen"
            assert "communicate" not in attrs, f"{node.name} must not reference communicate"


def test_resume_all_paused_processes_resumes_remaining_pids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_with_state(tmp_path)
    signals: list[tuple[int, signal.Signals]] = []

    monkeypatch.setattr("sdh_ludusavi.service._process_tree", lambda pid: [pid])
    monkeypatch.setattr("sdh_ludusavi.service.os.kill", lambda pid, sig: signals.append((pid, sig)))

    service.pause_game_process(100)
    service.pause_game_process(200)
    service.resume_all_paused_processes()

    assert signals == [
        (100, signal.SIGSTOP),
        (200, signal.SIGSTOP),
        (100, signal.SIGCONT),
        (200, signal.SIGCONT),
    ]


def test_settings_persist_auto_sync_toggle(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    assert service.get_settings() == expected_settings()
    assert service.set_auto_sync_enabled(True) == expected_settings(auto_sync_enabled=True)

    reloaded = service_with_state(tmp_path)

    assert reloaded.get_settings() == expected_settings(auto_sync_enabled=True)
    assert json.loads((tmp_path / "settings.json").read_text()) == {
        "auto_sync_enabled": True,
        "selected_game": "",
        "notifications": DEFAULT_NOTIFICATIONS,
    }


def test_persists_settings_and_cache_separately(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    service.set_auto_sync_enabled(True)
    service.set_selected_game("Hades")
    service.set_ludusavi_launcher_shortcut_id(12345)
    service.refresh_games(force=True, installed_app_ids="111,222")

    settings = json.loads((tmp_path / "settings.json").read_text())
    cache = json.loads((tmp_path / "cache.json").read_text())

    assert settings == {
        "auto_sync_enabled": True,
        "selected_game": "Hades",
        "notifications": DEFAULT_NOTIFICATIONS,
    }
    assert "games" not in settings
    assert "ludusaviLauncherShortcutAppId" not in settings
    assert cache == {
        "ludusaviLauncherShortcutAppId": 12345,
        "games": [
            {
                "name": "Hades",
                "steam_id": None,
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
                "status": "has_backup",
            },
            {
                "name": "Celeste",
                "steam_id": None,
                "configured": True,
                "has_backup": False,
                "needs_first_backup": True,
                "error": None,
                "status": "needs_first_backup",
            },
        ],
        "aliases": {},
        "ids": {},
        "installed_app_ids": "111,222",
        "ludusavi_config_mtime_ns": 100,
        "game_history": {},
    }
    assert "auto_sync_enabled" not in cache
    assert "selected_game" not in cache
    assert "notifications" not in cache


def test_does_not_load_old_combined_state_file(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(
        json.dumps({"auto_sync_enabled": True, "selected_game": "Legacy"}),
        encoding="utf-8",
    )

    service = service_with_state(tmp_path)

    assert service.get_settings() == expected_settings()
    assert not (tmp_path / "settings.json").exists()
    assert not (tmp_path / "cache.json").exists()


def test_cache_save_failure_keeps_existing_cache_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text('{"ludusaviLauncherShortcutAppId": 111}', encoding="utf-8")
    service = service_with_state(tmp_path)
    original_write_text = Path.write_text

    def fail_after_partial_temp_write(
        path: Path, data: str, *args: object, **kwargs: object
    ) -> int:
        if path.parent == tmp_path and path.name == ".cache.json.tmp":
            original_write_text(path, '{"ludusaviLauncherShortcutAppId":', *args, **kwargs)
            raise OSError("disk full")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_after_partial_temp_write)

    with pytest.raises(OSError, match="disk full"):
        service.set_ludusavi_launcher_shortcut_id(222)

    assert json.loads(cache_path.read_text(encoding="utf-8")) == {
        "ludusaviLauncherShortcutAppId": 111
    }


def test_failed_state_save_keeps_existing_state_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "settings.json"
    state_path.write_text('{"auto_sync_enabled": false}', encoding="utf-8")
    service = service_with_state(tmp_path)
    original_write_text = Path.write_text

    def fail_after_partial_temp_write(
        path: Path, data: str, *args: object, **kwargs: object
    ) -> int:
        if path.parent == tmp_path:
            original_write_text(path, '{"auto_sync_enabled":', *args, **kwargs)
            raise OSError("disk full")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_after_partial_temp_write)

    with pytest.raises(OSError, match="disk full"):
        service.set_auto_sync_enabled(True)

    assert json.loads(state_path.read_text(encoding="utf-8")) == {"auto_sync_enabled": False}


@pytest.mark.parametrize("contents", ["{", "[]"])
def test_invalid_cache_files_load_defaults_and_log_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    contents: str,
) -> None:
    state_path = tmp_path / "cache.json"
    state_path.write_text(contents, encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="sdh_ludusavi.service"):
        service = service_with_state(tmp_path)

    assert service.get_settings() == expected_settings()
    assert "Ignoring SDH-ludusavi state" in caplog.text


def test_unreadable_cache_file_loads_defaults_and_logs_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state_path = tmp_path / "cache.json"
    state_path.write_text('{"auto_sync_enabled": true}', encoding="utf-8")
    original_read_text = Path.read_text

    def unreadable(path: Path, *args: object, **kwargs: object) -> str:
        if path == state_path:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)

    with caplog.at_level(logging.WARNING, logger="sdh_ludusavi.service"):
        service = service_with_state(tmp_path)

    assert service.get_settings() == expected_settings()
    assert "permission denied" in caplog.text


def test_refresh_games_caches_statuses(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    result = service.refresh_games()

    assert [game["name"] for game in result["games"]] == ["Hades", "Celeste"]
    assert result["games"][0]["status"] == "has_backup"
    assert result["games"][1]["status"] == "needs_first_backup"
    assert service.get_operation_status()["is_running"] is False
    assert service.get_operation_status()["name"] is None
    assert service.get_operation_status()["game_name"] is None


def test_start_matches_steam_and_non_steam_names_conservatively(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    adapter.recency["Hades"] = "backup_newer"
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    steam_result = service.handle_game_start("hades", app_id="1145360")
    non_steam_result = service.handle_game_start("Celeste")

    assert steam_result["status"] == "restored"
    assert non_steam_result["status"] == "skipped"
    assert non_steam_result["reason"] == "no_backup"
    assert adapter.restores == ["Hades"]


def test_check_game_start_reports_restore_needed_without_restoring(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    adapter.recency["Hades"] = "backup_newer"
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    result = service.check_game_start("hades", app_id="1145360")

    assert result == {"status": "needed", "operation": "restore", "game": "Hades"}
    assert adapter.restores == []


def test_restore_game_on_start_performs_restore_and_records_history(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    result = service.restore_game_on_start("Hades", app_id="1145360")

    assert result["status"] == "restored"
    assert adapter.restores == ["Hades"]
    refresh = service.refresh_games()
    assert refresh["history"]["Hades"]["last_restore"]["trigger"] == "auto_start"


def test_check_game_start_reports_conflict_for_ambiguous_recency(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    adapter.recency["Hades"] = "ambiguous"
    result = service.check_game_start("Hades")

    assert result == {
        "status": "conflict",
        "operation": "restore",
        "game": "Hades",
        "reason": "ambiguous_recency",
        "localModifiedAt": "2026-05-19T09:00:00",
        "backupModifiedAt": "2026-05-19T10:00:00",
        "backupPath": "/home/deck/ludusavi-backups/Hades",
        "localLabel": "Keep Local Save",
        "backupLabel": "Restore Backup Save",
    }
    assert adapter.restores == []


def test_start_skips_disabled_unmatched_and_local_current(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    disabled = service.handle_game_start("Hades")
    service.set_auto_sync_enabled(True)
    unmatched = service.handle_game_start("Unknown Game")

    # local_current requires preview logic mock if using real adapter,
    # but FakeAdapter is static here.
    local_current = service.handle_game_start("Hades")

    assert disabled["reason"] == "auto_sync_disabled"
    assert unmatched["reason"] == "unmatched_game"
    assert local_current["reason"] == "local_current"
    assert adapter.restores == []

    # Verify log levels for skips are now 'info'
    logs = service.get_recent_logs()
    skip_logs = [log for log in logs if "Skipping" in log["message"] or "Skipped" in log["message"]]
    assert all(log["level"] == "info" for log in skip_logs)


@pytest.mark.parametrize(
    ("resolution", "expected_status", "expected_backups", "expected_restores"),
    [
        ("keep_local", "backed_up", ["Hades"], []),
        ("restore_backup", "restored", [], ["Hades"]),
    ],
)
def test_resolve_game_start_conflict_applies_selected_save(
    tmp_path: Path,
    resolution: str,
    expected_status: str,
    expected_backups: list[str],
    expected_restores: list[str],
) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    result = service.resolve_game_start_conflict("Hades", "1145360", resolution)

    assert result["status"] == expected_status
    assert result["game"] == "Hades"
    assert adapter.backups == expected_backups
    assert adapter.restores == expected_restores


def test_resolve_game_start_conflict_rejects_unknown_resolution(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    result = service.resolve_game_start_conflict("Hades", "1145360", "download_cloud")

    assert result["status"] == "skipped"
    assert result["reason"] == "invalid_resolution"
    assert adapter.backups == []
    assert adapter.restores == []


def test_check_game_exit_reports_backup_needed_without_backing_up(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    result = service.check_game_exit("Hades")

    assert result == {"status": "needed", "operation": "backup", "game": "Hades"}
    assert adapter.backups == []


def test_backup_game_on_exit_performs_backup_and_refreshes_history(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    result = service.backup_game_on_exit("Hades")

    assert result["status"] == "backed_up"
    assert adapter.backups == ["Hades"]
    refresh = service.refresh_games()
    assert refresh["history"]["Hades"]["last_backup"]["trigger"] == "auto_exit"


def test_exit_backs_up_only_when_auto_sync_enabled_and_matched(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    disabled = service.handle_game_exit("Hades")
    service.set_auto_sync_enabled(True)
    unmatched = service.handle_game_exit("Unknown Game")

    # Mock backup preview to return "Same" for Hades first
    original_backup = adapter.backup

    def backup_with_preview(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return {
                "games": {game_name: {"change": "Same", "files": {"save.dat": {}}, "registry": {}}}
            }
        return original_backup(game_name)

    adapter.backup = backup_with_preview
    local_current = service.handle_game_exit("Hades")

    # Now mock backup preview to return "Different"
    def backup_with_changes(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return {
                "games": {
                    game_name: {"change": "Different", "files": {"save.dat": {}}, "registry": {}}
                }
            }
        return original_backup(game_name)

    adapter.backup = backup_with_changes
    backed_up = service.handle_game_exit("Hades")

    assert disabled["reason"] == "auto_sync_disabled"
    assert unmatched["reason"] == "unmatched_game"
    assert local_current["reason"] == "local_current"
    assert backed_up["status"] == "backed_up"
    assert adapter.backups == ["Hades"]


def test_force_operations_work_when_auto_sync_disabled(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    backup = service.force_backup("Hades")
    restore = service.force_restore("Hades")

    assert service.get_settings() == expected_settings()
    assert backup["status"] == "backed_up"
    assert restore["status"] == "restored"
    assert adapter.backups == ["Hades"]
    assert adapter.restores == ["Hades"]


def test_global_operation_lock_blocks_new_operations(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()
    service._operation.is_running = True
    service._operation.name = "refresh"

    with pytest.raises(OperationLockedError):
        service.force_backup("Hades")

    assert service.get_operation_status()["name"] == "refresh"


def test_concurrent_operations_are_rejected_by_thread_safe_lock(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()
    entered = threading.Event()
    release = threading.Event()
    first_result: list[dict[str, object]] = []
    first_errors: list[BaseException] = []

    def slow_callback() -> dict[str, object]:
        entered.set()
        release.wait(timeout=1)
        return {"ok": True}

    def run_first_operation() -> None:
        try:
            first_result.append(service._run_locked("backup", "Hades", slow_callback))
        except BaseException as exc:  # pragma: no cover - failure details are asserted below.
            first_errors.append(exc)

    first_thread = threading.Thread(target=run_first_operation)
    first_thread.start()
    assert entered.wait(timeout=1)

    with pytest.raises(OperationLockedError):
        service._run_locked("restore", "Hades", lambda: {"ok": True})

    release.set()
    first_thread.join(timeout=1)

    assert not first_thread.is_alive()
    assert first_errors == []
    assert first_result == [{"ok": True}]


def test_version_lookup_and_missing_dependency_states_are_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sdh_ludusavi.service.resolve_version", lambda: "0.1.dev104+gabcdef")
    monkeypatch.setenv("DECKY_VERSION", "3.1.4")
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    versions = service.get_versions()
    assert versions["sdh_ludusavi"] == "0.1.dev104+gabcdef"
    assert versions["decky"] == "3.1.4"
    assert "ludusavi" in versions
    assert "pyludusavi" in versions

    adapter.refresh_error = RuntimeError("Ludusavi Flatpak is not installed")
    result = service.refresh_games()

    assert result["dependency_error"] == "Ludusavi Flatpak is not installed"
    assert service.get_recent_logs()[-1]["level"] == "error"
    assert "Ludusavi Flatpak" in service.get_recent_logs()[-1]["message"]


def test_ludusavi_diagnostics_are_logged_after_adapter_initialization(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    service.refresh_games()

    # Wait for the background diagnostics logging to finish
    for _ in range(50):
        messages = [entry["message"] for entry in service.get_recent_logs()]
        if any("Ludusavi version: 0.31.0" in message for message in messages):
            break
        time.sleep(0.01)

    messages = [entry["message"] for entry in service.get_recent_logs()]
    assert any("Ludusavi version: 0.31.0" in message for message in messages)
    assert any(
        "Ludusavi type/path: flatpak com.github.mtkennerly.ludusavi" in message
        for message in messages
    )
    assert any("Ludusavi config path:" in message for message in messages)
    assert any(
        "Ludusavi backup path: /home/deck/ludusavi-backups" in message for message in messages
    )


def test_ludusavi_diagnostics_logging_is_asynchronous(tmp_path: Path) -> None:
    diagnostics_called = threading.Event()
    diagnostics_can_continue = threading.Event()

    class BlockedAdapter(FakeAdapter):
        def get_diagnostics(self) -> dict[str, object]:
            diagnostics_called.set()
            diagnostics_can_continue.wait(timeout=5.0)
            return super().get_diagnostics()

    adapter = BlockedAdapter()
    service = service_with_state(tmp_path, adapter)

    # Triggering lazy-load diagnostics should run in background without blocking
    service.refresh_games()

    # Verify that get_diagnostics was triggered in the background
    assert diagnostics_called.wait(timeout=2.0)

    # At this point, get_diagnostics is still blocked in the thread.
    # Verify that the diagnostic messages are NOT logged yet.
    messages = [entry["message"] for entry in service.get_recent_logs()]
    assert not any("Ludusavi version: 0.31.0" in message for message in messages)

    # Let the background thread complete
    diagnostics_can_continue.set()

    # Wait for the logs to be populated
    for _ in range(50):
        messages = [entry["message"] for entry in service.get_recent_logs()]
        if any("Ludusavi version: 0.31.0" in message for message in messages):
            break
        time.sleep(0.01)

    messages = [entry["message"] for entry in service.get_recent_logs()]
    assert any("Ludusavi version: 0.31.0" in message for message in messages)


def test_get_ludusavi_logs(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    # Case: Log file exists
    monkeypatch.setattr(adapter, "get_log_contents", lambda: "test log content")
    assert service.get_ludusavi_logs() == "test log content"

    # Case: Log file missing or empty
    monkeypatch.setattr(adapter, "get_log_contents", lambda: "")
    assert service.get_ludusavi_logs() == ""


def test_refresh_games_cache_invalidation_via_app_ids(tmp_path: Path) -> None:
    # Setup cache with a "ghost" game and an initial app IDs string
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "name": "Ghost Game",
                        "configured": True,
                        "has_backup": False,
                        "needs_first_backup": True,
                    }
                ],
                "installed_app_ids": "1,2,3",
                "ludusavi_config_mtime_ns": 100,
            }
        )
    )

    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    # Ensure cache is loaded
    assert "Ghost Game" in service._games

    # Call with the same installed_app_ids should use the cache
    adapter.refresh_error = RuntimeError("should not be called")
    result = service.refresh_games(force=False, installed_app_ids="1,2,3")
    assert [g["name"] for g in result["games"]] == ["Ghost Game"]

    # Call with a DIFFERENT installed_app_ids should invalidate cache and trigger scan
    adapter.refresh_error = None  # allow it to succeed
    result = service.refresh_games(force=False, installed_app_ids="1,2,3,4")
    assert [g["name"] for g in result["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids == "1,2,3,4"

    # Call with NO installed_app_ids should also trigger scan if cache was empty, but since it's populated it will just use cache
    adapter.refresh_error = RuntimeError("should not be called")
    result = service.refresh_games(force=False)
    assert [g["name"] for g in result["games"]] == ["Hades", "Celeste"]


def test_refresh_games_normalizes_installed_app_ids_before_persisting(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    result = service.refresh_games(force=False, installed_app_ids="3,1,3,2")

    assert [g["name"] for g in result["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids == "1,2,3"
    saved_state = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert saved_state["installed_app_ids"] == "1,2,3"


def test_refresh_games_preserves_empty_installed_app_ids_marker(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "name": "Ghost Game",
                        "configured": True,
                        "has_backup": False,
                        "needs_first_backup": True,
                    }
                ],
                "installed_app_ids": "1,2,3",
                "ludusavi_config_mtime_ns": 100,
            }
        ),
        encoding="utf-8",
    )
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    result = service.refresh_games(force=False, installed_app_ids="")

    assert [g["name"] for g in result["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids == ""
    saved_state = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved_state["installed_app_ids"] == ""


def test_refresh_games_rejects_malformed_installed_app_ids(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    result = service.refresh_games(force=False, installed_app_ids="1,not-a-number,2")

    assert [g["name"] for g in result["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids is None
    saved_state = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert saved_state["installed_app_ids"] is None


def test_refresh_games_rejects_oversized_installed_app_ids(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    oversized = ",".join(str(index) for index in range(10000))

    result = service.refresh_games(force=False, installed_app_ids=oversized)

    assert [g["name"] for g in result["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids is None
    saved_state = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert saved_state["installed_app_ids"] is None


def test_refresh_games_cache_invalidation_via_ludusavi_config_mtime(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "name": "Ghost Game",
                        "configured": True,
                        "has_backup": False,
                        "needs_first_backup": True,
                    }
                ],
                "installed_app_ids": "1,2,3",
                "ludusavi_config_mtime_ns": 100,
            }
        ),
        encoding="utf-8",
    )

    adapter = FakeAdapter()
    adapter.config_mtime_ns = 101
    service = service_with_state(tmp_path, adapter)

    result = service.refresh_games(force=False, installed_app_ids="1,2,3")

    assert [g["name"] for g in result["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids == "1,2,3"
    assert service._ludusavi_config_mtime_ns == 101
    saved_state = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved_state["ludusavi_config_mtime_ns"] == 101


def test_failed_refresh_does_not_persist_pending_cache_markers(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "name": "Ghost Game",
                        "configured": True,
                        "has_backup": False,
                        "needs_first_backup": True,
                    }
                ],
                "installed_app_ids": "1,2,3",
                "ludusavi_config_mtime_ns": 100,
            }
        ),
        encoding="utf-8",
    )

    adapter = FakeAdapter()
    adapter.config_mtime_ns = 101
    adapter.refresh_error = RuntimeError("refresh failed")
    service = service_with_state(tmp_path, adapter)

    result = service.refresh_games(force=False, installed_app_ids="1,2,3,4")

    assert result["dependency_error"] == "refresh failed"
    assert service._installed_app_ids == "1,2,3"
    assert service._ludusavi_config_mtime_ns == 100


def test_concurrent_refresh_does_not_overwrite_first_refresh_cache_markers(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()
    adapter.config_mtime_ns = 100
    refresh_entered = threading.Event()
    release_refresh = threading.Event()
    original_refresh = adapter.refresh_statuses

    def slow_refresh() -> list[dict[str, object]]:
        refresh_entered.set()
        release_refresh.wait(timeout=1)
        return original_refresh()

    adapter.refresh_statuses = slow_refresh
    service = service_with_state(tmp_path, adapter)
    first_result: list[dict[str, object]] = []

    def first_refresh() -> None:
        first_result.append(service.refresh_games(force=False, installed_app_ids="3,1"))

    first = threading.Thread(target=first_refresh)
    first.start()
    assert refresh_entered.wait(timeout=1)

    rejected = service.refresh_games(force=False, installed_app_ids="9")
    release_refresh.set()
    first.join(timeout=1)

    assert not first.is_alive()
    assert rejected["dependency_error"] == "refresh is already running"
    assert [game["name"] for game in first_result[0]["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids == "1,3"
    assert service._ludusavi_config_mtime_ns == 100


def test_config_marker_read_failure_forces_refresh_instead_of_cache_hit(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "name": "Ghost Game",
                        "configured": True,
                        "has_backup": False,
                        "needs_first_backup": True,
                    }
                ],
                "installed_app_ids": "1,2,3",
                "ludusavi_config_mtime_ns": 100,
            }
        ),
        encoding="utf-8",
    )
    adapter = RaisingConfigMarkerAdapter()
    service = service_with_state(tmp_path, adapter)

    result = service.refresh_games(force=False, installed_app_ids="1,2,3")

    assert [game["name"] for game in result["games"]] == ["Hades", "Celeste"]
    assert service._installed_app_ids == "1,2,3"
    assert service._ludusavi_config_mtime_ns is None


def test_match_game_serializes_lazy_refresh_for_concurrent_callers(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    release_refresh = threading.Event()
    entered_refresh = threading.Event()
    original_refresh = adapter.refresh_statuses

    def slow_refresh() -> list[dict[str, object]]:
        entered_refresh.set()
        release_refresh.wait(timeout=1)
        time.sleep(0.01)
        return original_refresh()

    adapter.refresh_statuses = slow_refresh
    service = service_with_state(tmp_path, adapter)
    service._games = {}
    matches: list[str | None] = []
    errors: list[BaseException] = []

    def match() -> None:
        try:
            game = service._match_game("Hades")
            matches.append(game.name if game else None)
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    first = threading.Thread(target=match)
    second = threading.Thread(target=match)
    first.start()
    assert entered_refresh.wait(timeout=1)
    second.start()
    release_refresh.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert matches == ["Hades", "Hades"]
    assert adapter.refresh_count == 1


def test_concurrent_state_saves_do_not_share_temp_file(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    errors: list[BaseException] = []

    def save_selected_game(name: str) -> None:
        try:
            service.set_selected_game(name)
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    threads = [
        threading.Thread(target=save_selected_game, args=(f"Game {index}",)) for index in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    state = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert state["selected_game"].startswith("Game ")


def test_cache_keys_do_not_override_settings(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "auto_sync_enabled": True,
                "selected_game": "Hades",
                "notifications": {
                    "enabled": True,
                    "auto_sync_progress": True,
                    "auto_sync_results": True,
                    "manual_operations": True,
                    "refresh_status": True,
                    "failures_errors": True,
                },
            }
        ),
        encoding="utf-8",
    )

    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        json.dumps(
            {
                "auto_sync_enabled": False,
                "selected_game": "Celeste",
                "notifications": {
                    "enabled": False,
                    "auto_sync_progress": False,
                    "auto_sync_results": False,
                    "manual_operations": False,
                    "refresh_status": False,
                    "failures_errors": False,
                },
                "ludusaviLauncherShortcutAppId": 12345,
            }
        ),
        encoding="utf-8",
    )

    service = SDHLudusaviService(
        adapter=FakeAdapter(),
        settings_store=JsonSettingsStore(settings_file),
        cache_path=cache_file,
    )

    assert service.get_settings()["auto_sync_enabled"] is True
    assert service.get_settings()["selected_game"] == "Hades"
    assert service.get_settings()["notifications"]["enabled"] is True
    assert service._ludusavi_launcher_shortcut_id == 12345
