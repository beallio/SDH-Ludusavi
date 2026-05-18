from unittest.mock import MagicMock
from pathlib import Path
import pytest

from tests.test_main import fake_decky_module, import_main


@pytest.fixture
def plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    return module.Plugin()


@pytest.mark.asyncio
async def test_plugin_call_wraps_success(plugin) -> None:
    mock_service = MagicMock()
    mock_service.get_settings.return_value = {"foo": "bar"}
    plugin._backend = mock_service

    result = await plugin.get_settings()
    assert result == {"foo": "bar"}
    assert mock_service.get_settings.call_count == 1


@pytest.mark.asyncio
async def test_plugin_call_wraps_failure(plugin) -> None:
    mock_service = MagicMock()
    mock_service.get_ludusavi_logs.side_effect = RuntimeError("disk error")
    plugin._backend = mock_service

    result = await plugin.get_ludusavi_logs()
    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert "disk error" in result["message"]


@pytest.mark.asyncio
async def test_get_ludusavi_command_discovery_failure(plugin) -> None:
    mock_service = MagicMock()
    # Mocking what happens if find_ludusavi throws inside get_ludusavi_command
    mock_service.get_ludusavi_command.side_effect = Exception("discovery failed")
    plugin._backend = mock_service

    result = await plugin.get_ludusavi_command()
    assert result == {"status": "failed", "message": "discovery failed"}


@pytest.mark.asyncio
async def test_get_ludusavi_command_not_found(plugin) -> None:
    mock_service = MagicMock()
    mock_service.get_ludusavi_command.return_value = None
    plugin._backend = mock_service

    result = await plugin.get_ludusavi_command()
    assert result is None
