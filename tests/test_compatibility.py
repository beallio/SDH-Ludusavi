"""Contract tests for the symbols and methods main.py consumes from the service façade."""

from __future__ import annotations

import inspect
from pathlib import Path

from sdh_ludusavi.service import SDHLudusaviService
from sdh_ludusavi.persistence import JsonSettingsStore


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


def test_facade_public_symbols() -> None:
    import sdh_ludusavi.constants as constants
    import sdh_ludusavi.coordinator as coordinator
    import sdh_ludusavi.service as service

    assert service.__all__ == [
        "SDHLudusaviService",
        "OperationLockedError",
        "DEFAULT_NOTIFICATION_SETTINGS",
    ]
    assert service.OperationLockedError is coordinator.OperationLockedError
    assert service.DEFAULT_NOTIFICATION_SETTINGS is constants.DEFAULT_NOTIFICATION_SETTINGS


EXPECTED_METHODS: dict[str, list[str]] = {
    "get_settings": [],
    "get_game_history": [],
    "set_auto_sync_enabled": ["enabled"],
    "set_selected_game": ["game_name"],
    "set_notification_settings": ["settings"],
    "set_debug_logging": ["enabled"],
    "log": ["level", "message", "operation", "game_name"],
    "set_update_channel": ["channel"],
    "set_automatic_update_checks": ["enabled"],
    "get_update_check_context": [],
    "check_for_plugin_update": ["current_version", "force"],
    "record_update_install_requested": ["candidate"],
    "confirm_update_install_handoff": ["version"],
    "clear_pending_update_install": ["version"],
    "reconcile_pending_update_install": ["current_version"],
    "revalidate_plugin_update": ["candidate"],
    "has_pending_update_install": [],
    "start_syncthing_activity_watch": ["phase", "game_name", "app_id"],
    "get_syncthing_activity": ["watch_id"],
    "stop_syncthing_activity_watch": ["watch_id"],
    "get_ludusavi_launcher_shortcut_id": [],
    "set_ludusavi_launcher_shortcut_id": ["app_id"],
    "clear_ludusavi_launcher_shortcut_id": [],
    "get_ludusavi_command": [],
    "refresh_games": ["force", "installed_app_ids"],
    "is_game_cache_current": ["installed_app_ids"],
    "check_game_start": ["game_name", "app_id"],
    "resolve_game_start_conflict": [
        "game_name",
        "app_id",
        "resolution",
        "gate_pid",
        "gate_lease_id",
    ],
    "restore_game_on_start": ["game_name", "app_id"],
    "handle_game_start": ["game_name", "app_id"],
    "check_game_exit": ["game_name", "app_id"],
    "backup_game_on_exit": ["game_name", "app_id"],
    "handle_game_exit": ["game_name", "app_id"],
    "force_backup": ["game_name"],
    "force_restore": ["game_name"],
    "get_versions": [],
    "get_ludusavi_logs": [],
    "get_operation_status": [],
    "get_recent_logs": [],
    "pause_game_process": ["pid"],
    "renew_game_process_pause": ["pid", "lease_id"],
    "resume_game_process": ["pid", "lease_id"],
    "stop": [],
}


def test_facade_method_signatures(tmp_path: Path) -> None:
    service = SDHLudusaviService(
        adapter=DummyAdapter(),
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )

    # 1. __init__ signature check
    init_sig = inspect.signature(SDHLudusaviService.__init__)
    assert "adapter" in init_sig.parameters
    assert "adapter_factory" in init_sig.parameters
    assert "settings_store" in init_sig.parameters
    assert "cache_path" in init_sig.parameters
    assert "log_limit" in init_sig.parameters

    for name, params in EXPECTED_METHODS.items():
        method = getattr(service, name, None)
        assert method is not None, f"main.py calls service.{name} but it does not exist"
        assert inspect.ismethod(method), name
        assert list(inspect.signature(method).parameters) == params, name


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
    assert service.renew_game_process_pause(-1, "bad")["status"] == "failed"
    assert service.resume_game_process(-1)["status"] == "failed"

    # Test history integration
    history = service.get_game_history()
    assert isinstance(history, dict)
