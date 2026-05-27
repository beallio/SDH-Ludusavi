from __future__ import annotations

from sdh_ludusavi.constants import (
    DEFAULT_NOTIFICATION_SETTINGS,
    SETTINGS_KEYS,
    MAX_INSTALLED_APP_IDS_BYTES,
)


def test_constants_defined() -> None:
    assert DEFAULT_NOTIFICATION_SETTINGS["enabled"] is True
    assert "auto_sync_enabled" in SETTINGS_KEYS
    assert MAX_INSTALLED_APP_IDS_BYTES == 16384
