from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from ._version import resolve_version

LOGGER = logging.getLogger(__name__)


class OperationLockedError(RuntimeError):
    """Raised when a global Ludusavi operation is already running."""


class LudusaviAdapter(Protocol):
    def refresh_statuses(self) -> list[dict[str, object]]: ...

    def compare_recency(self, game_name: str) -> str: ...

    def backup(self, game_name: str) -> dict[str, object]: ...

    def restore(self, game_name: str) -> dict[str, object]: ...

    def get_versions(self) -> dict[str, str]: ...


@dataclass
class GameStatus:
    name: str
    configured: bool
    has_backup: bool
    needs_first_backup: bool
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.has_backup:
            return "has_backup"
        if self.needs_first_backup:
            return "needs_first_backup"
        return "configured" if self.configured else "error"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status
        return data


@dataclass
class OperationState:
    is_running: bool = False
    name: str | None = None
    game_name: str | None = None
    last_result: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class LogEntry:
    level: str
    message: str
    operation: str | None = None
    game_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SDHLudusaviService:
    def __init__(
        self,
        adapter: LudusaviAdapter | None = None,
        state_path: Path | None = None,
        log_limit: int = 50,
    ) -> None:
        if adapter is None:
            from .ludusavi import PyludusaviAdapter

            adapter = PyludusaviAdapter()

        self._adapter = adapter
        self._state_path = state_path or Path("/tmp/sdh_ludusavi/state.json")
        self._auto_sync_enabled = False
        self._games: dict[str, GameStatus] = {}
        self._operation = OperationState()
        self._operation_lock = threading.Lock()
        self._logs: deque[LogEntry] = deque(maxlen=log_limit)
        self._load_state()

    def get_settings(self) -> dict[str, bool]:
        return {"auto_sync_enabled": self._auto_sync_enabled}

    def set_auto_sync_enabled(self, enabled: bool) -> dict[str, bool]:
        self._auto_sync_enabled = bool(enabled)
        self._save_state()
        self._log("info", f"Automatic sync {'enabled' if enabled else 'disabled'}")
        return self.get_settings()

    def refresh_games(self) -> dict[str, object]:
        try:
            games = self._run_locked("refresh", None, self._refresh_statuses_unlocked)
        except (
            Exception
        ) as exc:  # pragma: no cover - concrete exception types come from pyludusavi.
            message = str(exc)
            self._operation.last_error = message
            self._log("error", message, operation="refresh")
            return {"games": self._cached_games(), "dependency_error": message}

        return {"games": [game.to_dict() for game in games], "dependency_error": None}

    def handle_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        del app_id
        if not self._auto_sync_enabled:
            return self._skip("start", game_name, "auto_sync_disabled")
        if self._operation.is_running:
            return self._skip("start", game_name, "operation_running")

        game = self._match_game(game_name)
        if game is None:
            return self._skip("start", game_name, "unmatched_game")
        if not game.has_backup:
            return self._skip("start", game.name, "no_backup")

        recency = self._adapter.compare_recency(game.name)
        if recency == "backup_newer":
            result = self._run_locked(
                "restore",
                game.name,
                lambda: self._adapter.restore(game.name),
            )
            self._log("info", f"Restored {game.name} before launch", "restore", game.name)
            return {"status": "restored", "game": game.name, "result": result}
        if recency == "local_current":
            return self._skip("start", game.name, "local_current")
        return self._skip("start", game.name, "ambiguous_recency")

    def handle_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        del app_id
        if not self._auto_sync_enabled:
            return self._skip("exit", game_name, "auto_sync_disabled")
        if self._operation.is_running:
            return self._skip("exit", game_name, "operation_running")

        game = self._match_game(game_name)
        if game is None:
            return self._skip("exit", game_name, "unmatched_game")

        result = self._run_locked("backup", game.name, lambda: self._adapter.backup(game.name))
        self._refresh_statuses_unlocked()
        self._log("info", f"Backed up {game.name} after exit", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_backup(self, game_name: str) -> dict[str, object]:
        game = self._match_game(game_name)
        if game is None:
            return self._skip("backup", game_name, "unmatched_game")

        result = self._run_locked("backup", game.name, lambda: self._adapter.backup(game.name))
        self._refresh_statuses_unlocked()
        self._log("info", f"Backed up {game.name}", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_restore(self, game_name: str) -> dict[str, object]:
        game = self._match_game(game_name)
        if game is None:
            return self._skip("restore", game_name, "unmatched_game")
        if not game.has_backup:
            return self._skip("restore", game.name, "no_backup")

        result = self._run_locked("restore", game.name, lambda: self._adapter.restore(game.name))
        self._log("info", f"Restored {game.name}", "restore", game.name)
        return {"status": "restored", "game": game.name, "result": result}

    def get_versions(self) -> dict[str, str]:
        versions = dict(self._run_locked("versions", None, self._adapter.get_versions))
        versions["sdh_ludusavi"] = resolve_version()
        return versions

    def get_operation_status(self) -> dict[str, object]:
        return self._operation.to_dict()

    def get_recent_logs(self) -> list[dict[str, object]]:
        return [entry.to_dict() for entry in reversed(self._logs)]

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            raw_state = self._state_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._warn_state_load(f"unreadable state file: {exc}")
            return
        if not raw_state.strip():
            self._warn_state_load("empty state file")
            return
        try:
            data = json.loads(raw_state)
        except json.JSONDecodeError as exc:
            self._warn_state_load(f"invalid JSON: {exc}")
            return
        if not isinstance(data, dict):
            self._warn_state_load("state file must contain a JSON object")
            return
        self._auto_sync_enabled = bool(data.get("auto_sync_enabled", False))

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temp_path = self._state_path.with_name(f".{self._state_path.name}.tmp")
        try:
            temp_path.write_text(
                json.dumps(self.get_settings(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self._state_path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    def _refresh_statuses_unlocked(self) -> list[GameStatus]:
        games = [self._coerce_game_status(game) for game in self._adapter.refresh_statuses()]
        self._games = {_normalize(game.name): game for game in games}
        self._log("info", f"Refreshed {len(games)} Ludusavi games", "refresh")
        return games

    def _coerce_game_status(self, data: dict[str, object]) -> GameStatus:
        error = data.get("error")
        return GameStatus(
            name=str(data["name"]),
            configured=bool(data.get("configured", True)),
            has_backup=bool(data.get("has_backup", False)),
            needs_first_backup=bool(data.get("needs_first_backup", False)),
            error=str(error) if error else None,
        )

    def _cached_games(self) -> list[dict[str, object]]:
        return [game.to_dict() for game in self._games.values()]

    def _match_game(self, game_name: str) -> GameStatus | None:
        normalized = _normalize(game_name)
        if not self._games:
            self._refresh_statuses_unlocked()
        return self._games.get(normalized)

    def _run_locked(self, operation: str, game_name: str | None, callback: Any) -> Any:
        if self._operation.is_running or not self._operation_lock.acquire(blocking=False):
            raise OperationLockedError(f"{self._operation.name or 'operation'} is already running")

        self._operation.is_running = True
        self._operation.name = operation
        self._operation.game_name = game_name
        self._operation.last_error = None
        try:
            result = callback()
        except Exception as exc:
            self._operation.last_error = str(exc)
            self._operation.last_result = "failed"
            raise
        else:
            self._operation.last_result = "ok"
            return result
        finally:
            self._operation.is_running = False
            self._operation.name = None
            self._operation.game_name = None
            self._operation_lock.release()

    def _skip(self, operation: str, game_name: str, reason: str) -> dict[str, object]:
        self._log("info", f"Skipped {operation} for {game_name}: {reason}", operation, game_name)
        return {"status": "skipped", "game": game_name, "reason": reason}

    def _log(
        self,
        level: str,
        message: str,
        operation: str | None = None,
        game_name: str | None = None,
    ) -> None:
        self._logs.append(LogEntry(level, message, operation, game_name))

    def _warn_state_load(self, reason: str) -> None:
        LOGGER.warning("Ignoring SDH-ludusavi state at %s: %s", self._state_path, reason)


def _normalize(game_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", game_name.casefold()).strip()
