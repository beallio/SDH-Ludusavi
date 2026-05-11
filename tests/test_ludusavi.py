import sys
import types

import pytest

import pyludusavi
from pyludusavi import main as pyludusavi_main
from sdh_ludusavi.ludusavi import FLATPAK_ID, PyludusaviAdapter, _game_error, _games_from_output


def test_flatpak_id_is_required_ludusavi_flatpak() -> None:
    assert FLATPAK_ID == "com.github.mtkennerly.ludusavi"


def test_pyludusavi_constructor_accepts_flatpak_user_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def find_ludusavi(**kwargs: object) -> list[str]:
        captured.update(kwargs)
        return ["/usr/bin/flatpak", "run", FLATPAK_ID]

    monkeypatch.setattr(pyludusavi_main, "find_ludusavi", find_ludusavi)

    pyludusavi_main.Ludusavi(flatpak_id=FLATPAK_ID, flatpak_user_home="/home/deck")

    assert captured["explicit_flatpak_id"] == FLATPAK_ID
    assert captured["flatpak_user_home"] == "/home/deck"


def test_adapter_passes_decky_user_home_to_pyludusavi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeLudusavi:
        command_prefix = ["/usr/bin/flatpak", "run", FLATPAK_ID]

        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import sdh_ludusavi.ludusavi

    monkeypatch.setattr(pyludusavi, "Ludusavi", FakeLudusavi)
    monkeypatch.setitem(
        sys.modules,
        "decky",
        types.SimpleNamespace(DECKY_USER_HOME="/home/deck", DECKY_USER="deck"),
    )
    monkeypatch.setattr(sdh_ludusavi.ludusavi, "_find_ludusavi_binary", lambda *args: None)
    monkeypatch.setattr(sdh_ludusavi.ludusavi, "_find_ludusavi_config_dir", lambda *args: None)

    PyludusaviAdapter()

    assert captured == {
        "explicit_path": None,
        "config_dir": None,
        "flatpak_id": FLATPAK_ID,
        "flatpak_user_home": "/home/deck",
        "flatpak_user": "deck",
    }


def test_games_from_output_accepts_ludusavi_api_shape() -> None:
    output = {
        "games": {
            "Hades": {"backups": [{"name": "full", "when": "2026-05-10T00:00:00Z"}]},
            "Ignored": "not a mapping",
        }
    }

    assert _games_from_output(output) == {
        "Hades": {"backups": [{"name": "full", "when": "2026-05-10T00:00:00Z"}]}
    }


def test_game_error_reports_failed_files_or_registry() -> None:
    assert _game_error({"files": {"save": {"failed": True, "error": {"message": "denied"}}}})
    assert _game_error({"registry": {"key": {"failed": True}}})
    assert _game_error({"files": {"save": {"failed": False}}}) is None


class FakeResponse:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data


class FakeLudusaviClient:
    def __init__(self, backup_data: dict[str, object]) -> None:
        self.backup_data = backup_data
        self.requested_games: list[str] | None = None

    def backups_list(self, games: list[str] | None = None) -> FakeResponse:
        self.requested_games = games
        return FakeResponse(self.backup_data)


def adapter_with_backups(
    backup_data: dict[str, object],
) -> tuple[PyludusaviAdapter, FakeLudusaviClient]:
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    client = FakeLudusaviClient(backup_data)
    adapter._client = client
    return adapter, client


def test_compare_recency_returns_no_backup_when_ludusavi_has_no_backup() -> None:
    adapter, client = adapter_with_backups({"games": {}})

    assert adapter.compare_recency("Hades") == "no_backup"
    assert client.requested_games == ["Hades"]


def test_compare_recency_remains_ambiguous_without_direct_recency_proof() -> None:
    adapter, client = adapter_with_backups(
        {"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}}
    )

    assert adapter.compare_recency("Hades") == "ambiguous"
    assert client.requested_games == ["Hades"]
