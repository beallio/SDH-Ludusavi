from __future__ import annotations

from pathlib import Path
from sdh_ludusavi.service import SDHLudusaviService
from sdh_ludusavi.persistence import JsonSettingsStore


def test_updater_service_settings_defaults(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    # Save empty/old settings
    settings_file.write_text("{}", encoding="utf-8")
    cache_file.write_text("{}", encoding="utf-8")

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    # Defaults should be applied
    assert service._update_channel == "stable"
    assert service._automatic_update_checks is True
    assert service._update_check_cache == {}


def test_updater_service_channel_normalization(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    # Save invalid channel
    settings_file.write_text('{"update_channel": "invalid"}', encoding="utf-8")
    cache_file.write_text("{}", encoding="utf-8")

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    # Invalid channel should normalize to stable
    assert service._update_channel == "stable"


def test_updater_service_set_methods(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    service.set_update_channel("development")
    assert service._update_channel == "development"

    service.set_automatic_update_checks(False)
    assert service._automatic_update_checks is False


def test_pending_update_install_reconciliation(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    # Set pending update
    pending = {
        "version": "0.2.2-dev.g456",
        "tag": "v0.2.2-dev.g456",
        "channel": "development",
        "published_at": "2026-05-30T12:00:00Z",
        "requested_at": "2026-05-30T12:01:00Z",
    }
    service._update_check_cache["pending_update_install"] = pending

    # Reconciliation on matching version: promotes tag and clears pending
    service.reconcile_pending_update_install("0.2.2-dev.g456")
    assert service._update_check_cache.get("installed_release_tag") == "v0.2.2-dev.g456"
    assert (
        service._update_check_cache.get("installed_release_published_at") == "2026-05-30T12:00:00Z"
    )
    assert service._update_check_cache.get("pending_update_install") is None

    # Reset pending
    service._update_check_cache["pending_update_install"] = pending
    # Reconciliation on mismatched version: clears pending and does not promote
    service.reconcile_pending_update_install("0.2.1")
    assert service._update_check_cache.get("pending_update_install") is None
    # Tag was already v0.2.2-dev.g456 from previous step, let's verify it didn't update to v0.2.1
    assert service._update_check_cache.get("installed_release_tag") == "v0.2.2-dev.g456"
