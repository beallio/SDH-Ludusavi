from __future__ import annotations

from sdh_ludusavi.updater import parse_plugin_version


def test_parse_plugin_version_stable() -> None:
    parsed = parse_plugin_version("0.2.1")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert not parsed.is_dev
    assert parsed.dev_suffix is None
    assert parsed.build_metadata is None


def test_parse_plugin_version_dev_gsha() -> None:
    parsed = parse_plugin_version("0.2.1-dev.g55d87c")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert parsed.is_dev
    assert parsed.dev_suffix == "g55d87c"
    assert parsed.build_metadata is None


def test_parse_plugin_version_dev_legacy() -> None:
    parsed = parse_plugin_version("0.2.1-dev.55d87c")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert parsed.is_dev
    assert parsed.dev_suffix == "55d87c"
    assert parsed.build_metadata is None


def test_parse_plugin_version_local_build() -> None:
    parsed = parse_plugin_version("0.2.1+g55d87c")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert not parsed.is_dev
    assert parsed.dev_suffix is None
    assert parsed.build_metadata == "g55d87c"


def test_parse_plugin_version_invalid() -> None:
    assert parse_plugin_version("invalid") is None
    assert parse_plugin_version("1.2") is None
    assert parse_plugin_version("1.2.3.4") is None


def test_version_comparison() -> None:
    v_0_2_0 = parse_plugin_version("0.2.0")
    v_0_2_1 = parse_plugin_version("0.2.1")
    v_0_2_1_local = parse_plugin_version("0.2.1+g123")
    v_0_2_1_dev1 = parse_plugin_version("0.2.1-dev.g123")
    v_0_2_1_dev2 = parse_plugin_version("0.2.1-dev.g456")
    v_0_2_2_dev = parse_plugin_version("0.2.2-dev.g123")

    assert v_0_2_0 is not None
    assert v_0_2_1 is not None
    assert v_0_2_1_local is not None
    assert v_0_2_1_dev1 is not None
    assert v_0_2_1_dev2 is not None
    assert v_0_2_2_dev is not None

    # Higher stable is greater
    assert v_0_2_1 > v_0_2_0
    assert v_0_2_1 >= v_0_2_0
    assert v_0_2_0 < v_0_2_1
    assert v_0_2_0 <= v_0_2_1

    # Local builds are stable-equivalent
    assert v_0_2_1 == v_0_2_1_local
    assert not (v_0_2_1 < v_0_2_1_local)
    assert not (v_0_2_1 > v_0_2_1_local)

    # Stable wins over same-base dev
    assert v_0_2_1 > v_0_2_1_dev1
    assert v_0_2_1_local > v_0_2_1_dev1

    # Higher base dev is greater than lower stable
    assert v_0_2_2_dev > v_0_2_1
    assert v_0_2_2_dev > v_0_2_1_local
    assert v_0_2_1 < v_0_2_2_dev

    # Same-base dev builds are equal in version comparison (ordering relies on published_at)
    assert v_0_2_1_dev1 == v_0_2_1_dev2
    assert not (v_0_2_1_dev1 < v_0_2_1_dev2)
    assert not (v_0_2_1_dev1 > v_0_2_1_dev2)


def test_validate_release_candidate(monkeypatch) -> None:
    from sdh_ludusavi.updater import validate_release_candidate, JsonResponse

    release = {
        "draft": False,
        "prerelease": False,
        "tag_name": "v0.2.1",
        "html_url": "https://github.com/beallio/SDH-Ludusavi/releases/tag/v0.2.1",
        "published_at": "2026-05-30T12:00:00Z",
        "assets": [
            {
                "name": "SDH-Ludusavi-v0.2.1.manifest.json",
                "browser_download_url": "https://github.com/manifest",
            },
            {
                "name": "SDH-Ludusavi-v0.2.1.zip",
                "browser_download_url": "https://github.com/zip",
            },
        ],
    }

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

    # Mock fetch_json to return manifest
    import sdh_ludusavi.updater as updater_mod

    def mock_fetch_json(url: str, *, timeout_seconds: float = 15.0) -> JsonResponse:
        return JsonResponse(status=200, headers={}, body=manifest)

    monkeypatch.setattr(updater_mod, "fetch_json", mock_fetch_json)

    # Valid candidate
    candidate = validate_release_candidate(release)
    assert candidate is not None
    assert candidate.version == "0.2.1"
    assert candidate.tag == "v0.2.1"
    assert candidate.channel == "stable"
    assert candidate.artifact_url == "https://github.com/zip"
    assert candidate.sha256 == "a" * 64
    assert candidate.release_url == release["html_url"]

    # Draft releases are ignored
    draft_release = dict(release, draft=True)
    assert validate_release_candidate(draft_release) is None

    # Mismatched plugin name in manifest
    bad_manifest = dict(manifest, pluginName="WrongName")
    monkeypatch.setattr(
        updater_mod,
        "fetch_json",
        lambda *args, **kwargs: JsonResponse(status=200, headers={}, body=bad_manifest),
    )
    assert validate_release_candidate(release) is None


def test_select_candidate() -> None:
    from sdh_ludusavi.updater import select_candidate, UpdateCandidate

    # Setup list of validated candidates
    c_stable_1 = UpdateCandidate(
        version="0.2.0",
        tag="v0.2.0",
        channel="stable",
        artifact_url="https://zip1",
        sha256="a" * 64,
        release_url="https://release1",
        published_at="2026-05-20T12:00:00Z",
        action="update",
    )
    c_stable_2 = UpdateCandidate(
        version="0.2.1",
        tag="v0.2.1",
        channel="stable",
        artifact_url="https://zip2",
        sha256="a" * 64,
        release_url="https://release2",
        published_at="2026-05-25T12:00:00Z",
        action="update",
    )
    c_dev_2_1 = UpdateCandidate(
        version="0.2.1-dev.g123",
        tag="v0.2.1-dev.g123",
        channel="development",
        artifact_url="https://zip_dev1",
        sha256="a" * 64,
        release_url="https://release_dev1",
        published_at="2026-05-23T12:00:00Z",
        action="update",
    )
    c_dev_2_2 = UpdateCandidate(
        version="0.2.2-dev.g456",
        tag="v0.2.2-dev.g456",
        channel="development",
        artifact_url="https://zip_dev2",
        sha256="a" * 64,
        release_url="https://release_dev2",
        published_at="2026-05-28T12:00:00Z",
        action="update",
    )

    candidates = [c_stable_1, c_stable_2, c_dev_2_1, c_dev_2_2]

    # Installed: 0.2.0, Channel: stable
    # Should choose latest stable 0.2.1
    sel = select_candidate(candidates, "0.2.0", "stable")
    assert sel is not None
    assert sel.version == "0.2.1"
    assert sel.action == "update"

    # Installed: 0.2.1, Channel: stable
    # Should not offer anything (up to date)
    assert select_candidate(candidates, "0.2.1", "stable") is None

    # Installed: 0.2.1+g999, Channel: stable
    # Local build 0.2.1+g999 is stable-equivalent to 0.2.1. Should not offer stable 0.2.1.
    assert select_candidate(candidates, "0.2.1+g999", "stable") is None

    # Installed: 0.2.1-dev.g123, Channel: stable
    # Latest stable is 0.2.1, same base version as installed dev. Action: move_to_stable.
    sel = select_candidate(candidates, "0.2.1-dev.g123", "stable")
    assert sel is not None
    assert sel.version == "0.2.1"
    assert sel.action == "move_to_stable"

    # Installed: 0.2.2-dev.g456, Channel: stable
    # Latest stable is 0.2.1, which is below the installed dev base 0.2.2. Action: downgrade_to_stable.
    sel = select_candidate(candidates, "0.2.2-dev.g456", "stable")
    assert sel is not None
    assert sel.version == "0.2.1"
    assert sel.action == "downgrade_to_stable"

    # Installed: 0.2.0, Channel: development
    # Should offer stable over dev of same base (0.2.1 wins over 0.2.1-dev.g123).
    # But 0.2.2-dev.g456 is higher base than 0.2.1. So 0.2.2-dev.g456 wins!
    sel = select_candidate(candidates, "0.2.0", "development")
    assert sel is not None
    assert sel.version == "0.2.2-dev.g456"
    assert sel.action == "update"
