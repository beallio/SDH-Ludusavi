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
