from __future__ import annotations

import functools
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, List, Literal, Mapping

from sdh_ludusavi._version import resolve_version


@functools.total_ordering
@dataclass(frozen=True)
class ParsedPluginVersion:
    major: int
    minor: int
    patch: int
    is_dev: bool = False
    dev_suffix: str | None = None
    build_metadata: str | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ParsedPluginVersion):
            return NotImplemented
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
            and self.is_dev == other.is_dev
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ParsedPluginVersion):
            return NotImplemented
        self_base = (self.major, self.minor, self.patch)
        other_base = (other.major, other.minor, other.patch)
        if self_base != other_base:
            return self_base < other_base
        if self.is_dev and not other.is_dev:
            return True
        return False


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    plugin_name: str
    package_name: str
    version: str
    source_version: str
    tag: str
    channel: Literal["stable", "dev"]
    asset_name: str
    sha256: str
    generated_at: str


@dataclass(frozen=True)
class UpdateCandidate:
    version: str
    tag: str
    channel: Literal["stable", "development"]
    artifact_url: str
    sha256: str
    release_url: str
    published_at: str
    action: Literal["update", "move_to_stable", "downgrade_to_stable"]


@dataclass(frozen=True)
class JsonResponse:
    status: int
    headers: Mapping[str, str]
    body: dict[str, Any] | list[Any]


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-dev\.([a-zA-Z0-9.-]+))?(?:\+([a-zA-Z0-9.-]+))?$")


def parse_plugin_version(version_str: str) -> ParsedPluginVersion | None:
    match = _VERSION_RE.match(version_str)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3))
    dev_suffix = match.group(4)
    build_metadata = match.group(5)
    is_dev = dev_suffix is not None
    return ParsedPluginVersion(
        major=major,
        minor=minor,
        patch=patch,
        is_dev=is_dev,
        dev_suffix=dev_suffix,
        build_metadata=build_metadata,
    )


def _get_user_agent() -> str:
    try:
        ver = resolve_version()
    # Intentionally broad
    except Exception:
        ver = "0.1.0"
    return f"SDH-Ludusavi/{ver}"


def fetch_json(url: str, *, timeout_seconds: float = 15.0) -> JsonResponse:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": _get_user_agent(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            status = response.status
            resp_headers = {k.lower(): v for k, v in response.headers.items()}
            body_bytes = response.read()
            body = json.loads(body_bytes.decode("utf-8"))
            return JsonResponse(status=status, headers=resp_headers, body=body)
    except urllib.error.HTTPError as e:
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
        try:
            body = json.loads(e.read().decode("utf-8"))
        # Intentionally broad
        except Exception:
            body = {}
        return JsonResponse(status=e.code, headers=resp_headers, body=body)
    # Intentionally broad
    except Exception as e:
        return JsonResponse(status=500, headers={}, body={"error": str(e)})


def validate_release_candidate(release: dict[str, Any]) -> UpdateCandidate | None:
    if release.get("draft", False):
        return None

    assets = release.get("assets", [])
    manifest_assets = [a for a in assets if a.get("name", "").endswith(".manifest.json")]
    if len(manifest_assets) != 1:
        return None
    manifest_asset = manifest_assets[0]

    resp = fetch_json(manifest_asset["browser_download_url"])
    if resp.status != 200 or not isinstance(resp.body, dict):
        return None
    manifest = resp.body

    # Validate manifest structure & field requirements
    if manifest.get("schemaVersion") != 1:
        return None
    if manifest.get("pluginName") != "SDH-Ludusavi":
        return None
    if manifest.get("packageName") != "sdh-ludusavi":
        return None
    if manifest.get("tag") != release.get("tag_name"):
        return None
    if "v" + str(manifest.get("version")) != release.get("tag_name"):
        return None

    # Validate channel matches prerelease
    manifest_channel = manifest.get("channel")
    is_prerelease = release.get("prerelease", False)
    if manifest_channel == "stable" and is_prerelease:
        return None
    if manifest_channel == "dev" and not is_prerelease:
        return None
    if manifest_channel not in ("stable", "dev"):
        return None

    # Validate sha256 syntax
    sha256 = manifest.get("sha256")
    if not isinstance(sha256, str) or not re.match(r"^[a-fA-F0-9]{64}$", sha256):
        return None

    # Validate exactly one ZIP matching manifest assetName
    zip_assets = [a for a in assets if a.get("name", "").endswith(".zip")]
    if len(zip_assets) != 1:
        return None
    zip_asset = zip_assets[0]
    if zip_asset.get("name") != manifest.get("assetName"):
        return None

    channel: Literal["stable", "development"] = (
        "stable" if manifest_channel == "stable" else "development"
    )
    return UpdateCandidate(
        version=manifest["version"],
        tag=manifest["tag"],
        channel=channel,
        artifact_url=zip_asset["browser_download_url"],
        sha256=sha256,
        release_url=release.get("html_url", ""),
        published_at=release.get("published_at", ""),
        action="update",
    )


def select_candidate(
    candidates: List[UpdateCandidate],
    installed_version_str: str,
    preferred_channel: Literal["stable", "development"],
) -> UpdateCandidate | None:
    installed_version = parse_plugin_version(installed_version_str)
    if not installed_version:
        return None

    # Filter candidates by channel preference
    eligible: List[UpdateCandidate] = []
    for c in candidates:
        if preferred_channel == "stable" and c.channel != "stable":
            continue
        c_ver = parse_plugin_version(c.version)
        if not c_ver:
            continue
        eligible.append(c)

    if not eligible:
        return None

    # Helper key to sort by base version, dev status, and published_at
    def get_sort_key(c: UpdateCandidate) -> tuple[int, int, int, bool, str]:
        c_ver = parse_plugin_version(c.version)
        assert c_ver is not None
        # We want stable to win over dev of same base, so not c_ver.is_dev
        return (c_ver.major, c_ver.minor, c_ver.patch, not c_ver.is_dev, c.published_at)

    eligible.sort(key=get_sort_key)
    best_candidate = eligible[-1]
    best_ver = parse_plugin_version(best_candidate.version)
    assert best_ver is not None

    is_upgrade = False
    action: Literal["update", "move_to_stable", "downgrade_to_stable"] = "update"

    # Base version component comparisons
    best_base = (best_ver.major, best_ver.minor, best_ver.patch)
    installed_base = (installed_version.major, installed_version.minor, installed_version.patch)

    if preferred_channel == "stable" and installed_version.is_dev:
        # On stable channel with a dev build installed: always offer latest stable
        is_upgrade = True
        if best_base == installed_base:
            action = "move_to_stable"
        elif best_base < installed_base:
            action = "downgrade_to_stable"
        else:
            action = "update"
    else:
        # Standard SemVer selection
        if best_ver > installed_version:
            is_upgrade = True
            if not best_ver.is_dev and installed_version.is_dev and best_base == installed_base:
                action = "move_to_stable"
        elif best_ver == installed_version:
            if best_ver.is_dev and installed_version.is_dev:
                # Same base dev version: offer upgrade if string version is different (e.g. different tag/SHA)
                if best_candidate.version != installed_version_str:
                    is_upgrade = True
                    action = "update"
            elif not best_ver.is_dev and installed_version.is_dev:
                is_upgrade = True
                action = "move_to_stable"

    if is_upgrade:
        return UpdateCandidate(
            version=best_candidate.version,
            tag=best_candidate.tag,
            channel=best_candidate.channel,
            artifact_url=best_candidate.artifact_url,
            sha256=best_candidate.sha256,
            release_url=best_candidate.release_url,
            published_at=best_candidate.published_at,
            action=action,
        )

    return None
