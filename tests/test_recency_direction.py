from __future__ import annotations

from unittest.mock import MagicMock

from sdh_ludusavi.lifecycle import GameLifecycleManager, LifecycleDependencies


def _make_manager(
    recency: str = "backup_differs",
    local_modified_at: str | None = "2026-06-01T00:00:00+00:00",
    backup_modified_at: str | None = "2026-06-01T02:05:00+00:00",
    backup_path: str = "/backup/Hades",
    has_backup: bool = True,
    auto_sync: bool = True,
    game_error: str | None = None,
) -> GameLifecycleManager:
    """Build a GameLifecycleManager with mocked dependencies for direction testing."""
    registry = MagicMock()
    game = MagicMock()
    game.name = "Hades"
    game.has_backup = has_backup
    game.error = game_error
    registry.match_game.return_value = game

    gateway = MagicMock()
    adapter = MagicMock()
    adapter.compare_recency.return_value = recency
    adapter.get_conflict_metadata.return_value = {}
    gateway.get_adapter.return_value = adapter

    history = MagicMock()
    is_coordinator_running = MagicMock(return_value=False)
    is_auto_sync_enabled = MagicMock(return_value=auto_sync)
    log = MagicMock()
    skip = MagicMock(return_value={"status": "skipped"})

    conflict_metadata_fn = MagicMock(
        return_value={
            "localModifiedAt": local_modified_at,
            "backupModifiedAt": backup_modified_at,
            "backupPath": backup_path,
        }
    )

    run_locked = MagicMock(side_effect=lambda _lock, _name, fn: fn())

    deps = LifecycleDependencies(
        registry=registry,
        gateway=gateway,
        history=history,
        is_coordinator_running=is_coordinator_running,
        run_locked=run_locked,
        is_auto_sync_enabled=is_auto_sync_enabled,
        log=log,
        skip=skip,
        conflict_metadata=conflict_metadata_fn,
    )

    return GameLifecycleManager(deps)


def test_backup_differs_auto_restore_when_backup_clearly_newer() -> None:
    """Edge case #3: backup - local > 120s margin -> auto-restore."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T00:00:00+00:00",
        backup_modified_at="2026-06-01T02:05:00+00:00",
    )
    result = manager.check_game_start("Hades")
    assert result == {"status": "needed", "operation": "restore", "game": "Hades"}


def test_backup_differs_conflict_when_local_newer() -> None:
    """Edge case #4: local >= backup -> conflict modal."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T02:10:00+00:00",
        backup_modified_at="2026-06-01T02:05:00+00:00",
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"
    assert result["game"] == "Hades"


def test_backup_differs_conflict_when_within_margin() -> None:
    """Edge case #5: |Δ| <= 120s -> conflict modal."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T02:04:30+00:00",
        backup_modified_at="2026-06-01T02:05:00+00:00",
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"


def test_backup_differs_conflict_when_local_mtime_missing() -> None:
    """Edge case #6: localModifiedAt is None -> conflict modal."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at=None,
        backup_modified_at="2026-06-01T02:05:00+00:00",
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"


def test_backup_differs_conflict_when_backup_mtime_missing() -> None:
    """Edge case #6 variant: backupModifiedAt is None -> conflict modal."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T00:00:00+00:00",
        backup_modified_at=None,
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"


def test_backup_differs_conflict_when_timestamp_corrupt() -> None:
    """Edge case #7: unparseable timestamp -> conflict modal."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="not-a-timestamp",
        backup_modified_at="also-not-a-timestamp",
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"


def test_backup_newer_still_auto_restores() -> None:
    """Edge case #1: backup_newer from 'New' change -> auto-restore (unchanged)."""
    manager = _make_manager(recency="backup_newer")
    result = manager.check_game_start("Hades")
    assert result == {"status": "needed", "operation": "restore", "game": "Hades"}


def test_ambiguous_recency_still_shows_conflict() -> None:
    """Edge case #8: ambiguous -> conflict modal (unchanged)."""
    manager = _make_manager(recency="ambiguous")
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"


def test_conflict_payload_includes_metadata() -> None:
    """Verify the conflict response includes metadata keys for the modal."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T02:10:00+00:00",
        backup_modified_at="2026-06-01T02:05:00+00:00",
        backup_path="/backup/Hades",
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert "localModifiedAt" in result
    assert "backupModifiedAt" in result
    assert "backupPath" in result
    assert "localLabel" in result
    assert "backupLabel" in result


def test_backup_differs_conflict_when_timestamps_mix_naive_and_aware() -> None:
    """A naive local timestamp paired with an aware backup timestamp must not
    raise; it must resolve safely (normalized comparison, not a crash)."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T02:10:00",  # naive
        backup_modified_at="2026-06-01T02:05:00+00:00",  # aware
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"
