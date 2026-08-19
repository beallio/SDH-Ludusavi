"""Contract tests for the symbols and methods main.py consumes from the service façade."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
import re


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
    "set_game_sync_enabled": ["game_name", "enabled"],
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
    "restore_game_on_start": ["game_name", "app_id", "gate_pid", "gate_lease_id"],
    "check_game_exit": ["game_name", "app_id"],
    "backup_game_on_exit": ["game_name", "app_id"],
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


def test_start_mutation_contracts_propagate_pid_and_lease_id_across_every_boundary() -> None:
    from sdh_ludusavi.lifecycle import GameLifecycleManager

    for method in (
        SDHLudusaviService.restore_game_on_start,
        GameLifecycleManager.restore_game_on_start,
    ):
        assert list(inspect.signature(method).parameters)[-2:] == ["gate_pid", "gate_lease_id"]

    rpc_source = Path("src/api/ludusaviRpc.ts").read_text(encoding="utf-8")
    lifecycle_rpc_source = Path("src/controllers/gameLifecycleRpc.ts").read_text(encoding="utf-8")
    controller_source = Path("src/controllers/gameLifecycleController.tsx").read_text(
        encoding="utf-8"
    )

    assert re.search(
        r"restoreGameOnStartCall\s*=\s*callable<\[\s*gameName: string,\s*"
        r"app_id\?: string,\s*gatePid\?: number,\s*gateLeaseId\?: string",
        rpc_source,
        re.DOTALL,
    )
    assert re.search(
        r"restoreGameOnStart:\s*\(gameName: string, appID\?: string, gatePid\?: number, "
        r"gateLeaseId\?: string\)",
        lifecycle_rpc_source,
    )
    assert (
        "restoreGameOnStart(name, appID, guardHandle.pid, guardHandle.leaseId)" in controller_source
    )


def test_bundled_frontend_does_not_depend_on_removed_compatibility_rpcs() -> None:
    removed_rpc_names = {
        "handle_game_start",
        "handle_game_exit",
        "clear_ludusavi_launcher_shortcut_id",
    }
    frontend_sources = [
        path
        for path in Path("src").rglob("*")
        if path.suffix in {".ts", ".tsx"} and not path.name.endswith((".test.ts", ".test.tsx"))
    ]

    assert frontend_sources
    for path in frontend_sources:
        assert not (
            removed_rpc_names & set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", path.read_text()))
        )

    main_source = Path("main.py").read_text(encoding="utf-8")
    main_tree = ast.parse(main_source)
    plugin_class = next(
        node for node in main_tree.body if isinstance(node, ast.ClassDef) and node.name == "Plugin"
    )
    public_async_methods = {
        node.name for node in plugin_class.body if isinstance(node, ast.AsyncFunctionDef)
    }

    assert public_async_methods.isdisjoint(removed_rpc_names)


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
