from __future__ import annotations

import datetime
import functools
import json
import re
import ssl
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


def _get_ssl_context() -> ssl.SSLContext:
    from pathlib import Path

    context = ssl.create_default_context()
    standard_paths = [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/ca-bundle.pem",
        "/etc/pki/tls/cacert.pem",
        "/etc/ssl/certs/ca-bundle.crt",
    ]
    for path_str in standard_paths:
        path = Path(path_str)
        if path.exists():
            try:
                context.load_verify_locations(cafile=str(path))
                break
            # Intentionally broad
            except Exception:
                pass
    return context


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
        with urllib.request.urlopen(
            req, timeout=timeout_seconds, context=_get_ssl_context()
        ) as response:
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

    tag_name = release.get("tag_name", "")
    if not tag_name or not tag_name.startswith("v"):
        return None

    version_part = tag_name[1:]
    parsed_version = parse_plugin_version(version_part)
    if parsed_version is None:
        return None

    expected_manifest_name = f"SDH-Ludusavi-{tag_name}.manifest.json"

    assets = release.get("assets", [])
    manifest_assets = [a for a in assets if a.get("name", "") == expected_manifest_name]
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


def check_for_update(
    current_version: str,
    preferred_channel: Literal["stable", "development"],
) -> dict[str, Any]:
    url = "https://api.github.com/repos/beallio/SDH-Ludusavi/releases"
    resp = fetch_json(url)

    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if resp.status in (403, 429):
        retry_after_str = None
        if "retry-after" in resp.headers:
            try:
                seconds = int(resp.headers["retry-after"])
                retry_after_str = (
                    datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(seconds=seconds)
                ).isoformat()
            # Intentionally broad
            except Exception:
                pass
        elif "x-ratelimit-reset" in resp.headers:
            try:
                reset_ts = int(resp.headers["x-ratelimit-reset"])
                retry_after_str = datetime.datetime.fromtimestamp(
                    reset_ts, datetime.timezone.utc
                ).isoformat()
            # Intentionally broad
            except Exception:
                pass

        if not retry_after_str:
            retry_after_str = (
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)
            ).isoformat()

        msg = "Rate limit exceeded"
        if isinstance(resp.body, dict) and "message" in resp.body:
            msg = str(resp.body["message"])

        return {
            "status": "failed",
            "checked_at": checked_at,
            "message": msg,
            "retry_after": retry_after_str,
        }

    if resp.status != 200 or not isinstance(resp.body, list):
        msg = "Failed to check for updates"
        if isinstance(resp.body, dict):
            if "message" in resp.body:
                msg = str(resp.body["message"])
            elif "error" in resp.body:
                msg = str(resp.body["error"])
        return {
            "status": "failed",
            "checked_at": checked_at,
            "message": msg,
        }

    candidates = []
    for r in resp.body:
        if not isinstance(r, dict):
            continue
        c = validate_release_candidate(r)
        if c:
            candidates.append(c)

    candidate = select_candidate(candidates, current_version, preferred_channel)
    if candidate:
        return {
            "status": "available",
            "checked_at": checked_at,
            "candidate": {
                "version": candidate.version,
                "tag": candidate.tag,
                "channel": candidate.channel,
                "artifact_url": candidate.artifact_url,
                "sha256": candidate.sha256,
                "release_url": candidate.release_url,
                "published_at": candidate.published_at,
                "action": candidate.action,
            },
        }

    return {
        "status": "current",
        "checked_at": checked_at,
        "channel": preferred_channel,
    }


def revalidate_install_candidate(candidate_dict: dict[str, Any]) -> dict[str, Any]:
    tag = candidate_dict.get("tag")
    if not tag:
        raise ValueError("Candidate missing tag")

    url = f"https://api.github.com/repos/beallio/SDH-Ludusavi/releases/tags/{tag}"
    resp = fetch_json(url)
    if resp.status != 200 or not isinstance(resp.body, dict):
        raise ValueError(f"Failed to fetch release for tag {tag}: {resp.status}")

    validated = validate_release_candidate(resp.body)
    if not validated:
        raise ValueError("Release validation failed during revalidaion")

    # Verify matching candidate fields: sha256, artifact_url, version
    if validated.sha256 != candidate_dict.get("sha256"):
        raise ValueError("SHA-256 mismatch during revalidaion")
    if validated.artifact_url != candidate_dict.get("artifact_url"):
        raise ValueError("Artifact URL mismatch during revalidaion")
    if validated.version != candidate_dict.get("version"):
        raise ValueError("Version mismatch during revalidaion")

    return {
        "version": validated.version,
        "tag": validated.tag,
        "channel": validated.channel,
        "artifact_url": validated.artifact_url,
        "sha256": validated.sha256,
        "release_url": validated.release_url,
        "published_at": validated.published_at,
        "action": candidate_dict.get("action", "update"),
    }


def set_update_channel(service: Any, channel: str) -> dict[str, Any]:
    if channel not in ("stable", "development"):
        channel = "stable"
    service._update_channel = channel
    service._save_state()
    service.log("info", f"Update channel set to {channel}")
    return service.get_settings()


def set_automatic_update_checks(service: Any, enabled: bool) -> dict[str, Any]:
    service._automatic_update_checks = bool(enabled)
    service._save_state()
    service.log("info", f"Automatic update checks {'enabled' if enabled else 'disabled'}")
    return service.get_settings()


def get_update_check_context(service: Any) -> dict[str, Any]:
    with service._state_lock:
        rate_limited_until_str = None
        if service._update_rate_limited_until:
            import datetime

            if datetime.datetime.now(datetime.timezone.utc) >= service._update_rate_limited_until:
                service._update_rate_limited_until = None
            else:
                rate_limited_until_str = service._update_rate_limited_until.isoformat()

        return {
            "update_channel": service._update_channel,
            "automatic_update_checks": service._automatic_update_checks,
            "installed_version": resolve_version(),
            "last_checked_at": service._update_check_cache.get("last_checked_at"),
            "last_checked_channel": service._update_check_cache.get("last_checked_channel"),
            "last_available_tag": service._update_check_cache.get("last_available_tag"),
            "last_notified_tag": service._update_check_cache.get("last_notified_tag"),
            "installed_release_tag": service._update_check_cache.get("installed_release_tag"),
            "installed_release_published_at": service._update_check_cache.get(
                "installed_release_published_at"
            ),
            "pending_update_install": service._update_check_cache.get("pending_update_install"),
            "rate_limited_until": rate_limited_until_str,
        }


def record_update_check_result(service: Any, result: dict[str, Any]) -> None:
    with service._state_lock:
        status = result.get("status")
        checked_at = result.get("checked_at")
        if status == "available":
            candidate = result.get("candidate", {})
            service._update_check_cache["last_checked_at"] = checked_at
            service._update_check_cache["last_checked_channel"] = service._update_channel
            service._update_check_cache["last_available_tag"] = candidate.get("tag")
        elif status == "current":
            service._update_check_cache["last_checked_at"] = checked_at
            service._update_check_cache["last_checked_channel"] = service._update_channel
        elif status == "failed":
            message = result.get("message")
            service.log("error", f"Update check failed: {message}")
            retry_after_str = result.get("retry_after")
            if retry_after_str:
                import datetime

                # Intentionally broad
                try:
                    service._update_rate_limited_until = datetime.datetime.fromisoformat(
                        retry_after_str
                    )
                # Intentionally broad
                except Exception:
                    pass
        service._save_state()


def record_update_install_requested(service: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    with service._state_lock:
        import datetime

        service._update_check_cache["pending_update_install"] = {
            "version": candidate.get("version"),
            "tag": candidate.get("tag"),
            "channel": candidate.get("channel"),
            "published_at": candidate.get("published_at"),
            "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        service._save_state()
        return get_update_check_context(service)


def reconcile_pending_update_install(service: Any, current_version: str) -> None:
    with service._state_lock:
        pending = service._update_check_cache.get("pending_update_install")
        if pending:
            pending_version = pending.get("version")
            if pending_version == current_version:
                service._update_check_cache["installed_release_tag"] = pending.get("tag")
                service._update_check_cache["installed_release_published_at"] = pending.get(
                    "published_at"
                )
            service._update_check_cache.pop("pending_update_install", None)
            service._save_state()


def revalidate_plugin_update(service: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    with service._state_lock:
        import datetime

        if service._update_rate_limited_until:
            if datetime.datetime.now(datetime.timezone.utc) < service._update_rate_limited_until:
                return {
                    "status": "failed",
                    "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "message": "Rate limit cooldown active",
                    "retry_after": service._update_rate_limited_until.isoformat(),
                }
            else:
                service._update_rate_limited_until = None

        tag = candidate.get("tag")
        if not tag:
            return {
                "status": "failed",
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": "Candidate missing tag",
            }

        url = f"https://api.github.com/repos/beallio/SDH-Ludusavi/releases/tags/{tag}"
        resp = fetch_json(url)

        if resp.status in (403, 429):
            retry_after_str = None
            if "retry-after" in resp.headers:
                # Intentionally broad
                try:
                    seconds = int(resp.headers["retry-after"])
                    retry_after_str = (
                        datetime.datetime.now(datetime.timezone.utc)
                        + datetime.timedelta(seconds=seconds)
                    ).isoformat()
                # Intentionally broad
                except Exception:
                    pass
            elif "x-ratelimit-reset" in resp.headers:
                # Intentionally broad
                try:
                    reset_ts = int(resp.headers["x-ratelimit-reset"])
                    retry_after_str = datetime.datetime.fromtimestamp(
                        reset_ts, datetime.timezone.utc
                    ).isoformat()
                # Intentionally broad
                except Exception:
                    pass

            if not retry_after_str:
                retry_after_str = (
                    datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)
                ).isoformat()

            # Intentionally broad
            try:
                service._update_rate_limited_until = datetime.datetime.fromisoformat(
                    retry_after_str
                )
            # Intentionally broad
            except Exception:
                pass
            service._save_state()

            msg = "Rate limit exceeded"
            if isinstance(resp.body, dict) and "message" in resp.body:
                msg = str(resp.body["message"])

            service.log("error", f"Revalidation failed due to rate limit: {msg}")

            return {
                "status": "failed",
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": msg,
                "retry_after": retry_after_str,
            }

        if resp.status != 200 or not isinstance(resp.body, dict):
            msg = f"Failed to fetch release for tag {tag}: {resp.status}"
            service.log("error", f"Revalidation check failed: {msg}")
            return {
                "status": "failed",
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": msg,
            }

        validated = validate_release_candidate(resp.body)
        if not validated:
            msg = "Release validation failed during revalidation"
            service.log("error", msg)
            return {
                "status": "failed",
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": msg,
            }

        if validated.sha256 != candidate.get("sha256"):
            msg = "SHA-256 mismatch during revalidation"
            service.log("error", msg)
            return {
                "status": "failed",
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": msg,
            }
        if validated.artifact_url != candidate.get("artifact_url"):
            msg = "Artifact URL mismatch during revalidation"
            service.log("error", msg)
            return {
                "status": "failed",
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": msg,
            }
        if validated.version != candidate.get("version"):
            msg = "Version mismatch during revalidation"
            service.log("error", msg)
            return {
                "status": "failed",
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": msg,
            }

        return {
            "version": validated.version,
            "tag": validated.tag,
            "channel": validated.channel,
            "artifact_url": validated.artifact_url,
            "sha256": validated.sha256,
            "release_url": validated.release_url,
            "published_at": validated.published_at,
            "action": candidate.get("action", "update"),
        }
