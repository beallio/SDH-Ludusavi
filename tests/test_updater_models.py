from __future__ import annotations

from sdh_ludusavi.updater_models import (
    ReleaseManifest,
    UpdaterCacheModel,
    parse_release_manifest,
)


def test_parse_release_manifest() -> None:
    manifest_dict = {
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

    # Valid
    manifest = parse_release_manifest(manifest_dict)
    assert isinstance(manifest, ReleaseManifest)
    assert manifest.version == "0.2.1"

    # Invalid sha256 length
    bad_sha = dict(manifest_dict, sha256="bad")
    assert parse_release_manifest(bad_sha) is None

    # Missing field
    missing_version = dict(manifest_dict)
    del missing_version["version"]
    assert parse_release_manifest(missing_version) is None

    # Not a dict
    assert parse_release_manifest(["not", "dict"]) is None


def test_updater_cache_model() -> None:
    # Empty
    cache = UpdaterCacheModel.from_dict({})
    assert cache.last_checked_at is None
    assert cache.to_dict() == {}

    # Valid
    cache = UpdaterCacheModel.from_dict(
        {
            "last_checked_at": "2026-06-08T12:00:00Z",
            "last_checked_channel": "stable",
            "extra_field": "test",
        }
    )
    assert cache.last_checked_at == "2026-06-08T12:00:00Z"
    assert cache.last_checked_channel == "stable"
    assert cache.extras == {"extra_field": "test"}
    assert cache.to_dict() == {
        "last_checked_at": "2026-06-08T12:00:00Z",
        "last_checked_channel": "stable",
        "extra_field": "test",
    }

    # Malformed fields individually rejected
    cache2 = UpdaterCacheModel.from_dict(
        {
            "last_checked_at": 123,  # Should be discarded
            "last_checked_channel": "invalid_channel",  # Should be discarded
            "last_result": "not_a_dict",  # Should be discarded
            "pending_update_install": ["list"],  # Should be discarded
            "last_checked_version": "1.0",  # Kept
            "extra_field": "test",  # Kept
        }
    )
    assert cache2.last_checked_at is None
    assert cache2.last_checked_channel is None
    assert cache2.last_result is None
    assert cache2.pending_update_install is None
    assert cache2.last_checked_version == "1.0"
    assert cache2.extras == {"extra_field": "test"}

    assert cache2.to_dict() == {
        "last_checked_version": "1.0",
        "extra_field": "test",
    }
