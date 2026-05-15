from typing import cast

import pytest

import pyludusavi
from sdh_ludusavi.ludusavi import FLATPAK_ID, PyludusaviAdapter, _game_error, _games_from_output


def test_flatpak_id_is_required_ludusavi_flatpak() -> None:
    assert FLATPAK_ID == "com.github.mtkennerly.ludusavi"


def test_pyludusavi_version_is_current() -> None:
    assert pyludusavi.__version__ == "0.2.2"


def test_adapter_uses_upstream_pyludusavi_constructor_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    instances: list[object] = []

    class FakeLudusavi:
        command_prefix = ["/usr/bin/flatpak", "run", FLATPAK_ID]

        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.executor = object()
            instances.append(self)

    monkeypatch.setattr(pyludusavi, "Ludusavi", FakeLudusavi)

    PyludusaviAdapter()

    assert captured["flatpak_id"] == FLATPAK_ID
    assert "flatpak_user_home" not in captured
    assert "flatpak_user" not in captured
    assert "env" not in captured
    assert instances
    assert instances[0].executor is not None


def test_adapter_injects_ld_library_path_from_sdh_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_env: dict[str, str] | None = None

    class FakeExecutor:
        def execute(
            self,
            args: list[str],
            *,
            mode: str = "JSON",
            env: dict[str, str] | None = None,
            **kwargs: object,
        ) -> object:
            nonlocal seen_env
            seen_env = env
            return object()

    class FakeLudusavi:
        command_prefix = ["/usr/bin/flatpak", "run", FLATPAK_ID]

        def __init__(self, **kwargs: object) -> None:
            self.executor = FakeExecutor()

    monkeypatch.setattr(pyludusavi, "Ludusavi", FakeLudusavi)

    adapter = PyludusaviAdapter()
    adapter._client.executor.execute(["--version"], mode="TEXT")

    assert isinstance(seen_env, dict)
    assert cast(dict[str, str], seen_env)["LD_LIBRARY_PATH"] == ""


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
    def __init__(
        self, backup_data: dict[str, object], restore_data: dict[str, object] | None = None
    ) -> None:
        self.backup_data = backup_data
        self.restore_data = restore_data or {}
        self.requested_games: list[str] | None = None
        self.preview_requested: bool = False

    def backups_list(self, games: list[str] | None = None) -> FakeResponse:
        self.requested_games = games
        return FakeResponse(self.backup_data)

    def restore(
        self, games: list[str] | None = None, preview: bool = False, **kwargs: object
    ) -> FakeResponse:
        self.requested_games = games
        self.preview_requested = preview
        return FakeResponse(self.restore_data)


def adapter_with_backups(
    backup_data: dict[str, object],
    restore_data: dict[str, object] | None = None,
) -> tuple[PyludusaviAdapter, FakeLudusaviClient]:
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    client = FakeLudusaviClient(backup_data, restore_data)
    adapter._client = client
    return adapter, client


def test_compare_recency_returns_no_backup_when_ludusavi_has_no_backup() -> None:
    adapter, client = adapter_with_backups({"games": {}})

    assert adapter.compare_recency("Hades") == "no_backup"
    assert client.requested_games == ["Hades"]


def test_compare_recency_returns_backup_newer_when_restore_preview_shows_changes() -> None:
    adapter, client = adapter_with_backups(
        backup_data={"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}},
        restore_data={"games": {"Hades": {"change": "Different"}}},
    )

    assert adapter.compare_recency("Hades") == "backup_newer"
    assert client.preview_requested is True


def test_compare_recency_returns_local_current_when_restore_preview_shows_same() -> None:
    adapter, client = adapter_with_backups(
        backup_data={"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}},
        restore_data={"games": {"Hades": {"change": "Same"}}},
    )

    assert adapter.compare_recency("Hades") == "local_current"


def test_compare_recency_remains_ambiguous_on_preview_error() -> None:
    adapter, client = adapter_with_backups(
        backup_data={"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}}
    )

    def fail_preview(*args: object, **kwargs: object) -> FakeResponse:
        raise RuntimeError("preview failed")

    client.restore = fail_preview

    assert adapter.compare_recency("Hades") == "ambiguous"
