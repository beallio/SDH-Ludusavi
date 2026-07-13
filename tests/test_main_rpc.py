from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.test_main import fake_decky_module, import_main


class MockService:
    def __init__(self, **kwargs):
        self.calls = []
        self.history = {
            "Hades": {
                "last_backup": None,
                "last_restore": None,
                "last_skip": None,
                "last_failure": None,
                "last_operation": None,
            }
        }

    def refresh_games(self, force: bool = False, installed_app_ids: str | None = None):
        self.calls.append(("refresh_games", force, installed_app_ids))
        return {"games": []}

    def get_settings(self):
        return {}

    def get_game_history(self):
        self.calls.append(("get_game_history",))
        return self.history

    def log(self, *args):
        pass

    def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
        self.calls.append(("is_game_cache_current", installed_app_ids))
        if getattr(self, "raise_on_cache_check", False):
            raise RuntimeError("adapter exploded")
        return True

    def get_ludusavi_launcher_shortcut_id(self) -> int:
        if getattr(self, "raise_on_shortcut", False):
            raise RuntimeError("boom")
        return 42

    def get_operation_status(self) -> dict[str, object]:
        if getattr(self, "raise_on_status", False):
            raise RuntimeError("boom")
        return {
            "is_running": True,
            "name": "backup",
            "game_name": "Hades",
            "last_result": None,
            "last_error": None,
        }

    def get_recent_logs(self) -> list[dict[str, object]]:
        if getattr(self, "raise_on_logs", False):
            raise RuntimeError("boom")
        return [
            {
                "level": "info",
                "message": "hi",
                "timestamp": "t",
                "operation": None,
                "game_name": None,
            }
        ]


def test_plugin_refresh_games_passes_installed_app_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()

    # Simulate RPC call with both arguments
    asyncio.run(plugin.refresh_games(force=True, installed_app_ids="1,2,3"))

    assert mock_service.calls == [("refresh_games", True, "1,2,3")]


def test_plugin_refresh_games_works_with_legacy_single_arg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()

    # Simulate legacy RPC call with one argument
    asyncio.run(plugin.refresh_games(force=True))

    assert mock_service.calls == [("refresh_games", True, None)]


def test_plugin_get_game_history_returns_service_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()

    result = asyncio.run(plugin.get_game_history())

    assert result == mock_service.history
    assert mock_service.calls == [("get_game_history",)]


def test_is_game_cache_current_returns_service_bool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    assert asyncio.run(plugin.is_game_cache_current("1,2")) is True
    assert ("is_game_cache_current", "1,2") in mock_service.calls


def test_is_game_cache_current_coerces_failure_to_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()
    mock_service.raise_on_cache_check = True

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    assert asyncio.run(plugin.is_game_cache_current("1,2")) is False


def test_get_ludusavi_launcher_shortcut_id_returns_int(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    assert asyncio.run(plugin.get_ludusavi_launcher_shortcut_id()) == 42


def test_get_ludusavi_launcher_shortcut_id_coerces_failure_to_minus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()
    mock_service.raise_on_shortcut = True

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    assert asyncio.run(plugin.get_ludusavi_launcher_shortcut_id()) == -1


def test_get_operation_status_coerces_failure_to_idle_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()
    mock_service.raise_on_status = True

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    assert asyncio.run(plugin.get_operation_status()) == {
        "is_running": False,
        "name": None,
        "game_name": None,
        "last_result": None,
        "last_error": None,
    }


def test_get_recent_logs_coerces_failure_to_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()
    mock_service.raise_on_logs = True

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    assert asyncio.run(plugin.get_recent_logs()) == []


def test_log_rpc_before_service_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def fail_service() -> Any:
        raise AssertionError("log must never construct the service")

    monkeypatch.setattr(plugin, "_service", fail_service)

    asyncio.run(plugin.log("info", "test message"))

    assert plugin._backend is None
    assert "[frontend:info] frontend: test message" in logger.infos


def test_plugin_renew_game_process_pause_calls_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()
    mock_service.renew_game_process_pause = lambda pid, lease_id: {"status": "renewed"}

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    result = asyncio.run(plugin.renew_game_process_pause(pid=123, lease_id="test_lease"))

    assert result == {"status": "renewed"}
