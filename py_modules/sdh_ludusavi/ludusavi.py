from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, cast


FLATPAK_ID = "com.github.mtkennerly.ludusavi"
LOGGER = logging.getLogger(__name__)


def _ludusavi_env() -> dict[str, str]:
    """
    Return Ludusavi subprocess environment overrides.

    pyludusavi merges these values onto the current process environment, so
    LD_LIBRARY_PATH must be set to an empty string to clear it for subprocesses.
    """
    env: dict[str, str] = {}
    if "XDG_RUNTIME_DIR" not in os.environ:
        env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    else:
        env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
    if "LD_LIBRARY_PATH" in os.environ:
        env["LD_LIBRARY_PATH"] = ""
    return env


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
    ) -> None:
        from pyludusavi import Ludusavi

        env = _ludusavi_env()
        LOGGER.debug("Using Ludusavi environment overrides: %s", env)
        self._client = Ludusavi(flatpak_id=flatpak_id, env=env)
        self._cached_config_path: str | None = None
        self._cached_versions: dict[str, str] | None = None
        self._cached_diagnostics: dict[str, object] | None = None

    def refresh_statuses(self) -> list[dict[str, object]]:
        preview = self._client.backup(preview=True).data
        backups = self._client.backups_list().data
        preview_games = _games_from_output(preview)
        backup_games = _games_from_output(backups)

        # Filter out games that have no files and no registry entries in the preview.
        # This ensures we only show games that Ludusavi actually found on the system.
        # We also filter out games where the decision is 'Ignored' or 'Cancelled'.
        installed_games = {
            name: game
            for name, game in preview_games.items()
            if (game.get("files") or game.get("registry"))
            and game.get("decision") not in ("Ignored", "Cancelled")
        }

        names = sorted(installed_games.keys(), key=str.casefold)
        return [
            {
                "name": name,
                "configured": True,
                "has_backup": bool(backup_games.get(name, {}).get("backups")),
                "needs_first_backup": not bool(backup_games.get(name, {}).get("backups")),
                "steam_id": str(installed_games.get(name, {}).get("steamId"))
                if installed_games.get(name, {}).get("steamId")
                else None,
                "error": _game_error(installed_games.get(name, {})),
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

    def get_conflict_metadata(self, game_name: str) -> dict[str, object]:
        metadata: dict[str, object] = {}
        try:
            backups_data = self._client.backups_list(games=[game_name]).data.get("games", {})
            game_backups = backups_data.get(game_name, {})
            backups = game_backups.get("backups") or []
            if backups:
                latest_backup = backups[0]
                if isinstance(latest_backup, dict):
                    metadata["backupModifiedAt"] = latest_backup.get("when")
            backup_path = game_backups.get("backupPath")
            if backup_path:
                metadata["backupPath"] = backup_path
        except Exception:
            pass

        try:
            preview = self._client.backup(games=[game_name], preview=True, force=True).data
            files = preview.get("games", {}).get(game_name, {}).get("files", {})
            mtimes = []
            if isinstance(files, dict):
                for file_data in files.values():
                    if not isinstance(file_data, dict):
                        continue
                    raw_path = file_data.get("redirectedPath") or file_data.get("originalPath")
                    if not raw_path:
                        continue
                    try:
                        mtimes.append(Path(str(raw_path)).stat().st_mtime)
                    except OSError:
                        continue
            if mtimes:
                metadata["localModifiedAt"] = datetime.fromtimestamp(
                    max(mtimes),
                    tz=timezone.utc,
                ).isoformat()
        except Exception:
            pass
        return metadata

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

        cached_versions = getattr(self, "_cached_versions", None)
        if cached_versions is not None:
            return dict(cached_versions)

        ludusavi = self._client.version()
        # Normalize the Ludusavi version string to be lowercase and without the "ludusavi " prefix, if present.
        ludusavi = ludusavi.lower().replace("ludusavi", "").strip() if ludusavi else "unknown"
        versions = {
            "ludusavi": ludusavi,
            "pyludusavi": pyludusavi_version,
        }
        self._cached_versions = dict(versions)
        return versions

    def _config_path(self) -> str:
        if getattr(self, "_cached_config_path", None) is None:
            self._cached_config_path = self._client.config_path()
        cached_config_path = self._cached_config_path
        if cached_config_path is None:
            raise RuntimeError("Ludusavi config path discovery returned no path")
        return cached_config_path

    def get_diagnostics(self) -> dict[str, object]:
        cached_diagnostics = getattr(self, "_cached_diagnostics", None)
        if cached_diagnostics is not None:
            return dict(cached_diagnostics)

        command_prefix = list(getattr(self._client, "command_prefix", []))
        command_type = "unknown"
        command_path = "unknown"
        if command_prefix[:2] == ["flatpak", "run"]:
            command_type = "flatpak"
            command_path = command_prefix[2] if len(command_prefix) > 2 else "unknown"
        elif command_prefix:
            command_type = "bin"
            command_path = command_prefix[0]

        version = self.get_versions().get("ludusavi", "unknown")
        config_path = self._config_path()
        backup_path = "unknown"
        try:
            backup_config = self._client.config_show().data.get("backup", {})
            if isinstance(backup_config, dict):
                backup_path = str(backup_config.get("path") or "unknown")
        except Exception:
            pass

        diagnostics = {
            "version": version,
            "type": command_type,
            "path": command_path,
            "configPath": config_path,
            "backupPath": backup_path,
        }
        self._cached_diagnostics = dict(diagnostics)
        return diagnostics

    def get_log_contents(self) -> str:
        return self._client.log_show()

    def get_config_mtime_ns(self) -> int | None:
        try:
            return Path(self._config_path()).stat().st_mtime_ns
        except Exception as exc:
            LOGGER.debug(
                "Unable to stat Ludusavi config path: %s", self._cached_config_path, exc_info=True
            )
            raise exc


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
