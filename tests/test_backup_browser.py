from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from unittest.mock import MagicMock
from typing import Any

import pytest

from sdh_ludusavi.lifecycle import GameLifecycleManager, LifecycleDependencies
from sdh_ludusavi.ludusavi import _backup_disk_stats
from tests.test_ludusavi import adapter_with_backups
from tests.test_main import fake_decky_module, import_main
from tests.test_main_rpc import MockService


# 1. Adapter list_backups
def test_adapter_list_backups_parses_and_sorts_backups(tmp_path: Path) -> None:
    backup_path = tmp_path / "backup_dir"
    backup_path.mkdir()
    (backup_path / "1").mkdir()
    (backup_path / "2").mkdir()

    adapter, client = adapter_with_backups(
        backup_data={
            "games": {
                "Hades": {
                    "backupPath": str(backup_path),
                    "backups": [
                        {
                            "name": "1",
                            "when": "2026-05-10T00:00:00Z",
                            "locked": True,
                            "os": "linux",
                        },
                        {
                            "name": "2",
                            "when": "2026-06-01T12:00:00Z",
                            "comment": "new",
                            "os": "windows",
                        },
                    ],
                }
            }
        }
    )
    res = adapter.list_backups("Hades")
    assert res["game"] == "Hades"
    assert res["backup_path"] == str(backup_path)
    # Sorts newest-first (2026-06-01 > 2026-05-10)
    assert len(res["backups"]) == 2
    assert res["backups"][0]["id"] == "2"
    assert res["backups"][0]["when"] == "2026-06-01T12:00:00Z"
    assert res["backups"][0]["comment"] == "new"
    assert res["backups"][0]["locked"] is False
    assert res["backups"][0]["os"] == "windows"

    assert res["backups"][1]["id"] == "1"
    assert res["backups"][1]["when"] == "2026-05-10T00:00:00Z"
    assert res["backups"][1]["locked"] is True
    assert res["backups"][1]["comment"] is None


def test_adapter_list_backups_missing_game() -> None:
    adapter, client = adapter_with_backups(backup_data={"games": {}})
    res = adapter.list_backups("Hades")
    assert res == {"game": "Hades", "backup_path": None, "total_size_bytes": None, "backups": []}


# 2. _backup_disk_stats
def test_backup_disk_stats_directory(tmp_path: Path) -> None:
    snap = tmp_path / "snap1"
    snap.mkdir()
    (snap / "f1.txt").write_text("a", encoding="utf-8")
    (snap / "f2.txt").write_text("bc", encoding="utf-8")
    size, count = _backup_disk_stats(str(tmp_path), "snap1")
    assert size == 3
    assert count == 2


def test_backup_disk_stats_zip(tmp_path: Path) -> None:
    snap_zip = tmp_path / "snap1.zip"
    with zipfile.ZipFile(snap_zip, "w") as z:
        z.writestr("f1.txt", b"a")
        z.writestr("f2.txt", b"bc")
    size, count = _backup_disk_stats(str(tmp_path), "snap1.zip")
    assert count == 2
    assert size == snap_zip.stat().st_size


def test_backup_disk_stats_zip_fallback(tmp_path: Path) -> None:
    snap_zip = tmp_path / "snap1.zip"
    with zipfile.ZipFile(snap_zip, "w") as z:
        z.writestr("f1.txt", b"a")
        z.writestr("f2.txt", b"bc")
    # If the API says 'snap1' but it's a zip file
    size, count = _backup_disk_stats(str(tmp_path), "snap1")
    assert count == 2
    assert size == snap_zip.stat().st_size


def test_backup_disk_stats_simple_layout(tmp_path: Path) -> None:
    # backup_name == "."
    (tmp_path / "f1.txt").write_text("a", encoding="utf-8")
    (tmp_path / "f2.txt").write_text("bc", encoding="utf-8")
    (tmp_path / "mapping.yaml").write_text("ignore", encoding="utf-8")
    (tmp_path / "backup-123").mkdir()
    size, count = _backup_disk_stats(str(tmp_path), ".")
    assert size == 3
    assert count == 2


def test_backup_disk_stats_nonexistent(tmp_path: Path) -> None:
    size, count = _backup_disk_stats(str(tmp_path), "nope")
    assert size is None
    assert count is None


# 3. Adapter restore_backup
def test_adapter_restore_backup_calls_client() -> None:
    adapter, client = adapter_with_backups({}, restore_data={"games": {"Hades": {"success": True}}})
    res = adapter.restore_backup("Hades", "backup_123")
    assert res == {"games": {"Hades": {"success": True}}}
    assert client.requested_games == ["Hades"]


# 4. Lifecycle restore_backup_version
def get_deps():
    registry = MagicMock()
    gateway = MagicMock()
    history = MagicMock()
    # Mock run_locked to execute immediately
    run_locked = MagicMock(side_effect=lambda op, game, fn: fn())
    is_auto_sync_enabled = MagicMock(return_value=False)
    is_coordinator_running = MagicMock(return_value=False)
    log = MagicMock()
    skip = MagicMock(return_value={"status": "skipped"})
    conflict_metadata = MagicMock()

    deps = LifecycleDependencies(
        registry=registry,
        gateway=gateway,
        history=history,
        is_coordinator_running=is_coordinator_running,
        run_locked=run_locked,
        is_auto_sync_enabled=is_auto_sync_enabled,
        log=log,
        skip=skip,
        conflict_metadata=conflict_metadata,
    )
    return deps


def test_lifecycle_restore_backup_version_unmatched_game() -> None:
    deps = get_deps()
    deps.registry.match_game.return_value = None
    manager = GameLifecycleManager(deps)
    res = manager.restore_backup_version("Hades", "123")
    assert res == {"status": "skipped"}
    deps.skip.assert_called_with("restore_backup_version", "Hades", "unmatched_game")


def test_lifecycle_restore_backup_version_no_backup() -> None:
    deps = get_deps()
    game = MagicMock()
    game.name = "Hades"
    game.has_backup = False
    deps.registry.match_game.return_value = game
    manager = GameLifecycleManager(deps)
    res = manager.restore_backup_version("Hades", "123")
    assert res == {"status": "skipped"}
    deps.skip.assert_called_with("restore_backup_version", "Hades", "no_backup")


def test_lifecycle_restore_backup_version_invalid_id() -> None:
    deps = get_deps()
    game = MagicMock()
    game.name = "Hades"
    game.has_backup = True
    deps.registry.match_game.return_value = game
    manager = GameLifecycleManager(deps)

    with pytest.raises(ValueError):
        manager.restore_backup_version("Hades", "")

    with pytest.raises(ValueError):
        manager.restore_backup_version("Hades", "../foo")


def test_lifecycle_restore_backup_version_success() -> None:
    deps = get_deps()
    game = MagicMock()
    game.name = "Hades"
    game.has_backup = True
    deps.registry.match_game.return_value = game

    adapter = MagicMock()
    adapter.restore_backup.return_value = {"success": True}
    deps.gateway.get_adapter.return_value = adapter

    manager = GameLifecycleManager(deps)
    res = manager.restore_backup_version("Hades", "123")

    assert res == {
        "status": "restored",
        "game": "Hades",
        "backup_id": "123",
        "result": {"success": True},
    }
    deps.history.record_history.assert_called_with("Hades", "point_in_time_restore", "restored")
    deps.registry.refresh_after_operation.assert_called_with("Hades")


def test_lifecycle_restore_backup_version_failure() -> None:
    deps = get_deps()
    game = MagicMock()
    game.name = "Hades"
    game.has_backup = True
    deps.registry.match_game.return_value = game

    adapter = MagicMock()
    adapter.restore_backup.side_effect = Exception("failed")
    deps.gateway.get_adapter.return_value = adapter

    manager = GameLifecycleManager(deps)
    with pytest.raises(Exception):
        manager.restore_backup_version("Hades", "123")

    deps.history.record_history.assert_called_with(
        "Hades", "restore", "point_in_time_restore", "failed", message="failed"
    )


# 5. Lifecycle list_backups
def test_lifecycle_list_backups() -> None:
    deps = get_deps()
    game = MagicMock()
    game.name = "Hades"
    deps.registry.match_game.return_value = game

    adapter = MagicMock()
    adapter.list_backups.return_value = {"game": "Hades"}
    deps.gateway.get_adapter.return_value = adapter

    manager = GameLifecycleManager(deps)
    res = manager.list_backups("Hades")

    assert res == {"game": "Hades"}
    deps.history.record_history.assert_not_called()


# 6. RPC endpoints
def test_plugin_list_backups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    class MyMockService(MockService):
        def list_backups(self, game_name):
            return {"game": game_name}

    mock_service = MyMockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    res = asyncio.run(plugin.list_backups("Hades"))
    assert res["game"] == "Hades"


def test_plugin_restore_backup_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    class MyMockService(MockService):
        def restore_backup_version(self, game_name, backup_id):
            return {"status": "restored", "backup_id": backup_id}

    mock_service = MyMockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    res = asyncio.run(plugin.restore_backup_version("Hades", "123"))
    assert res["status"] == "restored"
    assert res["backup_id"] == "123"
