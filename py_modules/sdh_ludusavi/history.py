from __future__ import annotations

from datetime import datetime
import threading
from typing import Any, Callable


class HistoryManager:
    """Manages the validation, sanitization, updates, and structures of

    operation history records for individual games.
    """

    def __init__(
        self, service: Any, initial_history: dict[str, Any], save_callback: Callable[[], None]
    ) -> None:
        self._service = service
        self._save_callback = save_callback
        self._game_history: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

        # Initialize and validate input history
        if isinstance(initial_history, dict):
            for game_name, history in initial_history.items():
                if not isinstance(history, dict):
                    continue
                validated_history = {}
                for field in ("last_backup", "last_restore", "last_skip", "last_failure"):
                    val = history.get(field)
                    validated_history[field] = self._coerce_history_entry(val)

                self._update_last_operation(validated_history)
                self._game_history[str(game_name)] = validated_history

    def get_history(self) -> dict[str, dict[str, Any]]:
        """Return the complete validated game operation history."""
        # Entries are replaced wholesale (never mutated in place), so copying
        # the outer and per-game dicts is sufficient for a consistent snapshot.
        with self._lock:
            return {game: dict(history) for game, history in self._game_history.items()}

    def record_history(
        self,
        game_name: str,
        operation: str,
        trigger: str,
        status: str,
        reason: str | None = None,
        message: str | None = None,
    ) -> None:
        """Record a history entry for a specific game and trigger persistence."""
        entry = self._coerce_history_entry(
            {
                "operation": operation,
                "trigger": trigger,
                "status": status,
                "reason": reason,
                "message": message,
                "timestamp": datetime.now().isoformat(timespec="microseconds"),
            }
        )
        if entry is None:
            return

        with self._lock:
            if game_name not in self._game_history:
                self._game_history[game_name] = {
                    "last_backup": None,
                    "last_restore": None,
                    "last_skip": None,
                    "last_failure": None,
                    "last_operation": None,
                }

            history = self._game_history[game_name]
            if status == "backed_up":
                field = "last_backup"
            elif status == "restored":
                field = "last_restore"
            elif status == "failed":
                field = "last_failure"
            else:
                field = "last_skip"

            history[field] = entry
            self._update_last_operation(history)

        # Lock-ordering note: _save_callback (service._save_state) acquires the
        # service _state_lock and re-enters get_history(). Invoke it only after
        # releasing self._lock so the lock order is never history -> service,
        # which would deadlock against _save_state's service -> history order.
        self._save_callback()

    def _coerce_history_entry(self, entry: Any) -> dict[str, Any] | None:
        """Validate and sanitize a history entry dictionary."""
        if not isinstance(entry, dict):
            return None

        schema = {
            "operation": str,
            "trigger": str,
            "status": str,
            "timestamp": str,
        }

        optional = {
            "reason": (str, type(None)),
            "message": (str, type(None)),
        }

        coerced = {}
        for field, expected_type in schema.items():
            val = entry.get(field)
            if not isinstance(val, expected_type):
                return None
            coerced[field] = val

        if coerced["status"] not in ("backed_up", "restored", "skipped", "failed"):
            return None
        if coerced["operation"] not in ("backup", "restore", "start", "exit"):
            return None
        if coerced["trigger"] not in (
            "manual_backup",
            "manual_restore",
            "auto_start",
            "auto_exit",
        ):
            return None

        for field, expected_types in optional.items():
            val = entry.get(field)
            if isinstance(val, expected_types):
                coerced[field] = val
            else:
                coerced[field] = None

        return coerced

    def _update_last_operation(self, history: dict[str, Any]) -> None:
        """Compute the last_operation field based on the newest timestamp."""
        entries = [
            history.get("last_backup"),
            history.get("last_restore"),
            history.get("last_skip"),
            history.get("last_failure"),
        ]
        valid_entries = [e for e in entries if isinstance(e, dict) and e.get("timestamp")]
        if not valid_entries:
            history["last_operation"] = None
            return

        valid_entries.sort(key=lambda x: str(x["timestamp"]), reverse=True)
        history["last_operation"] = valid_entries[0]
