from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol, cast

LOGGER = logging.getLogger("sdh_ludusavi.service.persistence")

# Bounded so a stuck peer process can degrade consistency but never hang the
# plugin; flock is advisory and all writes stay atomic (temp + os.replace).
LOCK_ACQUIRE_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_INTERVAL_SECONDS = 0.05


class _InterProcessLock:
    """Advisory file lock shared by all plugin processes touching one state set.

    Decky's update flow can briefly run two backend instances (and a lingering
    third) against the same settings/cache files; flock on a sidecar lock file
    serializes their read-modify-write cycles. Re-entrant per process via an
    RLock plus depth counter, so a locked compound operation can call the
    individually-locked save/load methods.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._fd: int | None = None

    def __enter__(self) -> "_InterProcessLock":
        self._thread_lock.acquire()
        self._depth += 1
        if self._depth == 1:
            self._fd = self._acquire_file_lock()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._depth == 1 and self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError as exc:
                LOGGER.warning("Failed to release state lock at %s: %s", self.path, exc)
            self._fd = None
        self._depth -= 1
        self._thread_lock.release()

    def _acquire_file_lock(self) -> int | None:
        try:
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as exc:
            LOGGER.warning("State lock unavailable at %s: %s", self.path, exc)
            return None

        deadline = time.monotonic() + LOCK_ACQUIRE_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    LOGGER.warning(
                        "Timed out acquiring state lock at %s after %.1fs; "
                        "proceeding without inter-process exclusion",
                        self.path,
                        LOCK_ACQUIRE_TIMEOUT_SECONDS,
                    )
                    os.close(fd)
                    return None
                time.sleep(LOCK_RETRY_INTERVAL_SECONDS)


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
        _atomic_json_write(self._path, settings)


def _atomic_json_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        temp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


class PersistenceManager:
    """Manages the persistence of settings and dynamic cache payloads, supporting

    both combined single-file storage and split settings/cache files.
    """

    def __init__(
        self,
        settings_store: SettingsStore | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self._settings_store = settings_store or JsonSettingsStore(
            Path("/tmp/sdh_ludusavi/settings.json")
        )
        self._cache_path = cache_path or Path("/tmp/sdh_ludusavi/cache.json")
        lock_anchor = self._cache_path
        self._lock = _InterProcessLock(lock_anchor.with_name(".sdh_ludusavi.state.lock"))

    @property
    def lock_path(self) -> Path:
        return self._lock.path

    def locked(self) -> _InterProcessLock:
        """Hold the state lock across a compound read-modify-write cycle."""
        return self._lock

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Load all data from persistence.

        Returns:
            A dict containing "settings" and "cache" dicts.
        """
        with self._lock:
            return self._load_all_locked()

    def _load_all_locked(self) -> dict[str, dict[str, Any]]:
        settings = {}
        cache = {}

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
        """Save settings payload."""
        with self._lock:
            self._settings_store.write(settings_data)

    def save_cache(self, cache_data: dict[str, Any]) -> None:
        """Save cache payload."""
        with self._lock:
            _atomic_json_write(self._cache_path, cache_data)

    def _warn_load(self, reason: str) -> None:
        LOGGER.warning("Ignoring SDH-ludusavi state: %s", reason)
