from __future__ import annotations
from pathlib import Path
from sdh_ludusavi.service import SDHLudusaviService
import pytest


class FakeAdapter:
    def refresh_statuses(self):
        return []

    def get_versions(self):
        return {}

    def get_log_contents(self):
        return ""


@pytest.fixture
def service(tmp_path: Path):
    return SDHLudusaviService(adapter=FakeAdapter(), state_path=tmp_path / "state.json")


def test_launcher_shortcut_id_persistence(service, tmp_path):
    # Initial state
    assert service.get_ludusavi_launcher_shortcut_id() == -1

    # Set ID
    assert service.set_ludusavi_launcher_shortcut_id(12345) is True
    assert service.get_ludusavi_launcher_shortcut_id() == 12345

    # Persistence check
    reloaded = SDHLudusaviService(adapter=FakeAdapter(), state_path=tmp_path / "state.json")
    assert reloaded.get_ludusavi_launcher_shortcut_id() == 12345

    # Clear ID
    assert service.clear_ludusavi_launcher_shortcut_id() is True
    assert service.get_ludusavi_launcher_shortcut_id() == -1

    # Persistence check after clear
    reloaded_after_clear = SDHLudusaviService(
        adapter=FakeAdapter(), state_path=tmp_path / "state.json"
    )
    assert reloaded_after_clear.get_ludusavi_launcher_shortcut_id() == -1


def test_get_ludusavi_command(service, monkeypatch):
    captured = {}

    # Mock find_ludusavi to simulate success
    def mock_find_ludusavi(**kwargs):
        captured.update(kwargs)
        return ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"]

    monkeypatch.setattr("pyludusavi.discovery.find_ludusavi", mock_find_ludusavi)

    cmd = service.get_ludusavi_command()
    assert cmd is not None
    assert cmd["commandPath"] == "/usr/bin/flatpak"
    assert cmd["args"] == ["run", "com.github.mtkennerly.ludusavi"]
    assert captured["explicit_flatpak_id"] == "com.github.mtkennerly.ludusavi"
    assert isinstance(captured["env"], dict)


def test_get_ludusavi_command_not_found(service, monkeypatch):
    # Mock find_ludusavi to simulate failure (raises exception)
    def mock_find_ludusavi_fail(**kwargs):
        from pyludusavi.discovery import LudusaviNotFoundError

        raise LudusaviNotFoundError("Not found")

    monkeypatch.setattr("pyludusavi.discovery.find_ludusavi", mock_find_ludusavi_fail)

    from pyludusavi.discovery import LudusaviNotFoundError

    with pytest.raises(LudusaviNotFoundError):
        service.get_ludusavi_command()
