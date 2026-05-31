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


def test_cache_poisoning_guard(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    # 1. Simulate a successful update check result and record/cache it
    successful_res = {
        "status": "current",
        "checked_at": "2026-05-30T12:00:00Z",
        "channel": "stable",
    }
    service._update_check_cache["last_result"] = successful_res
    service.record_update_check_result(successful_res)

    # 2. Record a failed check result (e.g. rate-limit or network failure)
    failed_res = {
        "status": "failed",
        "checked_at": "2026-05-30T13:00:00Z",
        "message": "API rate limit exceeded",
    }
    service.record_update_check_result(failed_res)

    # 3. Assert that last_result is STILL the successful check, not overwritten or poisoned
    assert service._update_check_cache.get("last_result") == successful_res


def test_decky_settings_store_defaults() -> None:
    from typing import Any
    from main import DeckySettingsStore

    class MockManager:
        def __init__(self) -> None:
            self.settings: dict[str, Any] = {}

        def read(self) -> None:
            pass

        def getSetting(self, key: str, default: Any) -> Any:
            return self.settings.get(key, default)

        def setSetting(self, key: str, value: Any) -> None:
            self.settings[key] = value

        def commit(self) -> None:
            pass

    manager = MockManager()
    store = DeckySettingsStore(manager)

    # Reading empty manager should yield default settings
    settings = store.read()
    assert settings["update_channel"] == "stable"
    assert settings["automatic_update_checks"] is True

    # Writing settings should commit them to the manager
    store.write({"update_channel": "development", "automatic_update_checks": False})
    assert manager.settings["update_channel"] == "development"
    assert manager.settings["automatic_update_checks"] is False


def test_transient_rate_limit_properties(tmp_path: Path) -> None:
    import datetime

    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    # Set rate-limit reset timestamp
    future_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    service._update_rate_limited_until = future_time

    # Save state
    service._save_state()

    # Re-instantiate service from files and assert that rate-limit timestamp is not persisted
    service2 = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    assert service2._update_rate_limited_until is None


def test_record_update_install_requested_preserves_metadata(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    candidate = {
        "version": "0.2.2-dev.g456",
        "tag": "v0.2.2-dev.g456",
        "channel": "development",
        "published_at": "2026-05-30T12:00:00Z",
        "action": "update",
    }

    # 1. Call record_update_install_requested
    ctx = service.record_update_install_requested(candidate)

    # 2. Assert the returned context STILL contains the pending_update_install metadata
    assert ctx["pending_update_install"] is not None
    assert ctx["pending_update_install"]["version"] == "0.2.2-dev.g456"

    # 3. Assert calling get_update_check_context() does NOT clear the pending update metadata
    ctx2 = service.get_update_check_context()
    assert ctx2["pending_update_install"] is not None
    assert ctx2["pending_update_install"]["version"] == "0.2.2-dev.g456"

    # 4. Assert that calling reconcile_pending_update_install with mismatching version clears it
    service.reconcile_pending_update_install("0.2.1")
    ctx3 = service.get_update_check_context()
    assert ctx3["pending_update_install"] is None
