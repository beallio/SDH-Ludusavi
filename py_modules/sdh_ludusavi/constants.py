from __future__ import annotations

DEFAULT_NOTIFICATION_SETTINGS: dict[str, bool] = {
    "enabled": True,
    "auto_sync_progress": True,
    "auto_sync_results": True,
    "manual_operations": True,
    "refresh_status": True,
    "failures_errors": True,
    "update_available": True,
}

SETTINGS_KEYS = (
    "auto_sync_enabled",
    "sync_disabled_games",
    "selected_game",
    "notifications",
    "update_channel",
    "automatic_update_checks",
    "debug_logging",
)

MAX_INSTALLED_APP_IDS_BYTES = 16_384

CONFIG_MARKER_READ_FAILED = object()
CACHE_MARKER_UNCHANGED = object()

# Safety margin for "Different" recency: if backup timestamp is not more than
# this many seconds newer than the local save, treat it as ambiguous.
RECENCY_TIMESTAMP_MARGIN_SECONDS: float = 120.0

# Three-minute upper bound for real (non-preview) Ludusavi backup and restore
# subprocesses. On expiry, the operation surfaces as an ordinary failure and
# releases the global lock.
LUDUSAVI_OPERATION_TIMEOUT_SECONDS = 180.0

# Three-minute upper bound for Ludusavi preview, recency, and status-check
# subprocesses. This also bounds the normal launch-gate pause during
# check_game_start.
LUDUSAVI_PREVIEW_TIMEOUT_SECONDS = 180.0

# Watchdog: A pause lease is valid for this many seconds from its last renewal.
LAUNCH_GATE_LEASE_TTL_SECONDS = 30.0

# Watchdog: The frontend should renew a lease every this many seconds.
LAUNCH_GATE_RENEW_INTERVAL_SECONDS = 5.0

# Watchdog: four-minute emergency ceiling for a frozen Steam app scope. It is
# derived from the longest legal Ludusavi command plus one minute, so it only
# fires when the normal three-minute operation is genuinely wedged.
WATCHDOG_ABSOLUTE_RESUME_SECONDS = (
    max(LUDUSAVI_OPERATION_TIMEOUT_SECONDS, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) + 60.0
)
