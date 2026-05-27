from __future__ import annotations

DEFAULT_NOTIFICATION_SETTINGS: dict[str, bool] = {
    "enabled": True,
    "auto_sync_progress": True,
    "auto_sync_results": True,
    "manual_operations": True,
    "refresh_status": True,
    "failures_errors": True,
}

SETTINGS_KEYS = ("auto_sync_enabled", "selected_game", "notifications")

MAX_INSTALLED_APP_IDS_BYTES = 16_384

CONFIG_MARKER_READ_FAILED = object()
CACHE_MARKER_UNCHANGED = object()
