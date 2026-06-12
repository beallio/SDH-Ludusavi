import os
import threading
from datetime import datetime
from unittest.mock import patch

import pytest

import pyludusavi
from sdh_ludusavi.constants import (
    LUDUSAVI_OPERATION_TIMEOUT_SECONDS,
    LUDUSAVI_PREVIEW_TIMEOUT_SECONDS,
)
from sdh_ludusavi.ludusavi import (
    FLATPAK_ID,
    PyludusaviAdapter,
    _game_error,
    _games_from_output,
    _ludusavi_env,
)


def test_flatpak_id_is_required_ludusavi_flatpak() -> None:
    assert FLATPAK_ID == "com.github.mtkennerly.ludusavi"


def test_pyludusavi_version_is_current() -> None:
    assert pyludusavi.__version__ == "0.2.3"


def test_adapter_passes_upstream_env_to_pyludusavi_constructor(
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
    assert isinstance(captured["env"], dict)
    assert "flatpak_user_home" not in captured
    assert "flatpak_user" not in captured
    assert instances
    assert instances[0].executor is not None


def test_ludusavi_env_uses_flatpak_defaults_without_mutating_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "decky-runtime-value")

    with patch("os.getuid", return_value=1001), patch("os.path.isdir", return_value=True):
        env = _ludusavi_env()

    assert env["XDG_RUNTIME_DIR"] == "/run/user/1001"
    assert env["LD_LIBRARY_PATH"] == ""
    assert os.environ["LD_LIBRARY_PATH"] == "decky-runtime-value"


def test_ludusavi_env_falls_back_when_uid_runtime_dir_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with patch("os.getuid", return_value=0), patch("os.path.isdir", return_value=False):
        env = _ludusavi_env()

    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"


def test_ludusavi_env_preserves_existing_xdg_runtime_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1234")
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)

    env = _ludusavi_env()

    assert env["XDG_RUNTIME_DIR"] == "/run/user/1234"
    assert "LD_LIBRARY_PATH" not in env


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


def test_refresh_statuses_runs_preview_and_backups_probes_concurrently() -> None:
    backup_started = threading.Event()
    release_preview = threading.Event()

    class ConcurrentProbeClient:
        def backup(self, preview: bool = False, **kwargs: object) -> FakeResponse:
            assert preview is True
            if not backup_started.wait(timeout=1):
                raise AssertionError("backups_list did not start while preview was running")
            release_preview.wait(timeout=1)
            return FakeResponse(
                {
                    "games": {
                        "Hades": {
                            "files": {"save": {}},
                            "registry": {},
                            "steamId": 1145360,
                        }
                    }
                }
            )

        def backups_list(self) -> FakeResponse:
            backup_started.set()
            release_preview.set()
            return FakeResponse({"games": {"Hades": {"backups": [{"name": "full"}]}}})

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = ConcurrentProbeClient()

    assert adapter.refresh_statuses() == [
        {
            "name": "Hades",
            "configured": True,
            "has_backup": True,
            "needs_first_backup": False,
            "steam_id": "1145360",
            "error": None,
        }
    ]


class FakeResponse:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data


class FakeLudusaviClient:
    def __init__(
        self,
        backup_data: dict[str, object],
        restore_data: dict[str, object] | None = None,
        backup_preview_data: dict[str, object] | None = None,
    ) -> None:
        self.backup_data = backup_data
        self.restore_data = restore_data or {}
        self.backup_preview_data = backup_preview_data or {}
        self.requested_games: list[str] | None = None
        self.preview_requested: bool = False
        self.calls: list[tuple] = []
        self.last_restore_kwargs: dict[str, object] = {}

    def backups_list(self, games: list[str] | None = None) -> FakeResponse:
        self.requested_games = games
        return FakeResponse(self.backup_data)

    def restore(
        self,
        games: list[str] | None = None,
        preview: bool = False,
        force: bool = False,
        timeout: float | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        self.requested_games = games
        self.preview_requested = preview
        self.calls.append(("restore", tuple(games or ()), preview, timeout))
        self.last_restore_kwargs = {
            "games": games,
            "preview": preview,
            "force": force,
            "timeout": timeout,
            **kwargs,
        }
        return FakeResponse(self.restore_data)

    def backup(
        self,
        games: list[str] | None = None,
        preview: bool = False,
        force: bool = False,
        timeout: float | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        self.requested_games = games
        self.preview_requested = preview
        self.calls.append(("backup", tuple(games or ()), preview, timeout))
        return FakeResponse(self.backup_preview_data)


def adapter_with_backups(
    backup_data: dict[str, object],
    restore_data: dict[str, object] | None = None,
    backup_preview_data: dict[str, object] | None = None,
) -> tuple[PyludusaviAdapter, FakeLudusaviClient]:
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    client = FakeLudusaviClient(backup_data, restore_data, backup_preview_data)
    adapter._client = client
    return adapter, client


def test_compare_recency_returns_no_backup_when_ludusavi_has_no_backup() -> None:
    adapter, client = adapter_with_backups({"games": {}})

    assert adapter.compare_recency("Hades") == "no_backup"
    assert client.requested_games == ["Hades"]


def test_compare_recency_returns_backup_newer_when_restore_preview_shows_new() -> None:
    adapter, client = adapter_with_backups(
        backup_data={"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}},
        restore_data={"games": {"Hades": {"change": "New"}}},
    )

    assert adapter.compare_recency("Hades") == "backup_newer"
    assert client.preview_requested is True


def test_compare_recency_returns_backup_differs_when_restore_preview_shows_different() -> None:
    adapter, client = adapter_with_backups(
        backup_data={"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}},
        restore_data={"games": {"Hades": {"change": "Different"}}},
    )

    assert adapter.compare_recency("Hades") == "backup_differs"
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
        raise pyludusavi.LudusaviError("preview failed")

    client.restore = fail_preview

    assert adapter.compare_recency("Hades") == "ambiguous"


def test_conflict_metadata_local_modified_at_is_timezone_aware_utc(tmp_path):
    save_file = tmp_path / "save.dat"
    save_file.write_text("save", encoding="utf-8")
    os.utime(save_file, (1_800_000_000, 1_800_000_000))
    adapter, _client = adapter_with_backups(
        backup_data={
            "games": {
                "Hades": {
                    "backups": [{"when": "2026-05-10T00:00:00Z"}],
                    "backupPath": "/backup/Hades",
                }
            }
        },
        backup_preview_data={
            "games": {
                "Hades": {
                    "files": {
                        "save": {"originalPath": str(save_file)},
                    }
                }
            }
        },
    )

    metadata = adapter.get_conflict_metadata("Hades")

    assert metadata["backupModifiedAt"] == "2026-05-10T00:00:00Z"
    assert metadata["backupPath"] == "/backup/Hades"
    assert str(metadata["localModifiedAt"]).endswith("+00:00")
    assert datetime.fromisoformat(str(metadata["localModifiedAt"])).tzinfo is not None


def test_get_conflict_metadata_uses_newest_backup_timestamp() -> None:
    """When multiple backups exist, pick the one with the latest 'when' timestamp."""
    adapter, _client = adapter_with_backups(
        backup_data={
            "games": {
                "Hades": {
                    "backups": [
                        {"when": "2026-05-10T00:00:00Z", "name": "full"},
                        {"when": "2026-06-01T12:00:00Z", "name": "differential"},
                    ],
                    "backupPath": "/backup/Hades",
                }
            }
        },
    )

    metadata = adapter.get_conflict_metadata("Hades")

    assert metadata["backupModifiedAt"] == "2026-06-01T12:00:00Z"
    assert metadata["backupPath"] == "/backup/Hades"


def test_newest_backup_when_returns_latest_timestamp() -> None:
    from sdh_ludusavi.ludusavi import _newest_backup_when

    backups: list[dict[str, object]] = [
        {"when": "2026-05-10T00:00:00Z", "name": "full"},
        {"when": "2026-06-01T12:00:00Z", "name": "differential"},
    ]
    assert _newest_backup_when(backups) == "2026-06-01T12:00:00Z"


def test_newest_backup_when_returns_none_for_empty_list() -> None:
    from sdh_ludusavi.ludusavi import _newest_backup_when

    assert _newest_backup_when([]) is None


def test_newest_backup_when_returns_none_when_no_when_keys() -> None:
    from sdh_ludusavi.ludusavi import _newest_backup_when

    backups: list[dict[str, object]] = [{"name": "full"}, {"name": "differential"}]
    assert _newest_backup_when(backups) is None


def test_refresh_statuses_forwards_game_names_to_client() -> None:
    calls = []

    class MockClient:
        def backup(
            self, games: list[str] | None = None, preview: bool = False, **kwargs: object
        ) -> FakeResponse:
            calls.append(("backup", games, preview, kwargs.get("timeout")))
            return FakeResponse({"games": {}})

        def backups_list(self, games: list[str] | None = None) -> FakeResponse:
            calls.append(("backups_list", games))
            return FakeResponse({"games": {}})

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = MockClient()

    adapter.refresh_statuses(game_names=["Hades"])
    assert ("backup", ["Hades"], True, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) in calls
    assert ("backups_list", ["Hades"]) in calls


def test_adapter_backup_passes_operation_timeout() -> None:
    adapter, client = adapter_with_backups({"games": {}})
    adapter.backup("Hades")
    assert ("backup", ("Hades",), False, LUDUSAVI_OPERATION_TIMEOUT_SECONDS) in client.calls


def test_adapter_backup_preview_passes_preview_timeout() -> None:
    adapter, client = adapter_with_backups({"games": {}})
    adapter.backup("Hades", preview=True)
    assert ("backup", ("Hades",), True, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) in client.calls


def test_adapter_restore_passes_operation_timeout() -> None:
    adapter, client = adapter_with_backups({"games": {}})
    adapter.restore("Hades")
    assert ("restore", ("Hades",), False, LUDUSAVI_OPERATION_TIMEOUT_SECONDS) in client.calls


def test_refresh_statuses_uses_preview_timeout() -> None:
    """The bulk preview inside refresh_statuses must pass the preview budget."""
    calls = []

    class MockClient:
        def backup(
            self, games: list[str] | None = None, preview: bool = False, **kwargs: object
        ) -> FakeResponse:
            calls.append(("backup", games, preview, kwargs.get("timeout")))
            return FakeResponse({"games": {}})

        def backups_list(self, games: list[str] | None = None) -> FakeResponse:
            return FakeResponse({"games": {}})

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = MockClient()
    adapter.refresh_statuses()
    assert ("backup", None, True, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) in calls


def test_compare_recency_restore_preview_uses_preview_timeout() -> None:
    adapter, client = adapter_with_backups(
        backup_data={"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}}
    )
    adapter.compare_recency("Hades")
    assert ("restore", ("Hades",), True, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) in client.calls


def test_get_conflict_metadata_preview_uses_preview_timeout() -> None:
    adapter, client = adapter_with_backups({"games": {}})
    adapter.get_conflict_metadata("Hades")
    assert ("backup", ("Hades",), True, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) in client.calls
