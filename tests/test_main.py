from __future__ import annotations

import asyncio
import ast
import importlib.util
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

from sdh_ludusavi.service import OperationLockedError


class FakeLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.exceptions: list[str] = []
        self.errors: list[str] = []

    def info(self, message: str, *args: object) -> None:
        self.infos.append(_format_log(message, args))

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(_format_log(message, args))

    def error(self, message: str, *args: object) -> None:
        self.errors.append(_format_log(message, args))

    def exception(self, message: str, *args: object) -> None:
        self.exceptions.append(_format_log(message, args))


def _format_log(message: str, args: tuple[object, ...]) -> str:
    return message % args if args else message


def fake_decky_module(
    tmp_path: Path,
    settings_dir: Path | str | None = None,
    plugin_settings_dir: Path | str | None = None,
    runtime_dir: Path | str | None = None,
    plugin_dirs: bool = True,
) -> tuple[types.SimpleNamespace, FakeLogger]:
    logger = FakeLogger()
    decky = types.SimpleNamespace(
        DECKY_USER_HOME=str(tmp_path / "decky-home"),
        DECKY_HOME=str(tmp_path / "decky"),
        logger=logger,
        migrate_logs=lambda *args: None,
        migrate_settings=lambda *args: None,
        migrate_runtime=lambda *args: None,
    )
    if plugin_dirs:
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(plugin_settings_dir or tmp_path / "plugin-settings")
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(runtime_dir or tmp_path / "plugin-data")
    if settings_dir is not None:
        decky.DECKY_SETTINGS_DIR = str(settings_dir)
    if plugin_settings_dir is not None:
        decky.DECKY_PLUGIN_SETTINGS_DIR = str(plugin_settings_dir)
    if runtime_dir is not None:
        decky.DECKY_PLUGIN_RUNTIME_DIR = str(runtime_dir)
    return decky, logger


class FakeSettingsManager:
    created: list[tuple[str, str | None]] = []

    def __init__(self, name: str, settings_directory: str | None = None) -> None:
        self.name = name
        self.settings_directory = settings_directory
        self.values: dict[str, object] = {}
        FakeSettingsManager.created.append((name, settings_directory))

    def read(self) -> None:
        return None

    def getSetting(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def setSetting(self, key: str, value: object) -> None:
        self.values[key] = value

    def commit(self) -> None:
        return None


def import_main(
    monkeypatch: pytest.MonkeyPatch,
    decky: types.SimpleNamespace,
    *,
    settings_manager: type[FakeSettingsManager] | None = None,
) -> Any:
    monkeypatch.setitem(sys.modules, "decky", decky)
    FakeSettingsManager.created = []
    monkeypatch.setitem(
        sys.modules,
        "settings",
        types.SimpleNamespace(SettingsManager=settings_manager or FakeSettingsManager),
    )
    sys.modules.pop("main", None)
    spec = importlib.util.spec_from_file_location("main", Path("main.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["main"] = module
    spec.loader.exec_module(module)
    return module


def test_migration_does_not_call_decky_template_migration_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    calls: list[str] = []

    def record_call(name: str) -> Any:
        def recorder(*_args: object) -> None:
            calls.append(name)

        return recorder

    decky.migrate_logs = record_call("migrate_logs")
    decky.migrate_settings = record_call("migrate_settings")
    decky.migrate_runtime = record_call("migrate_runtime")
    module = import_main(monkeypatch, decky)

    asyncio.run(module.Plugin()._migration())

    assert calls == []
    assert logger.infos == ["SDH-ludusavi migration skipped; no legacy paths to migrate"]


def test_migration_has_no_template_scaffolding_paths() -> None:
    content = Path("main.py").read_text(encoding="utf-8")

    assert "template" not in content.casefold()


def test_run_blocking_uses_shared_executor_without_pipes_or_threads() -> None:
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    run_blocking = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_blocking"
    )
    names = {node.id for node in ast.walk(run_blocking) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(run_blocking) if isinstance(node, ast.Attribute)}

    assert "run_in_executor" in attributes
    assert "copy_context" in attributes
    assert "pipe" not in attributes
    assert "add_reader" not in attributes
    assert "remove_reader" not in attributes
    assert "Thread" not in attributes
    assert "shield" not in attributes
    assert "sleep" not in attributes
    assert "to_thread" not in attributes
    assert "queue" not in names


def test_call_does_not_block_event_loop_while_callback_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    async def scenario() -> None:
        def blocking_callback() -> dict[str, str]:
            time.sleep(0.15)
            return {"status": "ok"}

        started = time.perf_counter()
        task = asyncio.create_task(plugin._call("blocking", blocking_callback))
        await asyncio.sleep(0.01)

        assert time.perf_counter() - started < 0.08
        assert await task == {"status": "ok"}

    asyncio.run(scenario())


def test_call_maps_operation_locked_error_from_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def raise_locked() -> dict[str, object]:
        raise OperationLockedError("refresh is already running")

    result = asyncio.run(plugin._call("refresh", raise_locked))

    assert result == {
        "status": "skipped",
        "reason": "operation_running",
        "message": "refresh is already running",
    }
    assert logger.infos == ["refresh skipped: refresh is already running"]


def test_call_maps_generic_exception_from_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def raise_failure() -> dict[str, object]:
        raise RuntimeError("boom")

    result = asyncio.run(plugin._call("refresh", raise_failure))

    assert result == {"status": "failed", "message": "boom"}
    assert logger.exceptions == ["refresh failed"]


def test_call_maps_base_exception_from_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WorkerFatal(BaseException):
        pass

    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def raise_failure() -> dict[str, object]:
        raise WorkerFatal("fatal")

    result = asyncio.run(plugin._call("refresh", raise_failure))

    assert result == {"status": "failed", "message": "fatal"}
    assert logger.exceptions == ["refresh failed"]


def test_plugin_exposes_split_lifecycle_check_and_action_rpcs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[tuple[str, str, str | None]] = []

    class CapturingService:
        def __init__(self, settings_store: object, cache_path: Path) -> None:
            self.settings_store = settings_store
            self.cache_path = cache_path

        def check_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
            calls.append(("check_start", game_name, app_id))
            return {"status": "needed", "operation": "restore", "game": game_name}

        def restore_game_on_start(
            self, game_name: str, app_id: str | None = None
        ) -> dict[str, object]:
            calls.append(("restore_start", game_name, app_id))
            return {"status": "restored", "game": game_name}

        def check_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
            calls.append(("check_exit", game_name, app_id))
            return {"status": "needed", "operation": "backup", "game": game_name}

        def backup_game_on_exit(
            self, game_name: str, app_id: str | None = None
        ) -> dict[str, object]:
            calls.append(("backup_exit", game_name, app_id))
            return {"status": "backed_up", "game": game_name}

        def resolve_game_start_conflict(
            self, game_name: str, app_id: str | None, resolution: str
        ) -> dict[str, object]:
            calls.append((f"resolve_{resolution}", game_name, app_id))
            return {"status": "restored", "game": game_name}

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)

    async def scenario() -> None:
        assert await plugin.check_game_start("Hades", "1145360") == {
            "status": "needed",
            "operation": "restore",
            "game": "Hades",
        }
        assert await plugin.restore_game_on_start("Hades", "1145360") == {
            "status": "restored",
            "game": "Hades",
        }
        assert await plugin.check_game_exit("Hades", "1145360") == {
            "status": "needed",
            "operation": "backup",
            "game": "Hades",
        }
        assert await plugin.backup_game_on_exit("Hades", "1145360") == {
            "status": "backed_up",
            "game": "Hades",
        }
        assert await plugin.resolve_game_start_conflict("Hades", "1145360", "restore_backup") == {
            "status": "restored",
            "game": "Hades",
        }

    asyncio.run(scenario())

    assert calls == [
        ("check_start", "Hades", "1145360"),
        ("restore_start", "Hades", "1145360"),
        ("check_exit", "Hades", "1145360"),
        ("backup_exit", "Hades", "1145360"),
        ("resolve_restore_backup", "Hades", "1145360"),
    ]


def test_plugin_exposes_process_pause_resume_rpcs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[tuple[str, int]] = []

    class CapturingService:
        def __init__(self, settings_store: object, cache_path: Path) -> None:
            self.settings_store = settings_store
            self.cache_path = cache_path

        def pause_game_process(self, pid: int) -> dict[str, object]:
            calls.append(("pause", pid))
            return {"status": "paused", "pid": pid}

        def resume_game_process(self, pid: int) -> dict[str, object]:
            calls.append(("resume", pid))
            return {"status": "resumed", "pid": pid}

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)

    async def scenario() -> None:
        assert await plugin.pause_game_process(1234) == {"status": "paused", "pid": 1234}
        assert await plugin.resume_game_process(1234) == {"status": "resumed", "pid": 1234}

    asyncio.run(scenario())

    assert calls == [("pause", 1234), ("resume", 1234)]


def test_unload_stops_backend_through_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[str] = []

    class Backend:
        def stop(self) -> None:
            calls.append("stop")

    async def fake_call(operation: str, callback: Any) -> object:
        calls.append(operation)
        return callback()

    plugin._backend = Backend()
    monkeypatch.setattr(plugin, "_call", fake_call)

    asyncio.run(plugin._unload())

    assert calls == ["unload_stop", "stop"]
    assert logger.infos[-1] == "SDH-ludusavi backend unloaded"


def test_unload_does_not_block_event_loop_while_stop_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    class SlowBackend:
        def stop(self) -> None:
            time.sleep(0.15)

    plugin._backend = SlowBackend()

    async def scenario() -> None:
        started = time.perf_counter()
        task = asyncio.create_task(plugin._unload())
        await asyncio.sleep(0.01)

        assert time.perf_counter() - started < 0.08
        assert not task.done()
        await task

    asyncio.run(scenario())


def test_unload_falls_back_to_synchronous_stop_when_offload_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[str] = []

    class Backend:
        def stop(self) -> None:
            calls.append("stop")

    async def fake_call(operation: str, callback: Any) -> dict[str, str]:
        calls.append(operation)
        return {"status": "failed", "message": "loop closed"}

    plugin._backend = Backend()
    monkeypatch.setattr(plugin, "_call", fake_call)

    asyncio.run(plugin._unload())

    assert calls == ["unload_stop", "stop"]
    assert logger.warnings == ["Offloaded unload stop failed; falling back to synchronous stop"]
    assert logger.infos[-1] == "SDH-ludusavi backend unloaded"


def test_unload_cancellation_runs_synchronous_stop_before_reraising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[str] = []

    class Backend:
        def stop(self) -> None:
            calls.append("stop")

    async def fake_call(operation: str, callback: Any) -> object:
        calls.append(operation)
        raise asyncio.CancelledError

    plugin._backend = Backend()
    monkeypatch.setattr(plugin, "_call", fake_call)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(plugin._unload())

    assert calls == ["unload_stop", "stop"]
    assert logger.warnings == ["Unload stop was cancelled; falling back to synchronous stop"]
    assert logger.infos[-1] == "SDH-ludusavi backend unloaded"


def test_unload_logs_synchronous_stop_fallback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    class Backend:
        def stop(self) -> None:
            raise RuntimeError("still failed")

    async def fake_call(operation: str, callback: Any) -> dict[str, str]:
        return {"status": "failed", "message": "loop closed"}

    plugin._backend = Backend()
    monkeypatch.setattr(plugin, "_call", fake_call)

    asyncio.run(plugin._unload())

    assert logger.warnings == ["Offloaded unload stop failed; falling back to synchronous stop"]
    assert logger.exceptions == ["Synchronous unload stop fallback failed"]
    assert logger.infos[-1] == "SDH-ludusavi backend unloaded"


def test_unload_shuts_down_executor_and_post_shutdown_call_fails_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    asyncio.run(plugin._unload())

    result = asyncio.run(plugin._call("post_unload", lambda: "should not run"))

    assert result["status"] == "failed"
    assert logger.exceptions == ["post_unload failed"]


def test_service_uses_decky_plugin_settings_and_runtime_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_settings_dir = tmp_path / "homebrew" / "settings" / "SDH-ludusavi"
    runtime_dir = tmp_path / "homebrew" / "data" / "SDH-ludusavi"
    decky, _logger = fake_decky_module(
        tmp_path,
        plugin_settings_dir=plugin_settings_dir,
        runtime_dir=runtime_dir,
    )
    module = import_main(monkeypatch, decky, settings_manager=FakeSettingsManager)
    captured: dict[str, object] = {}

    class CapturingService:
        def __init__(self, settings_store: object, cache_path: Path) -> None:
            captured["settings_store"] = settings_store
            captured["cache_path"] = cache_path

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)

    module.Plugin()._service()

    assert FakeSettingsManager.created == [("settings", str(plugin_settings_dir))]
    assert captured["cache_path"] == runtime_dir / "cache.json"


def test_storage_resolvers_require_decky_plugin_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, _logger = fake_decky_module(tmp_path, plugin_dirs=False)
    module = import_main(monkeypatch, decky, settings_manager=FakeSettingsManager)

    with pytest.raises(RuntimeError, match="DECKY_PLUGIN_SETTINGS_DIR"):
        module._settings_store()

    decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path / "settings")

    with pytest.raises(RuntimeError, match="DECKY_PLUGIN_RUNTIME_DIR"):
        module._cache_path()


def test_storage_resolver_surfaces_unusable_decky_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_dir = tmp_path / "primary"
    decky, _logger = fake_decky_module(tmp_path, plugin_settings_dir=primary_dir)
    module = import_main(monkeypatch, decky)

    def fake_ensure_private_directory(path: Path) -> None:
        if path == primary_dir:
            raise OSError("readonly")

    monkeypatch.setattr(module, "_ensure_private_directory", fake_ensure_private_directory)

    with pytest.raises(OSError, match="readonly"):
        module._settings_store()


def test_service_initializes_once_when_called_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_dir = tmp_path / "settings"
    decky, _logger = fake_decky_module(tmp_path, settings_dir=settings_dir)
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    barrier = threading.Barrier(3)
    count_lock = threading.Lock()
    services: list[object] = []
    errors: list[BaseException] = []
    service_count = 0

    class CapturingService:
        def __init__(self, settings_store: object, cache_path: Path) -> None:
            nonlocal service_count
            with count_lock:
                service_count += 1
            self.settings_store = settings_store
            self.cache_path = cache_path
            time.sleep(0.05)

    def load_service() -> None:
        try:
            barrier.wait(timeout=1)
            services.append(plugin._service())
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)
    threads = [threading.Thread(target=load_service) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=1)
    for thread in threads:
        thread.join(timeout=1)

    assert errors == []
    assert service_count == 1
    assert len(services) == 2
    assert services[0] is services[1]


@pytest.mark.parametrize("settings_dir", [None, ""])
def test_service_ignores_legacy_decky_settings_dir_for_plugin_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_dir: str | None,
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=settings_dir)
    module = import_main(monkeypatch, decky, settings_manager=FakeSettingsManager)
    captured: dict[str, object] = {}

    class CapturingService:
        def __init__(self, settings_store: object, cache_path: Path) -> None:
            captured["settings_store"] = settings_store
            captured["cache_path"] = cache_path

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)

    module.Plugin()._service()

    assert FakeSettingsManager.created == [("settings", decky.DECKY_PLUGIN_SETTINGS_DIR)]
    assert captured["cache_path"] == Path(decky.DECKY_PLUGIN_RUNTIME_DIR) / "cache.json"


def test_decky_settings_store_read_failure_handled_gracefully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    class FailingSettingsManager(FakeSettingsManager):
        def read(self) -> None:
            raise OSError("permission denied")

    decky, logger = fake_decky_module(tmp_path)
    module = import_main(monkeypatch, decky, settings_manager=FailingSettingsManager)

    plugin = module.Plugin()
    with caplog.at_level(logging.WARNING):
        service = plugin._service()

    assert service.get_settings()["auto_sync_enabled"] is False
    assert any(
        "unreadable settings: permission denied" in record.message for record in caplog.records
    )


def test_plugin_main_triggers_reconciliation(tmp_path: Path, monkeypatch) -> None:
    from tests.test_main import fake_decky_module, import_main, FakeSettingsManager

    decky, _ = fake_decky_module(tmp_path)
    module = import_main(monkeypatch, decky, settings_manager=FakeSettingsManager)

    plugin = module.Plugin()
    service = plugin._service()

    reconciled_version = None

    def mock_reconcile(current_version: str) -> None:
        nonlocal reconciled_version
        reconciled_version = current_version

    monkeypatch.setattr(service, "reconcile_pending_update_install", mock_reconcile)

    asyncio.run(plugin._main())

    assert reconciled_version is not None


def test_plugin_syncthing_rpc(tmp_path: Path, monkeypatch) -> None:
    from tests.test_main import fake_decky_module, import_main, FakeSettingsManager
    from unittest.mock import MagicMock

    decky, _ = fake_decky_module(tmp_path)
    module = import_main(monkeypatch, decky, settings_manager=FakeSettingsManager)

    plugin = module.Plugin()
    service = plugin._service()

    service.start_syncthing_activity_watch = MagicMock(
        return_value={"status": "watching", "watch_id": "test-id"}
    )
    service.get_syncthing_activity = MagicMock(return_value={"status": "activity"})
    service.stop_syncthing_activity_watch = MagicMock(return_value={"status": "stopped"})

    res = asyncio.run(plugin.start_syncthing_activity_watch("pre_game", "Hades", "1145300"))
    assert res["status"] == "watching"
    service.start_syncthing_activity_watch.assert_called_once_with("pre_game", "Hades", "1145300")

    poll_res = asyncio.run(plugin.get_syncthing_activity("test-id"))
    assert poll_res["status"] == "activity"
    service.get_syncthing_activity.assert_called_once_with("test-id")

    stop_res = asyncio.run(plugin.stop_syncthing_activity_watch("test-id"))
    assert stop_res["status"] == "stopped"
    service.stop_syncthing_activity_watch.assert_called_once_with("test-id")


def test_is_game_cache_current_does_not_block_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    event = threading.Event()

    class BlockingService:
        def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
            # Bounded wait: if the handler regresses to running on the event
            # loop, the elapsed-time assertion fails after ~5s instead of
            # hanging pytest forever (no pytest-timeout plugin is configured).
            event.wait(timeout=5.0)
            return True

    monkeypatch.setattr(plugin, "_service", lambda: BlockingService())

    async def scenario() -> None:
        started = time.perf_counter()
        task = asyncio.create_task(plugin.is_game_cache_current("1,2"))
        await asyncio.sleep(0.01)

        assert time.perf_counter() - started < 0.08
        event.set()
        assert await task is True

    asyncio.run(scenario())


def test_main_offloads_service_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[str] = []

    async def fake_call(operation: str, callback: Any) -> object:
        calls.append(operation)
        if callable(callback):
            return callback()
        return None

    class FakeService:
        def reconcile_pending_update_install(self, version: str) -> None:
            calls.append("reconcile_call")

    plugin._backend = FakeService()
    monkeypatch.setattr(plugin, "_call", fake_call)
    monkeypatch.setattr(plugin, "_service", lambda: plugin._backend)

    asyncio.run(plugin._main())

    assert "startup_init" in calls
    assert "reconcile_pending_update_install" in calls
    assert calls.index("startup_init") < calls.index("reconcile_pending_update_install")
    assert "reconcile_call" in calls


def test_main_logs_initialization_failure_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    async def fake_call(operation: str, callback: Any) -> object:
        if operation == "startup_init":
            return {"status": "failed", "message": "disk exploded"}
        return {"status": "ok"}

    monkeypatch.setattr(plugin, "_call", fake_call)

    asyncio.run(plugin._main())

    assert any(
        "Service initialization failed during startup: disk exploded" in msg
        for msg in logger.errors
    )


def test_main_logs_initialization_failure_via_real_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def exploding_service() -> Any:
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(plugin, "_service", exploding_service)

    asyncio.run(plugin._main())

    assert any(
        "Service initialization failed during startup: disk exploded" in msg
        for msg in logger.errors
    )
