from __future__ import annotations

from collections.abc import Mapping
import os
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

        # LD_LIBRARY_PATH = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ""
        self._client = Ludusavi()
        # os.environ["LD_LIBRARY_PATH"] = LD_LIBRARY_PATH
        # user_home = flatpak_user_home or _decky_user_home()
        # self._client = Ludusavi(
        #     flatpak_id=flatpak_id,
        #     flatpak_user_home=user_home,
        #     flatpak_user=flatpak_user or _decky_user(),
        # )

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
                "steam_id": str(preview_games.get(name, {}).get("steamId"))
                if preview_games.get(name, {}).get("steamId")
                else None,
                "error": _game_error(preview_games.get(name, {})),
            }
            for name in names
        ]

    def get_aliases(self) -> dict[str, str]:
        """
        Build a map of custom game names to their canonical titles.
        """
        aliases: dict[str, str] = {}
        try:
            config = self._client.config_show().data
            for game in config.get("customGames", []):
                name = game.get("name")
                alias = game.get("alias")
                if name and alias:
                    aliases[name] = alias
        except Exception:
            pass
        return aliases

    def compare_recency(self, game_name: str) -> str:
        """
        Compare the local save recency against the latest Ludusavi backup.

        Uses a restore preview to determine if the backup contains changes
        not present in the local save.
        """
        # Check if any backup exists first
        backups_data = self._client.backups_list(games=[game_name]).data.get("games", {})
        game_backups = backups_data.get(game_name, {})
        if not game_backups.get("backups"):
            return "no_backup"

        # Run a restore preview to see if the backup differs from local
        try:
            preview = self._client.restore(games=[game_name], preview=True).data
            game_output = preview.get("games", {}).get(game_name, {})
            change = game_output.get("change")

            if change == "Same":
                return "local_current"
            if change in ("New", "Different"):
                # In a restore context, New/Different implies the backup has
                # data that should be applied to local.
                return "backup_newer"
        except Exception:
            pass

        return "ambiguous"

    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._client.backup(games=[game_name], preview=preview, force=True).data,
        )

    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._client.restore(games=[game_name], preview=preview, force=True).data,
        )

    def get_versions(self) -> dict[str, str]:
        from pyludusavi import __version__ as pyludusavi_version

        ludusavi = self._client.version()
        # Normalize the Ludusavi version string to be lowercase and without the "ludusavi " prefix, if present.
        ludusavi = ludusavi.lower().replace("ludusavi", "").strip() if ludusavi else "unknown"
        return {
            "ludusavi": ludusavi,
            "pyludusavi": pyludusavi_version,
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
