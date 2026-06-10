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
            return {"status": "needed", "operation": "restore", "game": game.name}
        if recency == "local_current":
            return self.dependencies.skip("start", game.name, "local_current")

        metadata = self.dependencies.conflict_metadata(game.name)

        if recency == "backup_differs":
            direction = _timestamp_direction(
                metadata.get("localModifiedAt"),
                metadata.get("backupModifiedAt"),
                RECENCY_TIMESTAMP_MARGIN_SECONDS,
            )
            if direction == "backup_newer":
                self.dependencies.log(
                    "info",
                    f"Backup for {game.name} differs and is newer by timestamp; proceeding with restore",
                    "start",
                    game.name,
                )
                return {"status": "needed", "operation": "restore", "game": game.name}
            self.dependencies.log(
                "info",
                f"Backup for {game.name} differs but direction is {direction}; deferring to conflict resolution",
                "start",
                game.name,
            )

        # Fall through to conflict for: ambiguous, backup_differs without
        # clear direction, or any other unknown value.
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
            try:
                result = self.dependencies.run_locked(
                    "backup",
                    game.name,
                    lambda: self.dependencies.gateway.get_adapter().backup(game.name),
                )
                self.dependencies.history.record_history(
                    game.name, "backup", "auto_start", "backed_up"
                )
            # Intentionally broad: record history and re-raise on backup failure
            except Exception as exc:
                self.dependencies.history.record_history(
                    game.name, "backup", "auto_start", "failed", message=str(exc)
                )
                raise
            self.dependencies.log("info", f"Kept local save for {game.name}", "backup", game.name)
            return {"status": "backed_up", "game": game.name, "result": result}

        if not game.has_backup:
            return self.dependencies.skip("start", game.name, "no_backup")
        try:
            result = self.dependencies.run_locked(
                "restore",
                game.name,
                lambda: self.dependencies.gateway.get_adapter().restore(game.name),
            )
            self.dependencies.history.record_history(game.name, "restore", "auto_start", "restored")
        # Intentionally broad: record history and re-raise on restore failure
        except Exception as exc:
            self.dependencies.history.record_history(
                game.name, "restore", "auto_start", "failed", message=str(exc)
            )
            raise
        self.dependencies.log("info", f"Restored backup save for {game.name}", "restore", game.name)
        return {"status": "restored", "game": game.name, "result": result}

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

        try:
            result = self.dependencies.run_locked(
                "restore",
                game.name,
                lambda: self.dependencies.gateway.get_adapter().restore(game.name),
            )
        # Intentionally broad: record history and re-raise on launch restore failure
        except Exception as exc:
            self.dependencies.history.record_history(
                game.name, "restore", "auto_start", "failed", message=str(exc)
            )
            raise
        self.dependencies.log("info", f"Restored {game.name} before launch", "restore", game.name)
        self.dependencies.history.record_history(game.name, "restore", "auto_start", "restored")
        return {"status": "restored", "game": game.name, "result": result}

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
            if decision in ("Ignored", "Cancelled"):
                return self.dependencies.skip("exit", game.name, "not_processed")

            files = game_output.get("files", {})
            registry = game_output.get("registry", {})
            if not files and not registry:
                return self.dependencies.skip("exit", game.name, "no_files_found")

            change = game_output.get("change")
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

        try:
            result = self.dependencies.run_locked(
                "backup",
                game.name,
                lambda: self.dependencies.gateway.get_adapter().backup(game.name),
            )
            self.dependencies.history.record_history(game.name, "backup", "auto_exit", "backed_up")
        # Intentionally broad: record history and re-raise on exit backup failure
        except Exception as exc:
            self.dependencies.history.record_history(
                game.name, "backup", "auto_exit", "failed", message=str(exc)
            )
            raise

        self.dependencies.registry.refresh_after_operation(game.name)
        self.dependencies.log("info", f"Backed up {game.name} after exit", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

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

        try:
            result = self.dependencies.run_locked(
                "backup",
                game.name,
                lambda: self.dependencies.gateway.get_adapter().backup(game.name),
            )
            self.dependencies.history.record_history(
                game.name, "backup", "manual_backup", "backed_up"
            )
        # Intentionally broad: record history and re-raise on manual backup failure
        except Exception as exc:
            self.dependencies.history.record_history(
                game.name, "backup", "manual_backup", "failed", message=str(exc)
            )
            raise

        self.dependencies.registry.refresh_after_operation(game.name)
        self.dependencies.log("info", f"Backed up {game.name}", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_restore(self, game_name: str) -> dict[str, object]:
        """Trigger a manual restore for the specified game."""
        game_name = sanitize_game_name(game_name)
        game = self.dependencies.registry.match_game(game_name)
        if game is None:
            return self.dependencies.skip("restore", game_name, "unmatched_game")
        if not game.has_backup:
            return self.dependencies.skip("restore", game.name, "no_backup")

        try:
            result = self.dependencies.run_locked(
                "restore",
                game.name,
                lambda: self.dependencies.gateway.get_adapter().restore(game.name),
            )
        # Intentionally broad: record history and re-raise on manual restore failure
        except Exception as exc:
            self.dependencies.history.record_history(
                game.name, "restore", "manual_restore", "failed", message=str(exc)
            )
            raise
        self.dependencies.log("info", f"Restored {game.name}", "restore", game.name)
        self.dependencies.history.record_history(game.name, "restore", "manual_restore", "restored")
        self.dependencies.registry.refresh_after_operation(game.name)
        return {"status": "restored", "game": game.name, "result": result}
