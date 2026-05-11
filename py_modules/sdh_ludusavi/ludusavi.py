from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast


FLATPAK_ID = "com.github.mtkennerly.ludusavi"


class PyludusaviAdapter:
    """
    A concrete implementation of LudusaviAdapter that uses the pyludusavi library.

    This adapter discovers the user's Ludusavi executable (prioritizing the raw binary
    extracted from the Flatpak to avoid DBUS initialization issues in the root context)
    and proxies commands (backup, restore, versions) to it.
    """

    def __init__(
        self,
        flatpak_id: str = FLATPAK_ID,
        flatpak_user_home: str | None = None,
        flatpak_user: str | None = None,
    ) -> None:
        from pyludusavi import Ludusavi

        user_home = flatpak_user_home or _decky_user_home()
        raw_binary = _find_ludusavi_binary(flatpak_id, user_home)

        ludusavi_factory = cast(Any, Ludusavi)
        self._client = ludusavi_factory(
            explicit_path=raw_binary,
            config_dir=_find_ludusavi_config_dir(flatpak_id, user_home, raw_binary)
            if raw_binary
            else None,
            flatpak_id=flatpak_id,
            flatpak_user_home=user_home,
            flatpak_user=flatpak_user or _decky_user(),
        )

    def refresh_statuses(self) -> list[dict[str, object]]:
        preview = self._client.backup(preview=True).data
        backups = self._client.backups_list().data
        preview_games = _games_from_output(preview)
        backup_games = _games_from_output(backups)

        names = sorted(set(preview_games) | set(backup_games), key=str.casefold)
        return [
            {
                "name": name,
                "configured": True,
                "has_backup": bool(backup_games.get(name, {}).get("backups")),
                "needs_first_backup": not bool(backup_games.get(name, {}).get("backups")),
                "error": _game_error(preview_games.get(name, {})),
            }
            for name in names
        ]

    def compare_recency(self, game_name: str) -> str:
        # Ludusavi's current API exposes change categories, not a guaranteed
        # timestamp comparison between live saves and backups. Keep auto-restore
        # conservative unless a future adapter can prove backup recency.
        if not self._client.backups_list(games=[game_name]).data.get("games"):
            return "no_backup"
        return "ambiguous"

    def backup(self, game_name: str) -> dict[str, object]:
        return cast(dict[str, object], self._client.backup(games=[game_name], force=True).data)

    def restore(self, game_name: str) -> dict[str, object]:
        return cast(dict[str, object], self._client.restore(games=[game_name], force=True).data)

    def get_versions(self) -> dict[str, str]:
        ludusavi = self._client.version()
        return {
            "ludusavi": ludusavi,
        }


def _games_from_output(output: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Extract the 'games' dictionary from pyludusavi's JSON output payload,
    ensuring it is safely cast to a nested dictionary structure.
    """
    games = output.get("games", {})
    if isinstance(games, Mapping):
        return {str(name): dict(game) for name, game in games.items() if isinstance(game, Mapping)}
    return {}


def _game_error(game: dict[str, Any]) -> str | None:
    """
    Scan a game's 'files' and 'registry' output collections to see if Ludusavi
    reported any specific failures, and return the first error message encountered.
    """
    for collection in ("files", "registry"):
        items = game.get(collection, {})
        if not isinstance(items, dict):
            continue
        for value in items.values():
            if isinstance(value, dict) and value.get("failed"):
                error = value.get("error")
                return str(error) if error else "Ludusavi reported a failed item"
    return None


def _find_ludusavi_binary(flatpak_id: str, user_home: str | None) -> str | None:
    import os

    candidates: list[str] = []
    if user_home:
        candidates.append(f"{user_home}/.local/bin/ludusavi")
        candidates.append(
            f"{user_home}/.local/share/flatpak/app/{flatpak_id}/current/active/files/bin/ludusavi"
        )
    candidates.append(f"/var/lib/flatpak/app/{flatpak_id}/current/active/files/bin/ludusavi")
    candidates.append("/usr/bin/ludusavi")
    candidates.append("/usr/local/bin/ludusavi")

    for candidate in candidates:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _find_ludusavi_config_dir(
    flatpak_id: str, user_home: str | None, raw_binary: str
) -> str | None:
    import os

    if user_home and "flatpak" in raw_binary:
        candidate = f"{user_home}/.var/app/{flatpak_id}/config/ludusavi"
        if os.path.exists(candidate):
            return candidate
    return None


def _decky_user_home() -> str | None:
    import os

    env_home = os.environ.get("DECKY_USER_HOME")
    if env_home:
        return env_home

    try:
        import decky
    except ImportError:
        return None

    user_home = getattr(decky, "DECKY_USER_HOME", None)
    return str(user_home) if user_home else None


def _decky_user() -> str | None:
    import os

    env_user = os.environ.get("DECKY_USER")
    if env_user:
        return env_user

    try:
        import decky
    except ImportError:
        return None

    user = getattr(decky, "DECKY_USER", None)
    return str(user) if user else None
