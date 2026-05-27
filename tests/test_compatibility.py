from __future__ import annotations

import inspect
from pathlib import Path

from sdh_ludusavi.service import SDHLudusaviService, JsonSettingsStore


class DummyAdapter:
    def refresh_statuses(self) -> list[dict[str, object]]:
        return []

    def compare_recency(self, game_name: str) -> str:
        return "local_current"

    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
        return {}

    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]:
        return {}

    def get_conflict_metadata(self, game_name: str) -> dict[str, object]:
        return {}

    def get_versions(self) -> dict[str, str]:
        return {}

    def get_log_contents(self) -> str:
        return ""

    def get_config_mtime_ns(self) -> int | None:
        return 123

    def get_diagnostics(self) -> dict[str, object]:
        return {}


def test_sdh_ludusavi_service_interface_compatibility(tmp_path: Path) -> None:
    """
    Ensure all 29 expected public methods exist on SDHLudusaviService with the
    correct names, parameters, and signature contracts required by main.py.
    """
    service = SDHLudusaviService(
        adapter=DummyAdapter(),
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )

    # 1. __init__ signature check
    init_sig = inspect.signature(SDHLudusaviService.__init__)
    assert "adapter" in init_sig.parameters
    assert "adapter_factory" in init_sig.parameters
    assert "state_path" in init_sig.parameters
    assert "settings_store" in init_sig.parameters
    assert "cache_path" in init_sig.parameters
    assert "log_limit" in init_sig.parameters

    # 2. stop
    assert hasattr(service, "stop")
    assert inspect.ismethod(service.stop)
    assert len(inspect.signature(service.stop).parameters) == 0

    # 3. log
    assert hasattr(service, "log")
    log_sig = inspect.signature(service.log)
    assert list(log_sig.parameters.keys()) == ["level", "message", "operation", "game_name"]

    # 4. get_settings
    assert hasattr(service, "get_settings")
    assert len(inspect.signature(service.get_settings).parameters) == 0

    # 5. set_auto_sync_enabled
    assert hasattr(service, "set_auto_sync_enabled")
    assert list(inspect.signature(service.set_auto_sync_enabled).parameters.keys()) == ["enabled"]

    # 6. set_selected_game
    assert hasattr(service, "set_selected_game")
    assert list(inspect.signature(service.set_selected_game).parameters.keys()) == ["game_name"]

    # 7. set_notification_settings
    assert hasattr(service, "set_notification_settings")
    assert list(inspect.signature(service.set_notification_settings).parameters.keys()) == [
        "settings"
    ]

    # 8. get_game_history
    assert hasattr(service, "get_game_history")
    assert len(inspect.signature(service.get_game_history).parameters) == 0

    # 9. get_ludusavi_launcher_shortcut_id
    assert hasattr(service, "get_ludusavi_launcher_shortcut_id")
    assert len(inspect.signature(service.get_ludusavi_launcher_shortcut_id).parameters) == 0

    # 10. set_ludusavi_launcher_shortcut_id
    assert hasattr(service, "set_ludusavi_launcher_shortcut_id")
    assert list(inspect.signature(service.set_ludusavi_launcher_shortcut_id).parameters.keys()) == [
        "app_id"
    ]

    # 11. clear_ludusavi_launcher_shortcut_id
    assert hasattr(service, "clear_ludusavi_launcher_shortcut_id")
    assert len(inspect.signature(service.clear_ludusavi_launcher_shortcut_id).parameters) == 0

    # 12. get_ludusavi_command
    assert hasattr(service, "get_ludusavi_command")
    assert len(inspect.signature(service.get_ludusavi_command).parameters) == 0

    # 13. is_game_cache_current
    assert hasattr(service, "is_game_cache_current")
    assert list(inspect.signature(service.is_game_cache_current).parameters.keys()) == [
        "installed_app_ids"
    ]

    # 14. refresh_games
    assert hasattr(service, "refresh_games")
    assert list(inspect.signature(service.refresh_games).parameters.keys()) == [
        "force",
        "installed_app_ids",
    ]

    # 15. check_game_start
    assert hasattr(service, "check_game_start")
    assert list(inspect.signature(service.check_game_start).parameters.keys()) == [
        "game_name",
        "app_id",
    ]

    # 16. resolve_game_start_conflict
    assert hasattr(service, "resolve_game_start_conflict")
    assert list(inspect.signature(service.resolve_game_start_conflict).parameters.keys()) == [
        "game_name",
        "app_id",
        "resolution",
    ]

    # 17. restore_game_on_start
    assert hasattr(service, "restore_game_on_start")
    assert list(inspect.signature(service.restore_game_on_start).parameters.keys()) == [
        "game_name",
        "app_id",
    ]

    # 18. handle_game_start
    assert hasattr(service, "handle_game_start")
    assert list(inspect.signature(service.handle_game_start).parameters.keys()) == [
        "game_name",
        "app_id",
    ]

    # 19. check_game_exit
    assert hasattr(service, "check_game_exit")
    assert list(inspect.signature(service.check_game_exit).parameters.keys()) == [
        "game_name",
        "app_id",
    ]

    # 20. backup_game_on_exit
    assert hasattr(service, "backup_game_on_exit")
    assert list(inspect.signature(service.backup_game_on_exit).parameters.keys()) == [
        "game_name",
        "app_id",
    ]

    # 21. handle_game_exit
    assert hasattr(service, "handle_game_exit")
    assert list(inspect.signature(service.handle_game_exit).parameters.keys()) == [
        "game_name",
        "app_id",
    ]

    # 22. force_backup
    assert hasattr(service, "force_backup")
    assert list(inspect.signature(service.force_backup).parameters.keys()) == ["game_name"]

    # 23. force_restore
    assert hasattr(service, "force_restore")
    assert list(inspect.signature(service.force_restore).parameters.keys()) == ["game_name"]

    # 24. get_versions
    assert hasattr(service, "get_versions")
    assert len(inspect.signature(service.get_versions).parameters) == 0

    # 25. get_ludusavi_logs
    assert hasattr(service, "get_ludusavi_logs")
    assert len(inspect.signature(service.get_ludusavi_logs).parameters) == 0

    # 26. get_operation_status
    assert hasattr(service, "get_operation_status")
    assert len(inspect.signature(service.get_operation_status).parameters) == 0

    # 27. get_recent_logs
    assert hasattr(service, "get_recent_logs")
    assert len(inspect.signature(service.get_recent_logs).parameters) == 0

    # 28. resume_game_process
    assert hasattr(service, "resume_game_process")
    assert list(inspect.signature(service.resume_game_process).parameters.keys()) == ["pid"]

    # 29. pause_game_process
    assert hasattr(service, "pause_game_process")
    assert list(inspect.signature(service.pause_game_process).parameters.keys()) == ["pid"]


def test_sdh_ludusavi_service_facade_behavior(tmp_path: Path) -> None:
    """
    Do a basic test call of some methods on SDHLudusaviService to verify that they
    return compatible types under simple conditions.
    """
    service = SDHLudusaviService(
        adapter=DummyAdapter(),
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )

    # Basic setup values
    assert service.get_settings()["auto_sync_enabled"] is False
    service.set_auto_sync_enabled(True)
    assert service.get_settings()["auto_sync_enabled"] is True

    # Test process watchdog facade methods don't crash when called with bad PIDs (they report failed)
    assert service.pause_game_process(-1)["status"] == "failed"
    assert service.resume_game_process(-1)["status"] == "failed"

    # Test history integration
    history = service.get_game_history()
    assert isinstance(history, dict)
