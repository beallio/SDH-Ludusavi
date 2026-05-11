from __future__ import annotations

import subprocess
from collections.abc import Mapping
from typing import Any, cast


FLATPAK_ID = "com.github.mtkennerly.ludusavi"


class PyludusaviAdapter:
    def __init__(self, flatpak_id: str = FLATPAK_ID, flatpak_user_home: str | None = None) -> None:
        from pyludusavi import Ludusavi

        ludusavi_factory = cast(Any, Ludusavi)
        self._client = ludusavi_factory(
            flatpak_id=flatpak_id,
            flatpak_user_home=flatpak_user_home or _decky_user_home(),
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
            "rclone": self._rclone_version(),
        }

    def _rclone_version(self) -> str:
        command = _rclone_command_from_prefix(list(self._client.command_prefix))
        if command is None:
            return "unavailable"
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            return f"unavailable: {exc}"
        return result.stdout.splitlines()[0] if result.stdout else "unavailable"


def _games_from_output(output: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    games = output.get("games", {})
    if isinstance(games, Mapping):
        return {str(name): dict(game) for name, game in games.items() if isinstance(game, Mapping)}
    return {}


def _game_error(game: dict[str, Any]) -> str | None:
    for collection in ("files", "registry"):
        items = game.get(collection, {})
        if not isinstance(items, dict):
            continue
        for value in items.values():
            if isinstance(value, dict) and value.get("failed"):
                error = value.get("error")
                return str(error) if error else "Ludusavi reported a failed item"
    return None


def _rclone_command_from_prefix(command_prefix: list[str]) -> list[str] | None:
    try:
        run_index = command_prefix.index("run")
    except ValueError:
        return None

    for app_index in range(run_index + 1, len(command_prefix)):
        if not command_prefix[app_index].startswith("-"):
            return command_prefix[:app_index] + [
                "--command=rclone",
                command_prefix[app_index],
                "version",
            ]
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
