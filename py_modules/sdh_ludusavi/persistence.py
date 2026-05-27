from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol, cast

LOGGER = logging.getLogger("sdh_ludusavi.service.persistence")


class SettingsStore(Protocol):
    def read(self) -> dict[str, object]: ...

    def write(self, settings: dict[str, object]) -> None: ...


class JsonSettingsStore:
    """Small JSON settings store for tests and non-Decky local execution."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        raw_settings = self._path.read_text(encoding="utf-8")
        if not raw_settings.strip():
            return {}
        data = json.loads(raw_settings)
        if not isinstance(data, dict):
            return {}
        return cast(dict[str, object], data)

    def write(self, settings: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.tmp")
        try:
            temp_path.write_text(
                json.dumps(settings, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self._path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise


class PersistenceManager:
    """Manages the persistence of settings and dynamic cache payloads, supporting

    both combined single-file storage and split settings/cache files.
    """

    def __init__(
        self,
        state_path: Path | None = None,
        settings_store: SettingsStore | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self._combined_state_path = state_path
        self._settings_store = settings_store or JsonSettingsStore(
            state_path or Path("/tmp/sdh_ludusavi/settings.json")
        )
        self._cache_path = cache_path or state_path or Path("/tmp/sdh_ludusavi/cache.json")

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Load all data from persistence.

        Returns:
            A dict containing "settings" and "cache" dicts.
        """
        settings = {}
        cache = {}

        if self._combined_state_path is not None:
            if self._combined_state_path.exists():
                try:
                    raw_state = self._combined_state_path.read_text(encoding="utf-8")
                    if not raw_state.strip():
                        self._warn_load("empty state file")
                    else:
                        data = json.loads(raw_state)
                        if isinstance(data, dict):
                            settings = cast(dict[str, Any], dict(data))
                            cache = cast(dict[str, Any], dict(data))
                        else:
                            self._warn_load("state file must contain a JSON object")
                except OSError as exc:
                    self._warn_load(f"unreadable state file: {exc}")
                except json.JSONDecodeError as exc:
                    self._warn_load(f"invalid JSON: {exc}")
            return {"settings": settings, "cache": cache}

        # Load separate settings
        try:
            settings_data = self._settings_store.read()
            if isinstance(settings_data, dict):
                settings = settings_data
        except (OSError, json.JSONDecodeError) as exc:
            self._warn_load(f"unreadable settings: {exc}")

        # Load separate cache
        if self._cache_path.exists():
            try:
                raw_cache = self._cache_path.read_text(encoding="utf-8")
                if not raw_cache.strip():
                    self._warn_load("empty cache file")
                else:
                    cache_data = json.loads(raw_cache)
                    if isinstance(cache_data, dict):
                        cache = cache_data
                    else:
                        self._warn_load("cache file must contain a JSON object")
            except OSError as exc:
                self._warn_load(f"unreadable cache: {exc}")
            except json.JSONDecodeError as exc:
                self._warn_load(f"invalid cache JSON: {exc}")

        return {"settings": settings, "cache": cache}

    def save_settings(self, settings_data: dict[str, Any]) -> None:
        """Save settings payload.

        If combined state path is in use, saves the combined file (updating settings fields).
        """
        if self._combined_state_path is not None:
            self._save_combined(settings_data, self._load_combined_cache())
            return
        self._settings_store.write(settings_data)

    def save_cache(self, cache_data: dict[str, Any]) -> None:
        """Save cache payload.

        If combined state path is in use, saves the combined file (updating cache fields).
        """
        if self._combined_state_path is not None:
            self._save_combined(self._load_combined_settings(), cache_data)
            return

        self._cache_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temp_path = self._cache_path.with_name(f".{self._cache_path.name}.tmp")
        try:
            temp_path.write_text(
                json.dumps(cache_data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self._cache_path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    def _load_combined_settings(self) -> dict[str, Any]:
        data = self.load_all()
        # Filter settings keys from combined loaded dict
        from .service import SETTINGS_KEYS

        return {k: v for k, v in data["settings"].items() if k in SETTINGS_KEYS}

    def _load_combined_cache(self) -> dict[str, Any]:
        data = self.load_all()
        from .service import SETTINGS_KEYS

        return {k: v for k, v in data["cache"].items() if k not in SETTINGS_KEYS}

    def _save_combined(self, settings_data: dict[str, Any], cache_data: dict[str, Any]) -> None:
        if self._combined_state_path is None:
            raise RuntimeError("_save_combined called without a combined state path")
        data = {**settings_data, **cache_data}
        self._combined_state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temp_path = self._combined_state_path.with_name(f".{self._combined_state_path.name}.tmp")
        try:
            temp_path.write_text(
                json.dumps(data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self._combined_state_path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    def _warn_load(self, reason: str) -> None:
        state_path = self._combined_state_path or self._cache_path
        LOGGER.warning("Ignoring SDH-ludusavi state at %s: %s", state_path, reason)
