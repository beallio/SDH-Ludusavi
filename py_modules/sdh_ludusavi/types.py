from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


class LudusaviAdapter(Protocol):
    def refresh_statuses(self, game_names: list[str] | None = None) -> list[dict[str, object]]: ...
    def compare_recency(self, game_name: str) -> str:
        """Return one of: backup_newer, backup_differs, local_current, ambiguous, no_backup."""

    def get_conflict_metadata(self, game_name: str) -> dict[str, object]: ...
    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]: ...
    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]: ...
    def list_backups(self, game_name: str) -> dict[str, object]: ...
    def restore_backup(self, game_name: str, backup_id: str) -> dict[str, object]: ...
    def get_versions(self) -> dict[str, str]: ...
    def get_log_contents(self) -> str: ...
    def get_config_mtime_ns(self) -> int | None: ...
    def get_diagnostics(self) -> dict[str, object]: ...


@dataclass
class GameStatus:
    """Represents the parsed Ludusavi status for a single game."""

    name: str
    configured: bool
    has_backup: bool
    needs_first_backup: bool
    steam_id: str | None = None
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
