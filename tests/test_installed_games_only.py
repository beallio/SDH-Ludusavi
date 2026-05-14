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


def test_refresh_statuses_should_include_only_installed_games():
    preview_data = {
        "games": {
            "Installed Game": {"files": {"a": {}}, "change": "Same"},
            "Empty Game": {"files": {}, "registry": {}, "change": "Unknown"},
        }
    }
    backups_data = {
        "games": {
            "Installed Game": {"backups": [{"name": "1"}]},
            "Uninstalled Game": {"backups": [{"name": "1"}]},
            "Empty Game": {"backups": [{"name": "1"}]},
        }
    }

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = FakeClient(preview_data, backups_data)

    statuses = adapter.refresh_statuses()
    names = [s["name"] for s in statuses]

    # We want ONLY installed games (those with files or registry found)
    assert names == ["Installed Game"]
    assert "Uninstalled Game" not in names
    assert "Empty Game" not in names
