from __future__ import annotations

from unittest.mock import MagicMock
from sdh_ludusavi.lifecycle import GameLifecycleManager, LifecycleDependencies


def test_game_lifecycle_manager_init() -> None:
    deps = MagicMock()
    manager = GameLifecycleManager(deps)
    assert manager.dependencies is deps


def test_game_lifecycle_delegates_to_dependencies() -> None:
    registry = MagicMock()
    gateway = MagicMock()
    history = MagicMock()
    run_locked = MagicMock()
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
        is_game_sync_enabled=lambda _name: True,
        log=log,
        skip=skip,
        conflict_metadata=conflict_metadata,
    )

    manager = GameLifecycleManager(deps)
    res = manager.check_game_start("Hades")

    assert res["status"] == "skipped"
    is_auto_sync_enabled.assert_called_once()
    skip.assert_called_with("start", "Hades", "auto_sync_disabled")
