from __future__ import annotations

DEFAULT_NOTIFICATION_SETTINGS: dict[str, bool] = {
    "enabled": True,
    "auto_sync_progress": True,
    "auto_sync_results": True,
    "manual_operations": True,
    "refresh_status": True,
    "failures_errors": True,
}

SETTINGS_KEYS = (
    "auto_sync_enabled",
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

# Upper bound for real (non-preview) Ludusavi backup/restore subprocesses.
# Deliberately generous: Ludusavi-managed cloud sync of large saves over slow
# links is legitimate. On expiry, subprocess.run kills the child and the
# operation surfaces as an ordinary failure, releasing the global lock.
LUDUSAVI_OPERATION_TIMEOUT_SECONDS = 900.0

# Upper bound for preview/recency Ludusavi subprocesses. Generous because the
# backup command may perform a manifest update on first run. This also bounds
# the worst-case launch-gate pause during check_game_start.
LUDUSAVI_PREVIEW_TIMEOUT_SECONDS = 300.0

# Watchdog: A pause lease is valid for this many seconds from its last renewal.
LAUNCH_GATE_LEASE_TTL_SECONDS = 30.0

# Watchdog: The frontend should renew a lease every this many seconds.
LAUNCH_GATE_RENEW_INTERVAL_SECONDS = 5.0

# Watchdog: resume a SIGSTOPped game after this long UNCONDITIONALLY, even if
# an operation still claims to be running. Sized to outlast the longest legal
# operation so it only fires when something is genuinely wedged.
WATCHDOG_ABSOLUTE_RESUME_SECONDS = LUDUSAVI_OPERATION_TIMEOUT_SECONDS + 60.0
