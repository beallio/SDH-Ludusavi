from sdh_ludusavi.ludusavi import PyludusaviAdapter


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeClient:
    def __init__(self, preview_data, backups_data):
        self.preview_data = preview_data
        self.backups_data = backups_data

    def backup(self, preview=False, **kwargs):
        return FakeResponse(self.preview_data)

    def backups_list(self, **kwargs):
        return FakeResponse(self.backups_data)


def test_refresh_statuses_should_exclude_ignored_games():
    preview_data = {
        "games": {
            "Enabled Game": {"files": {"a": {}}, "decision": "Processed", "change": "Same"},
            "Ignored Game": {"files": {"a": {}}, "decision": "Ignored", "change": "Unknown"},
            "Cancelled Game": {"files": {"a": {}}, "decision": "Cancelled", "change": "Unknown"},
            "No Decision Game": {"files": {"a": {}}, "change": "Same"},
        }
    }
    backups_data = {"games": {}}

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = FakeClient(preview_data, backups_data)

    statuses = adapter.refresh_statuses()
    names = [s["name"] for s in statuses]

    # We want ONLY processed or implicitly processed games
    assert "Enabled Game" in names
    assert "No Decision Game" in names
    assert "Ignored Game" not in names
    assert "Cancelled Game" not in names
