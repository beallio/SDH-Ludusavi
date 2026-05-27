from __future__ import annotations

import logging
from typing import Any, cast

from .coordinator import OperationLockedError

LOGGER = logging.getLogger("sdh_ludusavi.service.lifecycle")


class GameLifecycleManager:
    """Manages game lifecycle events (start, exit, force backup/restore).

    Delegates coordination and logging to the main service and other sub-managers.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def check_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Check whether a game launch needs a restore without changing local saves."""
        game_name = self._service._sanitize_name(game_name)
        self._service.log(
            "info",
            f"check_game_start triggered for game='{game_name}', app_id='{app_id}'",
            "start",
            game_name,
        )
        if not self._service._auto_sync_enabled:
            return self._service._skip("start", game_name, "auto_sync_disabled")
        if self._service._coordinator.is_running:
            return self._service._skip("start", game_name, "operation_running")

        game = self._service._match_game(game_name, app_id=app_id)
        if game is None:
            return self._service._skip("start", game_name, "unmatched_game")
        if not game.has_backup:
            return self._service._skip("start", game.name, "no_backup")
        if game.error:
            return self._service._skip("start", game.name, "game_error")

        try:
            recency = self._service._run_locked(
                "start_check",
                game.name,
                lambda: self._service._gateway.get_adapter().compare_recency(game.name),
            )
        except OperationLockedError:
            return self._service._skip("start", game.name, "operation_running")

        if recency == "backup_newer":
            return {"status": "needed", "operation": "restore", "game": game.name}
        if recency == "local_current":
            return self._service._skip("start", game.name, "local_current")

        metadata = self._service._conflict_metadata(game.name)
        self._service._history.record_history(
            game.name, "start", "auto_start", "skipped", reason="ambiguous_recency"
        )
        return {
            "status": "conflict",
            "operation": "restore",
            "game": game.name,
            "reason": "ambiguous_recency",
            "localLabel": "Keep Local Save",
            "backupLabel": "Restore Backup Save",
            **metadata,
        }

    def resolve_game_start_conflict(
        self, game_name: str, app_id: str | None, resolution: str
    ) -> dict[str, object]:
        """Apply the user's choice for an ambiguous launch recency conflict."""
        if resolution not in ("keep_local", "restore_backup"):
            return self._service._skip(
                "start", self._service._sanitize_name(game_name), "invalid_resolution"
            )
        if not self._service._auto_sync_enabled:
            return self._service._skip("start", game_name, "auto_sync_disabled")

        game_name = self._service._sanitize_name(game_name)
        game = self._service._match_game(game_name, app_id=app_id)
        if game is None:
            return self._service._skip("start", game_name, "unmatched_game")
        if game.error:
            return self._service._skip("start", game.name, "game_error")

        if resolution == "keep_local":
            try:
                result = self._service._run_locked(
                    "backup",
                    game.name,
                    lambda: self._service._gateway.get_adapter().backup(game.name),
                )
                self._service._history.record_history(
                    game.name, "backup", "auto_start", "backed_up"
                )
            except Exception as exc:
                self._service._history.record_history(
                    game.name, "backup", "auto_start", "failed", message=str(exc)
                )
                raise
            self._service.log("info", f"Kept local save for {game.name}", "backup", game.name)
            return {"status": "backed_up", "game": game.name, "result": result}

        if not game.has_backup:
            return self._service._skip("start", game.name, "no_backup")
        try:
            result = self._service._run_locked(
                "restore",
                game.name,
                lambda: self._service._gateway.get_adapter().restore(game.name),
            )
            self._service._history.record_history(game.name, "restore", "auto_start", "restored")
        except Exception as exc:
            self._service._history.record_history(
                game.name, "restore", "auto_start", "failed", message=str(exc)
            )
            raise
        self._service.log("info", f"Restored backup save for {game.name}", "restore", game.name)
        return {"status": "restored", "game": game.name, "result": result}

    def restore_game_on_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Restore a game's backup during launch after a check reports it is needed."""
        game_name = self._service._sanitize_name(game_name)
        self._service.log(
            "info",
            f"restore_game_on_start triggered for game='{game_name}', app_id='{app_id}'",
            "restore",
            game_name,
        )
        if not self._service._auto_sync_enabled:
            return self._service._skip("start", game_name, "auto_sync_disabled")

        game = self._service._match_game(game_name, app_id=app_id)
        if game is None:
            return self._service._skip("start", game_name, "unmatched_game")
        if not game.has_backup:
            return self._service._skip("start", game.name, "no_backup")
        if game.error:
            return self._service._skip("start", game.name, "game_error")

        try:
            result = self._service._run_locked(
                "restore",
                game.name,
                lambda: self._service._gateway.get_adapter().restore(game.name),
            )
        except Exception as exc:
            self._service._history.record_history(
                game.name, "restore", "auto_start", "failed", message=str(exc)
            )
            raise
        self._service.log("info", f"Restored {game.name} before launch", "restore", game.name)
        self._service._history.record_history(game.name, "restore", "auto_start", "restored")
        return {"status": "restored", "game": game.name, "result": result}

    def handle_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Compatibility wrapper for the original one-call launch autosync flow."""
        result = self.check_game_start(game_name, app_id)
        if result.get("status") == "needed" and result.get("operation") == "restore":
            return self.restore_game_on_start(str(result["game"]), app_id)
        return result

    def check_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Check whether a game exit needs a backup without writing backup data."""
        game_name = self._service._sanitize_name(game_name)
        self._service.log(
            "info",
            f"check_game_exit triggered for game='{game_name}', app_id='{app_id}'",
            "exit",
            game_name,
        )
        if not self._service._auto_sync_enabled:
            return self._service._skip("exit", game_name, "auto_sync_disabled")
        if self._service._coordinator.is_running:
            return self._service._skip("exit", game_name, "operation_running")

        game = self._service._match_game(game_name, app_id=app_id)
        if game is None:
            return self._service._skip("exit", game_name, "unmatched_game")
        if game.error:
            return self._service._skip("exit", game.name, "game_error")

        try:
            preview = self._service._run_locked(
                "exit_check",
                game.name,
                lambda: self._service._gateway.get_adapter().backup(game.name, preview=True),
            )
            games_output = cast(dict[str, Any], preview.get("games", {}))

            if game.name not in games_output:
                return self._service._skip("exit", game.name, "not_in_preview")

            game_output = cast(dict[str, Any], games_output.get(game.name, {}))
            decision = game_output.get("decision")
            if decision in ("Ignored", "Cancelled"):
                return self._service._skip("exit", game.name, "not_processed")

            files = game_output.get("files", {})
            registry = game_output.get("registry", {})
            if not files and not registry:
                return self._service._skip("exit", game.name, "no_files_found")

            change = game_output.get("change")
            if change == "Same":
                return self._service._skip("exit", game.name, "local_current")
        except OperationLockedError:
            return self._service._skip("exit", game.name, "operation_running")
        except Exception as exc:
            self._service.log(
                "debug", f"Backup preview failed for {game.name}: {exc}", "exit", game.name
            )
            return self._service._skip("exit", game.name, "preview_failed")

        return {"status": "needed", "operation": "backup", "game": game.name}

    def backup_game_on_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Back up a game during exit after a check reports it is needed."""
        game_name = self._service._sanitize_name(game_name)
        self._service.log(
            "info",
            f"backup_game_on_exit triggered for game='{game_name}', app_id='{app_id}'",
            "backup",
            game_name,
        )
        if not self._service._auto_sync_enabled:
            return self._service._skip("exit", game_name, "auto_sync_disabled")

        game = self._service._match_game(game_name, app_id=app_id)
        if game is None:
            return self._service._skip("exit", game_name, "unmatched_game")
        if game.error:
            return self._service._skip("exit", game.name, "game_error")

        try:
            result = self._service._run_locked(
                "backup", game.name, lambda: self._service._gateway.get_adapter().backup(game.name)
            )
            self._service._history.record_history(game.name, "backup", "auto_exit", "backed_up")
        except Exception as exc:
            self._service._history.record_history(
                game.name, "backup", "auto_exit", "failed", message=str(exc)
            )
            raise

        try:
            self._service._refresh_statuses_unlocked()
        except Exception as exc:
            self._service.log(
                "warning", f"Post-backup status refresh failed: {exc}", "backup", game.name
            )

        self._service.log("info", f"Backed up {game.name} after exit", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def handle_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Compatibility wrapper for the original one-call exit autosync flow."""
        result = self.check_game_exit(game_name, app_id)
        if result.get("status") == "needed" and result.get("operation") == "backup":
            return self.backup_game_on_exit(str(result["game"]), app_id)
        return result

    def force_backup(self, game_name: str) -> dict[str, object]:
        """Trigger a manual backup for the specified game."""
        game_name = self._service._sanitize_name(game_name)
        game = self._service._match_game(game_name)
        if game is None:
            return self._service._skip("backup", game_name, "unmatched_game")

        try:
            result = self._service._run_locked(
                "backup", game.name, lambda: self._service._gateway.get_adapter().backup(game.name)
            )
            self._service._history.record_history(game.name, "backup", "manual_backup", "backed_up")
        except Exception as exc:
            self._service._history.record_history(
                game.name, "backup", "manual_backup", "failed", message=str(exc)
            )
            raise

        try:
            self._service._refresh_statuses_unlocked()
        except Exception as exc:
            self._service.log(
                "warning", f"Post-backup status refresh failed: {exc}", "backup", game.name
            )

        self._service.log("info", f"Backed up {game.name}", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_restore(self, game_name: str) -> dict[str, object]:
        """Trigger a manual restore for the specified game."""
        game_name = self._service._sanitize_name(game_name)
        game = self._service._match_game(game_name)
        if game is None:
            return self._service._skip("restore", game_name, "unmatched_game")
        if not game.has_backup:
            return self._service._skip("restore", game.name, "no_backup")

        try:
            result = self._service._run_locked(
                "restore",
                game.name,
                lambda: self._service._gateway.get_adapter().restore(game.name),
            )
        except Exception as exc:
            self._service._history.record_history(
                game.name, "restore", "manual_restore", "failed", message=str(exc)
            )
            raise
        self._service.log("info", f"Restored {game.name}", "restore", game.name)
        self._service._history.record_history(game.name, "restore", "manual_restore", "restored")
        return {"status": "restored", "game": game.name, "result": result}
