from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import stat
import threading
from typing import Any, cast

from pyludusavi import LudusaviError

from .constants import (
    LUDUSAVI_OPERATION_TIMEOUT_SECONDS,
    LUDUSAVI_PREVIEW_TIMEOUT_SECONDS,
)


FLATPAK_ID = "com.github.mtkennerly.ludusavi"
LOGGER = logging.getLogger(__name__)
_ALIASES_INIT_LOCK = threading.Lock()
_MONITORED_CONFIG_FILES = ("cache.yaml", "manifest.yaml")


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
        self._cached_aliases: dict[str, str] | None = None
        self._cached_aliases_mtime_ns: int | None = None
        self._aliases_lock = threading.Lock()

    def refresh_statuses(self, game_names: list[str] | None = None) -> list[dict[str, object]]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            if game_names:
                preview_future = executor.submit(
                    self._client.backup,
                    games=game_names,
                    preview=True,
                    timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS,
                )
                # backups_list has no timeout param; executor 30s default applies
                backups_future = executor.submit(self._client.backups_list, games=game_names)
            else:
                preview_future = executor.submit(
                    self._client.backup, preview=True, timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS
                )
                # backups_list has no timeout param; executor 30s default applies
                backups_future = executor.submit(self._client.backups_list)
            preview = preview_future.result().data
            backups = backups_future.result().data

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
        aliases_lock = getattr(self, "_aliases_lock", None)
        if aliases_lock is None:
            with _ALIASES_INIT_LOCK:
                aliases_lock = getattr(self, "_aliases_lock", None)
                if aliases_lock is None:
                    aliases_lock = threading.Lock()
                    self._aliases_lock = aliases_lock

        current_mtime_ns: int | None = None
        try:
            current_mtime_ns = self.get_config_mtime_ns()
        # Intentionally broad: alias refresh should still try config_show when the
        # optional mtime optimization is unavailable.
        except Exception as exc:
            LOGGER.debug("Failed to read config mtime for custom game aliases: %s", exc)

        with aliases_lock:
            cached_aliases = getattr(self, "_cached_aliases", None)
            cached_mtime_ns = getattr(self, "_cached_aliases_mtime_ns", None)
            if (
                current_mtime_ns is not None
                and cached_aliases is not None
                and cached_mtime_ns == current_mtime_ns
            ):
                return dict(cached_aliases)

        aliases: dict[str, str] = {}
        try:
            config = self._client.config_show().data
            for game in config.get("customGames", []):
                name = game.get("name")
                alias = game.get("alias")
                if name and alias:
                    aliases[name] = alias
            if current_mtime_ns is not None:
                with aliases_lock:
                    self._cached_aliases = dict(aliases)
                    self._cached_aliases_mtime_ns = current_mtime_ns
        except (LudusaviError, KeyError, TypeError, ValueError, AttributeError) as exc:
            LOGGER.debug("Failed to retrieve custom game aliases: %s", exc)
        return aliases

    def compare_recency(self, game_name: str) -> str:
        """
        Compare the local save recency against the latest Ludusavi backup.

        Returns one of:
            "no_backup"      - no backups exist for the game
            "local_current"  - backup and local save are identical
            "backup_newer"   - backup contains data absent locally (safe restore)
            "backup_differs" - backup and local both exist and differ; direction
                               unknown from this signal alone
            "ambiguous"      - preview failed or returned an unexpected shape
        """
        # Check if any backup exists first
        backups_data = self._client.backups_list(games=[game_name]).data.get("games", {})
        game_backups = backups_data.get(game_name, {})
        if not game_backups.get("backups"):
            return "no_backup"

        # Run a restore preview to see if the backup differs from local
        try:
            preview = self._client.restore(
                games=[game_name], preview=True, timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS
            ).data
            game_output = preview.get("games", {}).get(game_name, {})
            change = game_output.get("change")

            if change == "Same":
                return "local_current"
            if change == "New":
                # In a restore context, New implies the backup contains files
                # that don't exist locally — safe to auto-restore.
                return "backup_newer"
            if change == "Different":
                # Different means both sides exist and differ; direction is
                # unknown, so signal the caller to corroborate via timestamps.
                return "backup_differs"
        except (LudusaviError, KeyError, TypeError, ValueError) as exc:
            LOGGER.debug(
                "Restore preview failed or returned unexpected shape during recency check for %s: %s",
                game_name,
                exc,
            )

        return "ambiguous"

    def get_conflict_metadata(self, game_name: str) -> dict[str, object]:
        metadata: dict[str, object] = {}
        try:
            backups_data = self._client.backups_list(games=[game_name]).data.get("games", {})
            game_backups = backups_data.get(game_name, {})
            backups = game_backups.get("backups") or []
            if backups:
                backup_when = _newest_backup_when(backups)
                if backup_when is not None:
                    metadata["backupModifiedAt"] = backup_when
            backup_path = game_backups.get("backupPath")
            if backup_path:
                metadata["backupPath"] = backup_path
        except (LudusaviError, KeyError, TypeError, ValueError) as exc:
            LOGGER.debug("Failed to retrieve backup list for conflict metadata: %s", exc)

        try:
            preview = self._client.backup(
                games=[game_name],
                preview=True,
                force=True,
                timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS,
            ).data
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
        except (LudusaviError, KeyError, TypeError, ValueError) as exc:
            LOGGER.debug("Failed to run backup preview for conflict metadata: %s", exc)
        return metadata

    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
        timeout = (
            LUDUSAVI_PREVIEW_TIMEOUT_SECONDS if preview else LUDUSAVI_OPERATION_TIMEOUT_SECONDS
        )
        return cast(
            dict[str, object],
            self._client.backup(
                games=[game_name], preview=preview, force=True, timeout=timeout
            ).data,
        )

    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]:
        timeout = (
            LUDUSAVI_PREVIEW_TIMEOUT_SECONDS if preview else LUDUSAVI_OPERATION_TIMEOUT_SECONDS
        )
        return cast(
            dict[str, object],
            self._client.restore(
                games=[game_name], preview=preview, force=True, timeout=timeout
            ).data,
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
        except (LudusaviError, KeyError, TypeError, ValueError):
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
        """
        Return a composite 64-bit signed integer hash of monitored config file mtimes.

        Monitors config.yaml, cache.yaml, and manifest.yaml to detect settings changes,
        GUI/CLI backups, and manifest updates.

        Note/Limitation:
        As an O(1) constant-time check, this does not scan the backups directory directly.
        Therefore, external file/folder additions/deletions within the backups directory
        (e.g., via manual sync, Syncthing, Dropbox) will not trigger cache invalidation
        until Ludusavi GUI or CLI updates its configuration or database files.
        """
        try:
            if getattr(self, "_cached_resolved_config_path", None) is None:
                self._cached_resolved_config_path = Path(self._config_path()).resolve()
            config_path = self._cached_resolved_config_path
            config_stat = config_path.stat()
            mtimes = [config_stat.st_mtime_ns]
        except (OSError, RuntimeError, LudusaviError):
            path_to_log = getattr(self, "_cached_config_path", None)
            if path_to_log is None:
                LOGGER.debug("Unable to discover Ludusavi config path", exc_info=True)
            else:
                LOGGER.debug("Unable to stat Ludusavi config path: %s", path_to_log, exc_info=True)
            raise

        # Check optional sibling files defined in _MONITORED_CONFIG_FILES
        config_dir = config_path.parent
        for filename in _MONITORED_CONFIG_FILES:
            sibling = config_dir / filename
            try:
                st = sibling.stat()
                if stat.S_ISREG(st.st_mode):
                    mtimes.append(st.st_mtime_ns)
            except OSError:
                pass

        # Combine all mtimes using a stable 64-bit integer SHA-256 hash
        mtimes.sort()
        mtimes_str = ",".join(str(m) for m in mtimes)
        digest = hashlib.sha256(mtimes_str.encode("utf-8")).digest()
        # Return a signed 64-bit integer
        return int.from_bytes(digest[:8], byteorder="big", signed=True)


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


def _newest_backup_when(backups: list[dict[str, Any]] | list[Any]) -> str | None:
    """Return the latest 'when' timestamp from a list of backup dicts."""
    newest: str | None = None
    for backup in backups:
        when = backup.get("when")
        if isinstance(when, str):
            if newest is None or when > newest:
                newest = when
    return newest
