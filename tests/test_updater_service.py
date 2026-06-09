from __future__ import annotations

import datetime
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


def test_decky_settings_store_defaults(monkeypatch) -> None:
    import sys
    import types

    # Inject a dummy decky module so main.py can import it
    dummy_decky = types.SimpleNamespace(
        DECKY_USER_HOME="/tmp",
        DECKY_HOME="/tmp",
    )
    monkeypatch.setitem(sys.modules, "decky", dummy_decky)

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


def test_record_update_install_requested_preserves_metadata(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.1")

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

    assert ctx2["effective_installed_version"] == "0.2.2-dev.g456"

    ctx_confirmed = service.confirm_update_install_handoff("0.2.2-dev.g456")
    assert ctx_confirmed["pending_update_install"]["handoff_confirmed_at"] is not None
    assert ctx_confirmed["effective_installed_version"] == "0.2.2-dev.g456"

    # 4. A fresh confirmed mismatch should not clear the pending install.
    # Decky can keep the old backend loaded briefly after the installer handoff.
    service.reconcile_pending_update_install("0.2.1")
    ctx3 = service.get_update_check_context()
    assert ctx3["pending_update_install"] is not None
    assert ctx3["pending_update_install"]["version"] == "0.2.2-dev.g456"
    assert ctx3["effective_installed_version"] == "0.2.2-dev.g456"


def test_update_context_uses_pending_install_as_effective_version(
    monkeypatch, tmp_path: Path
) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.4",
        "tag": "v0.2.4",
        "channel": "stable",
        "published_at": "2026-06-02T12:00:00Z",
        "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "handoff_confirmed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.3")

    ctx = service.get_update_check_context()

    assert ctx["installed_version"] == "0.2.3"
    assert ctx["effective_installed_version"] == "0.2.4"


def test_confirmed_pending_install_freshness_uses_confirmation_time(
    monkeypatch, tmp_path: Path
) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    old_requested_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    fresh_confirmed_at = datetime.datetime.now(datetime.timezone.utc)
    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.4",
        "tag": "v0.2.4",
        "channel": "stable",
        "published_at": "2026-06-02T12:00:00Z",
        "requested_at": old_requested_at.isoformat(),
        "handoff_confirmed_at": fresh_confirmed_at.isoformat(),
    }
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.3")

    ctx = service.get_update_check_context()
    service.reconcile_pending_update_install("0.2.3")

    assert ctx["effective_installed_version"] == "0.2.4"
    assert service._update_check_cache["pending_update_install"]["version"] == "0.2.4"


def test_unconfirmed_pending_install_becomes_effective_version(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.4",
        "tag": "v0.2.4",
        "channel": "stable",
        "published_at": "2026-06-02T12:00:00Z",
        "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.3")

    ctx = service.get_update_check_context()

    assert ctx["installed_version"] == "0.2.3"
    assert ctx["effective_installed_version"] == "0.2.4"


def test_clear_pending_update_install_removes_failed_handoff_metadata(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.4",
        "tag": "v0.2.4",
        "channel": "stable",
        "published_at": "2026-06-02T12:00:00Z",
        "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    ctx = service.clear_pending_update_install("0.2.4")

    assert ctx["pending_update_install"] is None


def test_fresh_confirmed_pending_update_install_survives_startup_mismatch(
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.4",
        "tag": "v0.2.4",
        "channel": "stable",
        "published_at": "2026-06-02T12:00:00Z",
        "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "handoff_confirmed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    service.reconcile_pending_update_install("0.2.3")

    assert service._update_check_cache["pending_update_install"]["version"] == "0.2.4"
    assert service._update_check_cache.get("installed_release_tag") is None


def test_record_update_check_result_logs_failure(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    logged_messages = []

    def mock_log(level: str, msg: str) -> None:
        logged_messages.append((level, msg))

    service.log = mock_log

    failed_res = {
        "status": "failed",
        "checked_at": "2026-05-30T13:00:00Z",
        "message": "SSL certificate verification failed",
    }
    service.record_update_check_result(failed_res)

    assert any(
        level == "error" and "SSL certificate verification failed" in msg
        for level, msg in logged_messages
    )


def test_revalidate_plugin_update_respects_rate_limit(tmp_path: Path, monkeypatch) -> None:
    from typing import Any

    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    # Set rate-limit reset timestamp in the future
    import datetime

    future_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    service._update_rate_limited_until = future_time

    # Candidate to revalidate
    candidate = {
        "version": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "artifact_url": "https://zip-url",
        "sha256": "a" * 64,
    }

    # Mock fetch_json to ensure it is NEVER called when rate limited
    fetch_called = False
    import sdh_ludusavi.updater as updater_mod

    def mock_fetch_json(url: str, **kwargs) -> Any:
        nonlocal fetch_called
        fetch_called = True
        raise RuntimeError("Should not be called")

    class MockClient:
        def list_releases(self):
            return mock_fetch_json("releases")

        def get_release(self, tag):
            return mock_fetch_json(tag)

        def get_manifest(self, url):
            return mock_fetch_json(url)

    monkeypatch.setattr(updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClient())

    # Call revalidate_plugin_update
    res = service.revalidate_plugin_update(candidate)

    assert not fetch_called
    assert res["status"] == "failed"
    assert "Rate limit cooldown active" in res["message"]
    assert res["retry_after"] == future_time.isoformat()


def test_revalidate_plugin_update_records_rate_limit(tmp_path: Path, monkeypatch) -> None:
    from typing import Any

    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    candidate = {
        "version": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "artifact_url": "https://zip-url",
        "sha256": "a" * 64,
    }

    # Mock fetch_json to return 403 rate limit response
    import sdh_ludusavi.updater as updater_mod
    from sdh_ludusavi.updater_models import JsonResponse

    def mock_fetch_json(url: str, **kwargs) -> Any:
        return JsonResponse(
            status=403,
            headers={
                "retry-after": "120",
                "x-ratelimit-remaining": "0",
            },
            body={"message": "API rate limit exceeded"},
        )

    class MockClient:
        def list_releases(self):
            return mock_fetch_json("releases")

        def get_release(self, tag):
            return mock_fetch_json(tag)

        def get_manifest(self, url):
            return mock_fetch_json(url)

    monkeypatch.setattr(updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClient())

    # Call revalidate_plugin_update
    res = service.revalidate_plugin_update(candidate)

    assert res["status"] == "failed"
    assert "rate limit exceeded" in res["message"].lower()
    assert res["retry_after"] is not None
    # Cooldown should be recorded in service
    assert service._update_rate_limited_until is not None


def test_revalidate_plugin_update_does_not_hold_lock_during_fetch(
    tmp_path: Path, monkeypatch
) -> None:
    from typing import Any
    import threading

    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    candidate = {
        "version": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "artifact_url": "https://zip-url",
        "sha256": "a" * 64,
    }

    import sdh_ludusavi.updater as updater_mod
    from sdh_ludusavi.updater_models import JsonResponse

    lock_held_during_fetch = None

    def mock_fetch_json(url: str, **kwargs) -> Any:
        nonlocal lock_held_during_fetch

        # Try to acquire the lock from a separate thread to see if it is held by the main thread
        def try_acquire():
            nonlocal lock_held_during_fetch
            # If the main thread holds the lock, this acquire(blocking=False) will return False
            lock_held_during_fetch = not service._state_lock.acquire(blocking=False)
            if not lock_held_during_fetch:
                service._state_lock.release()

        t = threading.Thread(target=try_acquire)
        t.start()
        t.join()

        # Return a mock response so the function can finish
        return JsonResponse(
            status=200,
            headers={},
            body={
                "tag_name": "v0.2.1",
                "assets": [
                    {
                        "name": "SDH-Ludusavi-v0.2.1.zip",
                        "browser_download_url": "https://zip-url",
                    },
                    {
                        "name": "SDH-Ludusavi-v0.2.1.manifest.json",
                        "browser_download_url": "https://manifest-url",
                    },
                ],
            },
        )

    # We mock the second fetch_json call (for the manifest) to return manifest body
    manifest_fetched = False

    class MockClient:
        def get_release(self, tag):
            return mock_fetch_json(tag)

        def get_manifest(self, url):
            nonlocal manifest_fetched
            manifest_fetched = True
            return JsonResponse(
                status=200,
                headers={},
                body={
                    "schemaVersion": 1,
                    "pluginName": "SDH-Ludusavi",
                    "packageName": "sdh-ludusavi",
                    "version": "0.2.1",
                    "sourceVersion": "0.2.1",
                    "tag": "v0.2.1",
                    "channel": "stable",
                    "assetName": "SDH-Ludusavi-v0.2.1.zip",
                    "sha256": "a" * 64,
                    "generatedAt": "2026-05-30T12:00:00Z",
                },
            )

    monkeypatch.setattr(updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClient())

    service.revalidate_plugin_update(candidate)

    assert lock_held_during_fetch is False
    assert manifest_fetched is True


def test_updater_backend_logging_and_privacy(tmp_path: Path, monkeypatch) -> None:
    import datetime
    import sys
    import types
    import asyncio
    from sdh_ludusavi.updater_models import JsonResponse
    import sdh_ludusavi.updater as updater_mod

    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"
    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    logged = []

    def mock_log(
        level: str, msg: str, operation: str | None = None, game_name: str | None = None
    ) -> None:
        logged.append((level, msg))

    service.log = mock_log

    # 1. Update check log testing
    # A. Check available candidate logging
    releases = [
        {
            "draft": False,
            "prerelease": False,
            "tag_name": "v0.2.1",
            "html_url": "https://release-url",
            "published_at": "2026-05-30T12:00:00Z",
            "assets": [
                {
                    "name": "SDH-Ludusavi-v0.2.1.manifest.json",
                    "browser_download_url": "https://manifest-url",
                },
                {
                    "name": "SDH-Ludusavi-v0.2.1.zip",
                    "browser_download_url": "https://zip-url",
                },
            ],
        }
    ]
    manifest = {
        "schemaVersion": 1,
        "pluginName": "SDH-Ludusavi",
        "packageName": "sdh-ludusavi",
        "version": "0.2.1",
        "sourceVersion": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "assetName": "SDH-Ludusavi-v0.2.1.zip",
        "sha256": "f" * 64,
        "generatedAt": "2026-05-30T12:00:00Z",
    }

    def mock_fetch_success(url: str, **kwargs) -> JsonResponse:
        if "manifest" in url or "manifest.json" in url:
            return JsonResponse(status=200, headers={}, body=manifest)
        if url == "releases":
            return JsonResponse(status=200, headers={}, body=releases)
        return JsonResponse(status=200, headers={}, body=releases[0])

    class MockClient:
        def list_releases(self):
            return mock_fetch_success("releases")

        def get_release(self, tag):
            return mock_fetch_success(tag)

        def get_manifest(self, url):
            return mock_fetch_success(url)

    monkeypatch.setattr(updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClient())

    # Let's call main.py Plugin.check_for_plugin_update indirectly or directly via service/helpers
    # For testing, we mock decky for main.py import
    decky_logs = []

    class MockDeckyLogger:
        def info(self, msg, *args):
            decky_logs.append(msg)

        def warning(self, msg, *args):
            decky_logs.append(msg)

        def exception(self, msg, *args):
            decky_logs.append(msg)

    dummy_decky = types.SimpleNamespace(
        DECKY_USER_HOME=str(tmp_path),
        DECKY_HOME=str(tmp_path),
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path / "settings"),
        DECKY_PLUGIN_RUNTIME_DIR=str(tmp_path / "data"),
        logger=MockDeckyLogger(),
    )
    monkeypatch.setitem(sys.modules, "decky", dummy_decky)
    monkeypatch.setitem(
        sys.modules, "settings", types.SimpleNamespace(SettingsManager=lambda *args, **kwargs: None)
    )

    # We want to test check_for_plugin_update via Plugin or directly. Let's do it via service helper
    # First check: check_for_update through service record and call
    sys.modules.pop("main", None)
    import main

    plugin = main.Plugin()
    plugin._backend = service

    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    assert res["status"] == "available"

    # Verify logs for check start, fetch status, candidate parsing, selection
    assert any("Update check started" in m for _, m in logged)
    assert any(
        "GitHub releases fetch response: status=200" in m and "elapsed_ms" in m for _, m in logged
    )
    assert any("Parsed" in m and "valid candidate" in m and "elapsed_ms" in m for _, m in logged)
    assert any("Selected update candidate:" in m and "elapsed_ms" in m for _, m in logged)

    # Verify privacy: no full SHA-256 in logs
    for level, msg in logged:
        assert "f" * 64 not in msg
        assert "a" * 64 not in msg

    logged.clear()

    # B. Cache hit logging
    # Non-forced call should hit the cache if we just did a check
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=False))
    assert any("cache hit" in m.lower() and "elapsed_ms" in m for _, m in logged)
    logged.clear()

    # C. Rate-limit block logging on update check
    service._update_rate_limited_until = datetime.datetime.now(
        datetime.timezone.utc
    ) + datetime.timedelta(hours=1)
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    assert res["status"] == "failed"
    assert any(
        ("cooldown active" in m.lower() or "blocked by rate-limit" in m.lower())
        and "elapsed_ms" in m
        for _, m in logged
    )
    service._update_rate_limited_until = None
    logged.clear()

    # D. Failed fetch logging
    class MockClientFailed:
        def list_releases(self):
            return JsonResponse(status=500, headers={}, body={"error": "fetch failed"})

        def get_release(self, tag):
            return JsonResponse(status=500, headers={}, body={"error": "fetch failed"})

        def get_manifest(self, url):
            return JsonResponse(status=500, headers={}, body={"error": "fetch failed"})

    monkeypatch.setattr(
        updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClientFailed()
    )
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    assert res["status"] == "failed"
    assert any(
        ("fetch failed" in m.lower() or "failed to check" in m.lower()) and "elapsed_ms" in m
        for _, m in logged
    )
    logged.clear()

    # E. Current logging
    class MockClientLambdaCurrent:
        def list_releases(self):
            return JsonResponse(status=200, headers={}, body=[])

        def get_release(self, tag):
            return JsonResponse(status=200, headers={}, body=[])

        def get_manifest(self, url):
            return JsonResponse(status=200, headers={}, body=[])

    monkeypatch.setattr(
        updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClientLambdaCurrent()
    )
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    assert res["status"] == "current"
    assert any(
        ("no upgrade candidate found" in m.lower() or "already up to date" in m.lower())
        and "elapsed_ms" in m
        for _, m in logged
    )
    logged.clear()

    # 2. Revalidation log testing
    candidate = {
        "version": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "artifact_url": "https://zip-url",
        "sha256": "f" * 64,
    }

    # A. Rate-limit block revalidation
    service._update_rate_limited_until = datetime.datetime.now(
        datetime.timezone.utc
    ) + datetime.timedelta(hours=1)
    res = service.revalidate_plugin_update(candidate)
    assert res["status"] == "failed"
    assert any(
        ("rate-limit cooldown" in m.lower() or "blocked by rate-limit" in m.lower())
        and "elapsed_ms" in m
        for _, m in logged
    )
    service._update_rate_limited_until = None
    logged.clear()

    # B. Fetch failure revalidation
    class MockClient404:
        def list_releases(self):
            return JsonResponse(status=404, headers={}, body={})

        def get_release(self, tag):
            return JsonResponse(status=404, headers={}, body={})

        def get_manifest(self, url):
            return JsonResponse(status=404, headers={}, body={})

    monkeypatch.setattr(updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClient404())
    res = service.revalidate_plugin_update(candidate)
    assert res["status"] == "failed"
    assert any(
        ("fetch failed" in m.lower() or "revalidation check failed" in m.lower())
        and "elapsed_ms" in m
        for _, m in logged
    )
    logged.clear()

    # C. Validation failure revalidation
    # Mock tags fetch to return invalid release object
    class MockClientDraft2:
        def list_releases(self):
            return JsonResponse(status=200, headers={}, body={"draft": True})

        def get_release(self, tag):
            return JsonResponse(status=200, headers={}, body={"draft": True})

        def get_manifest(self, url):
            return JsonResponse(status=200, headers={}, body={"draft": True})

    monkeypatch.setattr(
        updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClientDraft2()
    )
    res = service.revalidate_plugin_update(candidate)
    assert res["status"] == "failed"
    assert any(
        "validation failed during revalidation" in m.lower() and "elapsed_ms" in m
        for _, m in logged
    )
    logged.clear()

    # D. Mismatch failures revalidation (e.g. SHA mismatch)
    class MockClientMismatch:
        def list_releases(self):
            return mock_fetch_success("releases")

        def get_release(self, tag):
            return mock_fetch_success(tag)

        def get_manifest(self, url):
            return mock_fetch_success(url)

    monkeypatch.setattr(updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClient())
    bad_sha_candidate = dict(candidate, sha256="e" * 64)
    res = service.revalidate_plugin_update(bad_sha_candidate)
    assert res["status"] == "failed"
    assert any(
        ("mismatch during revalidation" in m.lower() or "sha-256 mismatch" in m.lower())
        and "elapsed_ms" in m
        for _, m in logged
    )
    logged.clear()

    # E. Revalidation success
    res = service.revalidate_plugin_update(candidate)
    assert "version" in res
    assert any("revalidation success" in m.lower() and "elapsed_ms" in m for _, m in logged)
    logged.clear()

    # 3. Pending install save logging
    # We pass updateTraceId from frontend
    save_cand = dict(candidate, updateTraceId="test-trace-id")
    service.record_update_install_requested(save_cand)
    assert any(
        "pending install saved" in m.lower() and "test-trace-id" in m.lower() for _, m in logged
    )
    logged.clear()

    # 4. Startup reconciliation logs
    # A. Pending promoted
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "published_at": "2026-05-30T12:00:00Z",
    }
    service.reconcile_pending_update_install("0.2.1")
    assert any("pending update promoted" in m.lower() for _, m in logged)
    logged.clear()

    # B. Pending cleared (mismatched version)
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.2",
        "tag": "v0.2.2",
        "channel": "stable",
        "published_at": "2026-05-30T12:00:00Z",
    }
    service.reconcile_pending_update_install("0.2.1")
    assert any("cleared due to version mismatch" in m.lower() for _, m in logged)
    logged.clear()

    # C. No pending update
    service.reconcile_pending_update_install("0.2.1")
    assert any("no pending update found" in m.lower() for _, m in logged)
    logged.clear()

    # 5. Unload logs
    # Mock decky logger is already configured on dummy_decky
    decky_logs.clear()

    # Check unload with pending update
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.2",
    }
    asyncio.run(plugin._unload())
    assert any(
        "unload started" in m.lower() and "pending_update=true" in m.lower() for m in decky_logs
    ) or any(
        "unload started" in m.lower() and "pending_update=true" in m.lower() for _, m in logged
    )
    assert any("unload ended" in m.lower() for m in decky_logs) or any(
        "unload ended" in m.lower() for _, m in logged
    )
    decky_logs.clear()
    logged.clear()

    # Check unload without pending update
    service._update_check_cache.pop("pending_update_install", None)
    asyncio.run(plugin._unload())
    assert any(
        "unload started" in m.lower() and "pending_update=false" in m.lower() for m in decky_logs
    ) or any(
        "unload started" in m.lower() and "pending_update=false" in m.lower() for _, m in logged
    )
    assert any("unload ended" in m.lower() for m in decky_logs) or any(
        "unload ended" in m.lower() for _, m in logged
    )

    # Privacy check again on all collected log entries to make sure full SHA-256 was NEVER written
    for level, msg in logged:
        assert "f" * 64 not in msg
        assert "a" * 64 not in msg


def test_updater_cache_version_aware_and_invalidation(tmp_path: Path, monkeypatch) -> None:
    import sys
    import asyncio
    import types
    from sdh_ludusavi.service import SDHLudusaviService
    from sdh_ludusavi.persistence import JsonSettingsStore
    from sdh_ludusavi.updater_models import JsonResponse

    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"
    settings_file.write_text("{}", encoding="utf-8")
    cache_file.write_text("{}", encoding="utf-8")

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    manifest = {
        "schemaVersion": 1,
        "pluginName": "SDH-Ludusavi",
        "packageName": "sdh-ludusavi",
        "version": "0.2.1",
        "sourceVersion": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "assetName": "SDH-Ludusavi-v0.2.1.zip",
        "sha256": "a" * 64,
        "generatedAt": "2026-05-30T12:00:00Z",
    }
    releases = [
        {
            "draft": False,
            "prerelease": False,
            "tag_name": "v0.2.1",
            "html_url": "https://release-url",
            "published_at": "2026-05-30T12:00:00Z",
            "assets": [
                {
                    "name": "SDH-Ludusavi-v0.2.1.manifest.json",
                    "browser_download_url": "https://manifest-url",
                },
                {
                    "name": "SDH-Ludusavi-v0.2.1.zip",
                    "browser_download_url": "https://zip-url",
                },
            ],
        }
    ]

    # Mock release fetch: return a release candidate
    import sdh_ludusavi.updater as updater_mod

    class MockClientLambda:
        def list_releases(self):
            return JsonResponse(status=200, headers={}, body=releases)

        def get_release(self, tag):
            return JsonResponse(status=200, headers={}, body=releases)

        def get_manifest(self, url):
            return JsonResponse(status=200, headers={}, body=manifest)

    monkeypatch.setattr(
        updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClientLambda()
    )

    # Setup plugin for main.py check_for_plugin_update
    dummy_decky = types.SimpleNamespace(
        DECKY_USER_HOME=str(tmp_path),
        DECKY_HOME=str(tmp_path),
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path / "settings"),
        DECKY_PLUGIN_RUNTIME_DIR=str(tmp_path / "data"),
        logger=types.SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "decky", dummy_decky)
    monkeypatch.setitem(
        sys.modules, "settings", types.SimpleNamespace(SettingsManager=lambda *args, **kwargs: None)
    )

    sys.modules.pop("main", None)
    import main

    plugin = main.Plugin()
    plugin._backend = service

    # 1. Version-aware backend cache reuse test
    # Run a live check with version 0.2.0
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=False))
    assert res["status"] == "available"
    # This should store the cached result and the checked version (0.2.0)
    assert service._update_check_cache.get("last_checked_version") == "0.2.0"
    assert service._update_check_cache.get("last_result") == res

    # Calling check_for_plugin_update with the same version ("0.2.0") should HIT cache
    # Let's count how many times fetch_json is called
    fetch_calls = 0

    def mock_fetch_counted(url, **kwargs):
        nonlocal fetch_calls
        fetch_calls += 1
        if "manifest" in url or "manifest.json" in url:
            return JsonResponse(status=200, headers={}, body=manifest)
        if "sha256" in url:
            return JsonResponse(status=200, headers={}, body="a" * 64)
        return JsonResponse(status=200, headers={}, body=releases)

    class MockClient:
        def list_releases(self):
            return mock_fetch_counted("releases")

        def get_release(self, tag):
            return mock_fetch_counted(tag)

        def get_manifest(self, url):
            return mock_fetch_counted(url)

    monkeypatch.setattr(updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClient())

    # Call with same version: cached hit, fetch_calls should remain 0
    res2 = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=False))
    assert res2["status"] == "available"
    assert fetch_calls == 0

    # Call with a DIFFERENT version ("0.2.1"): cache bypassed, fetch_calls should increase
    res3 = asyncio.run(plugin.check_for_plugin_update("0.2.1", force=False))
    assert res3["status"] == "current"  # because target release is v0.2.1
    assert fetch_calls > 0
    assert service._update_check_cache.get("last_checked_version") == "0.2.1"

    # 2. Invalidation tests
    # Reset to available cache
    class MockClientLambdaInvalidation:
        def list_releases(self):
            return JsonResponse(status=200, headers={}, body=releases)

        def get_release(self, tag):
            return JsonResponse(status=200, headers={}, body=releases)

        def get_manifest(self, url):
            return JsonResponse(status=200, headers={}, body=manifest)

    monkeypatch.setattr(
        updater_mod, "GitHubReleaseClient", lambda *args, **kwargs: MockClientLambda()
    )
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    assert service._update_check_cache.get("last_result") is not None
    assert service._update_check_cache.get("last_available_tag") == "v0.2.1"
    assert service._update_check_cache.get("last_checked_version") == "0.2.0"

    # Test invalidation on record_update_install_requested
    service.record_update_install_requested(res["candidate"])
    assert service._update_check_cache.get("last_result") is None
    assert service._update_check_cache.get("last_available_tag") is None
    assert service._update_check_cache.get("last_checked_version") is None

    # Reset cache again
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    assert service._update_check_cache.get("last_result") is not None

    # Test invalidation on confirm_update_install_handoff
    service.confirm_update_install_handoff("0.2.1")
    assert service._update_check_cache.get("last_result") is None
    assert service._update_check_cache.get("last_available_tag") is None
    assert service._update_check_cache.get("last_checked_version") is None

    # Reset cache again
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    assert service._update_check_cache.get("last_result") is not None

    # Test invalidation on clear_pending_update_install
    service.clear_pending_update_install("0.2.1")
    assert service._update_check_cache.get("last_result") is None
    assert service._update_check_cache.get("last_available_tag") is None
    assert service._update_check_cache.get("last_checked_version") is None

    # Reset cache again and set pending update
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    service.record_update_install_requested(res["candidate"])
    # Put some values in cache to test reconcile promotion invalidation
    service._update_check_cache["last_result"] = res
    service._update_check_cache["last_available_tag"] = "v0.2.1"
    service._update_check_cache["last_checked_version"] = "0.2.0"

    # Reconcile pending update with promotion (version matches pending)
    service.reconcile_pending_update_install("0.2.1")
    assert service._update_check_cache.get("last_result") is None
    assert service._update_check_cache.get("last_available_tag") is None
    assert service._update_check_cache.get("last_checked_version") is None
    assert service._update_check_cache.get("installed_release_tag") == "v0.2.1"

    # Reset cache again and record install request
    res = asyncio.run(plugin.check_for_plugin_update("0.2.0", force=True))
    service.record_update_install_requested(res["candidate"])
    service._update_check_cache["last_result"] = res
    service._update_check_cache["last_available_tag"] = "v0.2.1"
    service._update_check_cache["last_checked_version"] = "0.2.0"

    # Reconcile pending update with version mismatch clearing
    # Let's override requested_at to make it stale
    service._update_check_cache["pending_update_install"]["requested_at"] = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)
    ).isoformat()
    service.reconcile_pending_update_install("0.2.2")
    assert service._update_check_cache.get("last_result") is None
    assert service._update_check_cache.get("last_available_tag") is None
    assert service._update_check_cache.get("last_checked_version") is None
    assert service._update_check_cache.get("pending_update_install") is None


def test_record_update_install_requested_returns_immediate_effective_version(
    monkeypatch, tmp_path: Path
) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.2-dev.g123")

    candidate = {
        "version": "0.2.3",
        "tag": "v0.2.3",
        "channel": "stable",
        "published_at": "2026-06-04T12:00:00Z",
        "action": "move_to_stable",
    }

    ctx = service.record_update_install_requested(candidate)
    assert ctx["effective_installed_version"] == "0.2.3"
    assert ctx["installed_version"] == "0.2.2-dev.g123"


def test_unconfirmed_pending_install_ttl(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.2-dev.g123")

    candidate = {
        "version": "0.2.3",
        "tag": "v0.2.3",
        "channel": "stable",
        "published_at": "2026-06-04T12:00:00Z",
        "action": "move_to_stable",
    }

    service.record_update_install_requested(candidate)

    # 1. Fresh unconfirmed install is effective
    ctx = service.get_update_check_context()
    assert ctx["effective_installed_version"] == "0.2.3"

    # 2. Mock time to make it stale
    stale_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)
    service._update_check_cache["pending_update_install"]["requested_at"] = stale_time.isoformat()

    ctx_stale = service.get_update_check_context()
    assert ctx_stale["effective_installed_version"] == "0.2.2-dev.g123"


def test_reconcile_promotion_stable_equivalents(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    def set_pending_stable() -> None:
        service._update_check_cache["pending_update_install"] = {
            "version": "0.2.3",
            "tag": "v0.2.3",
            "channel": "stable",
            "published_at": "2026-06-04T12:00:00Z",
            "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    # 1. Pending stable 0.2.3 promotes when loaded version is 0.2.3
    set_pending_stable()
    service.reconcile_pending_update_install("0.2.3")
    assert service._update_check_cache.get("installed_release_tag") == "v0.2.3"
    assert service._update_check_cache.get("pending_update_install") is None

    # 2. Pending stable 0.2.3 promotes when loaded version is 0.2.3+metadata
    set_pending_stable()
    service.reconcile_pending_update_install("0.2.3+metadata")
    assert service._update_check_cache.get("installed_release_tag") == "v0.2.3"
    assert service._update_check_cache.get("pending_update_install") is None

    # 3. Pending stable 0.2.3 does NOT promote when loaded version is 0.2.3-dev.gabcdef
    service._update_check_cache.pop("installed_release_tag", None)
    service._update_check_cache["pending_update_install"] = {
        "version": "0.2.3",
        "tag": "v0.2.3-new",
        "channel": "stable",
        "published_at": "2026-06-04T12:00:00Z",
        "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    service.reconcile_pending_update_install("0.2.3-dev.gabcdef")
    assert service._update_check_cache.get("installed_release_tag") is None
    assert service._update_check_cache.get("pending_update_install") is not None


def test_check_for_plugin_update_pending_fast_path(monkeypatch, tmp_path: Path) -> None:
    import sys
    import types
    import asyncio

    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    service = SDHLudusaviService(settings_store=store, cache_path=cache_file)

    dummy_decky = types.SimpleNamespace(
        DECKY_USER_HOME=str(tmp_path),
        DECKY_HOME=str(tmp_path),
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path / "settings"),
        DECKY_PLUGIN_RUNTIME_DIR=str(tmp_path / "data"),
        logger=types.SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "decky", dummy_decky)
    monkeypatch.setitem(
        sys.modules, "settings", types.SimpleNamespace(SettingsManager=lambda *args, **kwargs: None)
    )

    sys.modules.pop("main", None)
    import main

    plugin = main.Plugin()
    plugin._backend = service

    # Mock sdh_ludusavi.updater.check_for_update to fail or raise if called, to prove the fast path does NOT call it.
    check_for_update_calls = 0

    def mock_check_for_update(current_version, channel, service):
        nonlocal check_for_update_calls
        check_for_update_calls += 1
        return {"status": "current"}

    monkeypatch.setattr("sdh_ludusavi.updater.check_for_update", mock_check_for_update)

    # 1. Fresh pending install: stable-to-dev (from stable 0.2.0 to dev 0.2.1-dev.g123)
    # Target version is dev: "0.2.1-dev.g123"
    candidate = {
        "version": "0.2.1-dev.g123",
        "tag": "v0.2.1-dev.g123",
        "channel": "development",
        "published_at": "2026-06-04T12:00:00Z",
        "action": "install",
    }
    # Current version is "0.2.0"
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.0")
    service.record_update_install_requested(candidate)

    # If we check for update on the TARGET version ("0.2.1-dev.g123"), it should hit the fast path
    # since effective_installed_version === target_version (i.e. "0.2.1-dev.g123")
    res = asyncio.run(plugin.check_for_plugin_update("0.2.1-dev.g123", force=True))
    assert res["status"] == "current"
    assert check_for_update_calls == 0

    # 2. Fresh pending install: dev-to-dev (from dev 0.2.1-dev.g123 to dev 0.2.1-dev.g456)
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.1-dev.g123")
    service.clear_pending_update_install()
    candidate2 = {
        "version": "0.2.1-dev.g456",
        "tag": "v0.2.1-dev.g456",
        "channel": "development",
        "published_at": "2026-06-04T12:00:00Z",
        "action": "install",
    }
    service.record_update_install_requested(candidate2)
    res2 = asyncio.run(plugin.check_for_plugin_update("0.2.1-dev.g456", force=True))
    assert res2["status"] == "current"
    assert check_for_update_calls == 0

    # 3. Fresh pending install: dev-to-stable (from dev 0.2.1-dev.g123 to stable 0.2.1)
    monkeypatch.setattr("sdh_ludusavi.updater.resolve_version", lambda: "0.2.1-dev.g123")
    service.clear_pending_update_install()
    candidate3 = {
        "version": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "published_at": "2026-06-04T12:00:00Z",
        "action": "move_to_stable",
    }
    service.record_update_install_requested(candidate3)
    res3 = asyncio.run(plugin.check_for_plugin_update("0.2.1", force=True))
    assert res3["status"] == "current"
    assert check_for_update_calls == 0

    # 4. Stale pending metadata: should bypass fast path and fall through to check_for_update
    service.clear_pending_update_install()
    candidate4 = {
        "version": "0.2.1",
        "tag": "v0.2.1",
        "channel": "stable",
        "published_at": "2026-06-04T12:00:00Z",
        "action": "move_to_stable",
    }
    service.record_update_install_requested(candidate4)
    # mock time to make it stale (exceeding grace limit of 15 minutes)
    stale_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)
    service._update_check_cache["pending_update_install"]["requested_at"] = stale_time.isoformat()

    asyncio.run(plugin.check_for_plugin_update("0.2.1", force=True))
    # It should call check_for_update, so check_for_update_calls should be 1
    assert check_for_update_calls == 1
