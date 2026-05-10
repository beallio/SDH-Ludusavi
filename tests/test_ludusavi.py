from sdh_ludusavi.ludusavi import FLATPAK_ID, PyludusaviAdapter, _game_error, _games_from_output


def test_flatpak_id_is_required_ludusavi_flatpak() -> None:
    assert FLATPAK_ID == "com.github.mtkennerly.ludusavi"


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
