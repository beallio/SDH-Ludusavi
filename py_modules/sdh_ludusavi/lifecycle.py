from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal, cast

from .constants import RECENCY_TIMESTAMP_MARGIN_SECONDS
from .coordinator import OperationLockedError
from .gateway import LudusaviGateway
from .history import HistoryManager
from .registry import GameRegistry
from sdh_ludusavi.game_names import sanitize_game_name

LOGGER = logging.getLogger("sdh_ludusavi.service.lifecycle")


def _parse_iso_timestamp(ts: object) -> datetime | None:
    """Parse an ISO-8601 timestamp to aware UTC, returning None if unparseable.

    Naive timestamps are assumed to be UTC so that mixed naive/aware
    inputs can never raise during subtraction.
    """
    if not isinstance(ts, str):
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_direction(
    local_modified_at: object,
    backup_modified_at: object,
    margin_seconds: float,
) -> Literal["backup_newer", "not_newer", "unknown"]:
    """Decide restore direction from conflict-metadata timestamps.

    Returns "backup_newer" only when the backup timestamp exceeds the local
    timestamp by strictly more than margin_seconds. Missing or unparseable
    input yields "unknown".
    """
    local = _parse_iso_timestamp(local_modified_at)
    backup = _parse_iso_timestamp(backup_modified_at)
    if local is None or backup is None:
        return "unknown"
    if (backup - local).total_seconds() > margin_seconds:
        return "backup_newer"
    return "not_newer"


@dataclass(frozen=True)
class LifecycleDependencies:
    """Explicit collaborators needed by GameLifecycleManager."""

    registry: GameRegistry
    gateway: LudusaviGateway
    history: HistoryManager
    is_coordinator_running: Callable[[], bool]
    run_locked: Callable[..., Any]
    is_auto_sync_enabled: Callable[[], bool]
    log: Callable[..., None]
    skip: Callable[[str, str, str], dict[str, object]]
    conflict_metadata: Callable[[str], dict[str, object]]


class GameLifecycleManager:
    """Manages game lifecycle events (start, exit, force backup/restore).

    Delegates coordination, registry lookups, and logging to decoupled collaborators.
    """

    def __init__(self, dependencies: LifecycleDependencies) -> None:
        self.dependencies = dependencies

    @staticmethod
    def _conflict_response(
        game_name: str,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        """Build a standard conflict response for ambiguous recency."""
        return {
            "status": "conflict",
            "operation": "restore",
            "game": game_name,
            "reason": "ambiguous_recency",
            "localLabel": "Keep Local Save",
            "backupLabel": "Restore Backup Save",
            **metadata,
        }

    def _result_change(self, result: object, game_name: str) -> str | None:
        """Return the per-game ludusavi change value when available."""
        if not isinstance(result, dict):
            return None
        games = cast(dict[str, object], result).get("games")
        if not isinstance(games, dict):
            return None
        game_output = cast(dict[str, object], games).get(game_name)
        if not isinstance(game_output, dict):
            return None
        change = cast(dict[str, object], game_output).get("change")
        return change if isinstance(change, str) else None

    def _execute_operation(
        self,
        *,
        operation: str,
        trigger: str,
        game_name: str,
        adapter_call: Callable[[], Any],
        same_handling: bool,
        refresh: bool,
        record_order: Literal["before_log", "after_log"],
        success_status: str,
        success_log: str,
        same_log: str | None = None,
        result_extra: dict[str, object] | None = None,
        skip_locked_history: bool = False,
    ) -> dict[str, object]:
        try:
            result = self.dependencies.run_locked(operation, game_name, adapter_call)
            change = self._result_change(result, game_name) if same_handling else None
            is_same = same_handling and change == "Same"

            if record_order == "before_log":
                if is_same:
                    self.dependencies.history.record_history(
                        game_name, operation, trigger, "skipped", reason="local_current"
                    )
                else:
                    self.dependencies.history.record_history(
                        game_name, operation, trigger, success_status
                    )
        # Intentionally broad: record history and re-raise on adapter failure
        except Exception as exc:
            if skip_locked_history and isinstance(exc, OperationLockedError):
                raise
            self.dependencies.history.record_history(
                game_name, operation, trigger, "failed", message=str(exc)
            )
            raise

        if refresh:
            self.dependencies.registry.refresh_after_operation(game_name)

        if is_same:
            if same_log:
                self.dependencies.log("info", same_log, operation, game_name)
            resp = {
                "status": "skipped",
                "reason": "local_current",
                "game": game_name,
                "result": result,
            }
            if result_extra:
                resp.update(result_extra)
            return resp

        self.dependencies.log("info", success_log, operation, game_name)

        if record_order == "after_log":
            self.dependencies.history.record_history(game_name, operation, trigger, success_status)

        resp = {
            "status": success_status,
            "game": game_name,
            "result": result,
        }
        if result_extra:
            resp.update(result_extra)
        return resp

    def check_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Check whether a game launch needs a restore without changing local saves."""
        game_name = sanitize_game_name(game_name)
        self.dependencies.log(
            "info",
            f"check_game_start triggered for game='{game_name}', app_id='{app_id}'",
            "start",
            game_name,
        )
        if not self.dependencies.is_auto_sync_enabled():
            return self.dependencies.skip("start", game_name, "auto_sync_disabled")
        if self.dependencies.is_coordinator_running():
            return self.dependencies.skip("start", game_name, "operation_running")

        game = self.dependencies.registry.match_game(game_name, app_id=app_id)
        if game is None:
            return self.dependencies.skip("start", game_name, "unmatched_game")
        if not game.has_backup:
            return self.dependencies.skip("start", game.name, "no_backup")
        if game.error:
            return self.dependencies.skip("start", game.name, "game_error")

        try:
            recency = self.dependencies.run_locked(
                "start_check",
                game.name,
                lambda: self.dependencies.gateway.get_adapter().compare_recency(game.name),
            )
        except OperationLockedError:
            return self.dependencies.skip("start", game.name, "operation_running")

        if recency == "backup_newer":
            self.dependencies.log(
                "info",
                f"Restore needed for {game.name}: backup is newer than the local save",
                "start",
                game.name,
            )
            return {"status": "needed", "operation": "restore", "game": game.name}
        if recency == "local_current":
            return self.dependencies.skip("start", game.name, "local_current")

        metadata = self.dependencies.conflict_metadata(game.name)
        local_modified_at = metadata.get("localModifiedAt")
        backup_modified_at = metadata.get("backupModifiedAt")

        if recency == "backup_differs":
            direction = _timestamp_direction(
                local_modified_at,
                backup_modified_at,
                RECENCY_TIMESTAMP_MARGIN_SECONDS,
            )
            if direction == "backup_newer":
                self.dependencies.log(
                    "info",
                    f"Backup for {game.name} differs and is newer by timestamp; proceeding with restore "
                    f"(local={local_modified_at}, backup={backup_modified_at})",
                    "start",
                    game.name,
                )
                return {"status": "needed", "operation": "restore", "game": game.name}
            self.dependencies.log(
                "info",
                f"Backup for {game.name} differs but direction is {direction}; deferring to conflict resolution "
                f"(local={local_modified_at}, backup={backup_modified_at})",
                "start",
                game.name,
            )

        # Fall through to conflict for: ambiguous, backup_differs without
        # clear direction, or any other unknown value.
        self.dependencies.log(
            "info",
            f"Recency for {game.name} is {recency}; prompting user to resolve conflict "
            f"(local={local_modified_at}, backup={backup_modified_at})",
            "start",
            game.name,
        )
        self.dependencies.history.record_history(
            game.name, "start", "auto_start", "skipped", reason="ambiguous_recency"
        )
        return self._conflict_response(game.name, metadata)

    def resolve_game_start_conflict(
        self, game_name: str, app_id: str | None, resolution: str
    ) -> dict[str, object]:
        """Apply the user's choice for an ambiguous launch recency conflict."""
        if resolution not in ("keep_local", "restore_backup"):
            return self.dependencies.skip(
                "start", sanitize_game_name(game_name), "invalid_resolution"
            )
        if not self.dependencies.is_auto_sync_enabled():
            return self.dependencies.skip("start", game_name, "auto_sync_disabled")

        game_name = sanitize_game_name(game_name)
        game = self.dependencies.registry.match_game(game_name, app_id=app_id)
        if game is None:
            return self.dependencies.skip("start", game_name, "unmatched_game")
        if game.error:
            return self.dependencies.skip("start", game.name, "game_error")

        if resolution == "keep_local":
            return self._execute_operation(
                operation="backup",
                trigger="auto_start",
                game_name=game.name,
                adapter_call=lambda: self.dependencies.gateway.get_adapter().backup(game.name),
                same_handling=False,
                refresh=False,
                record_order="before_log",
                success_status="backed_up",
                success_log=f"Kept local save for {game.name}",
            )

        if not game.has_backup:
            return self.dependencies.skip("start", game.name, "no_backup")

        return self._execute_operation(
            operation="restore",
            trigger="auto_start",
            game_name=game.name,
            adapter_call=lambda: self.dependencies.gateway.get_adapter().restore(game.name),
            same_handling=False,
            refresh=False,
            record_order="before_log",
            success_status="restored",
            success_log=f"Restored backup save for {game.name}",
        )

    def restore_game_on_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Restore a game's backup during launch after a check reports it is needed."""
        game_name = sanitize_game_name(game_name)
        self.dependencies.log(
            "info",
            f"restore_game_on_start triggered for game='{game_name}', app_id='{app_id}'",
            "restore",
            game_name,
        )
        if not self.dependencies.is_auto_sync_enabled():
            return self.dependencies.skip("start", game_name, "auto_sync_disabled")

        game = self.dependencies.registry.match_game(game_name, app_id=app_id)
        if game is None:
            return self.dependencies.skip("start", game_name, "unmatched_game")
        if not game.has_backup:
            return self.dependencies.skip("start", game.name, "no_backup")
        if game.error:
            return self.dependencies.skip("start", game.name, "game_error")

        return self._execute_operation(
            operation="restore",
            trigger="auto_start",
            game_name=game.name,
            adapter_call=lambda: self.dependencies.gateway.get_adapter().restore(game.name),
            same_handling=False,
            refresh=False,
            record_order="after_log",
            success_status="restored",
            success_log=f"Restored {game.name} before launch",
        )

    def handle_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Compatibility wrapper for the original one-call launch autosync flow."""
        result = self.check_game_start(game_name, app_id)
        if result.get("status") == "needed" and result.get("operation") == "restore":
            return self.restore_game_on_start(str(result["game"]), app_id)
        return result

    def check_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Check whether a game exit needs a backup without writing backup data."""
        game_name = sanitize_game_name(game_name)
        self.dependencies.log(
            "info",
            f"check_game_exit triggered for game='{game_name}', app_id='{app_id}'",
            "exit",
            game_name,
        )
        if not self.dependencies.is_auto_sync_enabled():
            return self.dependencies.skip("exit", game_name, "auto_sync_disabled")
        if self.dependencies.is_coordinator_running():
            return self.dependencies.skip("exit", game_name, "operation_running")

        game = self.dependencies.registry.match_game(game_name, app_id=app_id)
        if game is None:
            return self.dependencies.skip("exit", game_name, "unmatched_game")
        if game.error:
            return self.dependencies.skip("exit", game.name, "game_error")

        try:
            preview = self.dependencies.run_locked(
                "exit_check",
                game.name,
                lambda: self.dependencies.gateway.get_adapter().backup(game.name, preview=True),
            )
            games_output = cast(dict[str, Any], preview.get("games", {}))

            if game.name not in games_output:
                return self.dependencies.skip("exit", game.name, "not_in_preview")

            game_output = cast(dict[str, Any], games_output.get(game.name, {}))
            decision = game_output.get("decision")
            files = game_output.get("files", {})
            registry = game_output.get("registry", {})
            change = game_output.get("change")
            self.dependencies.log(
                "info",
                f"Exit preview for {game.name}: decision={decision} change={change} "
                f"files={len(files)} registry={len(registry)}",
                "exit",
                game.name,
            )

            if decision in ("Ignored", "Cancelled"):
                return self.dependencies.skip("exit", game.name, "not_processed")
            if not files and not registry:
                return self.dependencies.skip("exit", game.name, "no_files_found")
            if change == "Same":
                return self.dependencies.skip("exit", game.name, "local_current")
        except OperationLockedError:
            return self.dependencies.skip("exit", game.name, "operation_running")
        # Intentionally broad: handle backup preview exceptions gracefully
        except Exception as exc:
            self.dependencies.log(
                "debug", f"Backup preview failed for {game.name}: {exc}", "exit", game.name
            )
            return self.dependencies.skip("exit", game.name, "preview_failed")

        return {"status": "needed", "operation": "backup", "game": game.name}

    def backup_game_on_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Back up a game during exit after a check reports it is needed."""
        game_name = sanitize_game_name(game_name)
        self.dependencies.log(
            "info",
            f"backup_game_on_exit triggered for game='{game_name}', app_id='{app_id}'",
            "backup",
            game_name,
        )
        if not self.dependencies.is_auto_sync_enabled():
            return self.dependencies.skip("exit", game_name, "auto_sync_disabled")

        game = self.dependencies.registry.match_game(game_name, app_id=app_id)
        if game is None:
            return self.dependencies.skip("exit", game_name, "unmatched_game")
        if game.error:
            return self.dependencies.skip("exit", game.name, "game_error")

        return self._execute_operation(
            operation="backup",
            trigger="auto_exit",
            game_name=game.name,
            adapter_call=lambda: self.dependencies.gateway.get_adapter().backup(game.name),
            same_handling=False,
            refresh=True,
            record_order="before_log",
            success_status="backed_up",
            success_log=f"Backed up {game.name} after exit",
        )

    def handle_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Compatibility wrapper for the original one-call exit autosync flow."""
        result = self.check_game_exit(game_name, app_id)
        if result.get("status") == "needed" and result.get("operation") == "backup":
            return self.backup_game_on_exit(str(result["game"]), app_id)
        return result

    def force_backup(self, game_name: str) -> dict[str, object]:
        """Trigger a manual backup for the specified game."""
        game_name = sanitize_game_name(game_name)
        game = self.dependencies.registry.match_game(game_name)
        if game is None:
            return self.dependencies.skip("backup", game_name, "unmatched_game")

        return self._execute_operation(
            operation="backup",
            trigger="manual_backup",
            game_name=game.name,
            adapter_call=lambda: self.dependencies.gateway.get_adapter().backup(game.name),
            same_handling=True,
            refresh=True,
            record_order="before_log",
            success_status="backed_up",
            success_log=f"Backed up {game.name}",
            same_log=f"Backup skipped for {game.name}: local save already current",
        )

    def force_restore(self, game_name: str) -> dict[str, object]:
        """Trigger a manual restore for the specified game."""
        game_name = sanitize_game_name(game_name)
        game = self.dependencies.registry.match_game(game_name)
        if game is None:
            return self.dependencies.skip("restore", game_name, "unmatched_game")
        if not game.has_backup:
            return self.dependencies.skip("restore", game.name, "no_backup")

        return self._execute_operation(
            operation="restore",
            trigger="manual_restore",
            game_name=game.name,
            adapter_call=lambda: self.dependencies.gateway.get_adapter().restore(game.name),
            same_handling=True,
            refresh=True,
            record_order="before_log",
            success_status="restored",
            success_log=f"Restored {game.name}",
            same_log=f"Restore skipped for {game.name}: local save already current",
        )

    def list_backups(self, game_name: str) -> dict[str, object]:
        game_name = sanitize_game_name(game_name)
        game = self.dependencies.registry.match_game(game_name)
        if not game:
            return self.dependencies.skip("backups_list", game_name, "unmatched_game")
        return self.dependencies.run_locked(
            "backups_list",
            game.name,
            lambda: self.dependencies.gateway.get_adapter().list_backups(game.name),
        )

    def restore_backup_version(self, game_name: str, backup_id: str) -> dict[str, object]:
        game_name = sanitize_game_name(game_name)
        game = self.dependencies.registry.match_game(game_name)
        if not game:
            return self.dependencies.skip("restore_backup_version", game_name, "unmatched_game")
        if not game.has_backup:
            return self.dependencies.skip("restore_backup_version", game.name, "no_backup")

        if not backup_id or "/" in backup_id or "\\" in backup_id or ".." in backup_id:
            raise ValueError(f"Invalid backup ID: {backup_id}")

        return self._execute_operation(
            operation="restore",
            trigger="manual_restore",
            game_name=game.name,
            adapter_call=lambda: self.dependencies.gateway.get_adapter().restore_backup(
                game.name, backup_id
            ),
            same_handling=True,
            refresh=True,
            record_order="before_log",
            success_status="restored",
            success_log=f"Restored {game.name} from backup {backup_id}",
            same_log=f"Restore skipped for {game.name} from backup {backup_id}: local save already matches backup",
            result_extra={"backup_id": backup_id},
            skip_locked_history=True,
        )
