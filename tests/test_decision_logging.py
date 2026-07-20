"""Diagnostic logging for auto-sync decision points.

These tests pin down the log lines that explain *why* the plugin chose to
restore, back up, skip, or prompt — the questions users hit when reading logs.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pyludusavi import LudusaviError

from sdh_ludusavi.lifecycle import GameLifecycleManager, LifecycleDependencies
from sdh_ludusavi.ludusavi import PyludusaviAdapter

ADAPTER_LOGGER = "sdh_ludusavi.ludusavi"


class _FakeClient:
    def __init__(
        self,
        backups: dict[str, object],
        restore_data: dict[str, object] | None = None,
        restore_exc: Exception | None = None,
    ) -> None:
        self._backups = backups
        self._restore_data = restore_data or {}
        self._restore_exc = restore_exc

    def backups_list(self, games: list[str] | None = None) -> SimpleNamespace:
        return SimpleNamespace(data=self._backups)

    def restore(
        self,
        games: list[str] | None = None,
        preview: bool = False,
        timeout: float | None = None,
    ) -> SimpleNamespace:
        if self._restore_exc is not None:
            raise self._restore_exc
        return SimpleNamespace(data=self._restore_data)


def _adapter(
    backups: dict[str, object],
    restore_data: dict[str, object] | None = None,
    restore_exc: Exception | None = None,
) -> PyludusaviAdapter:
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = _FakeClient(backups, restore_data, restore_exc)  # type: ignore[assignment]
    return adapter


def _backups_with_entries() -> dict[str, object]:
    return {"games": {"Hades": {"backups": [{"when": "2026-06-01T00:00:00Z"}]}}}


def _restore_preview(change: str) -> dict[str, object]:
    return {"games": {"Hades": {"change": change}}}


def test_compare_recency_logs_no_backup_verdict(caplog: pytest.LogCaptureFixture) -> None:
    adapter = _adapter({"games": {"Hades": {"backups": []}}})
    with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
        verdict = adapter.compare_recency("Hades")
    assert verdict == "no_backup"
    messages = " | ".join(record.getMessage() for record in caplog.records)
    assert "Recency check for Hades" in messages
    assert "no_backup" in messages


@pytest.mark.parametrize(
    ("change", "verdict"),
    [
        ("Same", "local_current"),
        ("New", "backup_newer"),
        ("Different", "backup_differs"),
    ],
)
def test_compare_recency_logs_preview_change_and_verdict(
    caplog: pytest.LogCaptureFixture, change: str, verdict: str
) -> None:
    adapter = _adapter(_backups_with_entries(), restore_data=_restore_preview(change))
    with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
        assert adapter.compare_recency("Hades") == verdict
    messages = " | ".join(record.getMessage() for record in caplog.records)
    assert "Recency check for Hades" in messages
    assert f"change={change}" in messages
    assert verdict in messages


def test_compare_recency_logs_ambiguous_when_preview_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter(_backups_with_entries(), restore_exc=LudusaviError("boom"))
    with caplog.at_level(logging.INFO, logger=ADAPTER_LOGGER):
        assert adapter.compare_recency("Hades") == "ambiguous"
    messages = " | ".join(
        record.getMessage() for record in caplog.records if record.levelno >= logging.INFO
    )
    assert "Recency check for Hades" in messages
    assert "ambiguous" in messages


def _make_manager(
    recency: str = "ambiguous",
    exit_preview: dict[str, object] | None = None,
) -> GameLifecycleManager:
    registry = MagicMock()
    game = MagicMock()
    game.name = "Hades"
    game.has_backup = True
    game.error = None
    registry.match_game.return_value = game

    gateway = MagicMock()
    adapter = MagicMock()
    adapter.compare_recency.return_value = recency
    adapter.backup.return_value = exit_preview or {"games": {}}
    gateway.get_adapter.return_value = adapter

    deps = LifecycleDependencies(
        registry=registry,
        gateway=gateway,
        history=MagicMock(),
        is_coordinator_running=MagicMock(return_value=False),
        run_locked=MagicMock(side_effect=lambda _lock, _name, fn: fn()),
        is_auto_sync_enabled=MagicMock(return_value=True),
        is_game_sync_enabled=lambda _name: True,
        log=MagicMock(),
        skip=MagicMock(return_value={"status": "skipped"}),
        conflict_metadata=MagicMock(
            return_value={
                "localModifiedAt": "2026-06-01T00:00:00+00:00",
                "backupModifiedAt": "2026-06-01T00:01:00+00:00",
                "backupPath": "/backup/Hades",
            }
        ),
    )
    return GameLifecycleManager(deps)


def _logged(manager: GameLifecycleManager) -> str:
    log = manager.dependencies.log
    assert isinstance(log, MagicMock)
    return " | ".join(str(call) for call in log.call_args_list)


def test_check_game_start_logs_restore_needed_decision() -> None:
    manager = _make_manager(recency="backup_newer")
    result = manager.check_game_start("Hades")
    assert result["status"] == "needed"
    logged = _logged(manager)
    assert "Restore needed for Hades" in logged


def test_check_game_start_logs_conflict_prompt_with_timestamps() -> None:
    manager = _make_manager(recency="ambiguous")
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    logged = _logged(manager)
    assert "prompting user to resolve conflict" in logged
    assert "2026-06-01T00:00:00+00:00" in logged
    assert "2026-06-01T00:01:00+00:00" in logged


def test_check_game_exit_logs_preview_summary() -> None:
    preview = {
        "games": {
            "Hades": {
                "decision": "Processed",
                "change": "Different",
                "files": {"/saves/a": {}, "/saves/b": {}},
                "registry": {},
            }
        }
    }
    manager = _make_manager(exit_preview=preview)
    result = manager.check_game_exit("Hades")
    assert result == {"status": "needed", "operation": "backup", "game": "Hades"}
    logged = _logged(manager)
    assert "Exit preview for Hades" in logged
    assert "decision=Processed" in logged
    assert "change=Different" in logged
    assert "files=2" in logged
    assert "registry=0" in logged
