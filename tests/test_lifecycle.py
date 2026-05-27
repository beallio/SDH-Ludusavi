from __future__ import annotations

from unittest.mock import MagicMock
from sdh_ludusavi.lifecycle import GameLifecycleManager


def test_game_lifecycle_manager_init() -> None:
    svc = MagicMock()
    manager = GameLifecycleManager(svc)
    assert manager._service is svc


def test_game_lifecycle_delegates_to_service() -> None:
    svc = MagicMock()
    svc._sanitize_name.return_value = "Hades"
    svc._auto_sync_enabled = False
    svc._skip.return_value = {"status": "skipped"}

    manager = GameLifecycleManager(svc)
    res = manager.check_game_start("Hades")

    assert res["status"] == "skipped"
    svc._sanitize_name.assert_called_with("Hades")
    svc._skip.assert_called_with("start", "Hades", "auto_sync_disabled")
