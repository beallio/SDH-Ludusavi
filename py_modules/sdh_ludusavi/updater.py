from __future__ import annotations

import datetime
import re
from contextlib import AbstractContextManager
from typing import Any, Callable, List, Literal, Mapping, cast
from dataclasses import dataclass

from sdh_ludusavi.updater_client import ReleaseClient
from sdh_ludusavi.updater_models import (
    ParsedPluginVersion,
    UpdateCandidate,
    parse_release_manifest,
    as_string_key_mapping,
)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-dev\.([a-zA-Z0-9.-]+))?(?:\+([a-zA-Z0-9.-]+))?$")
_PENDING_INSTALL_MISMATCH_GRACE = datetime.timedelta(minutes=15)
MAX_MANIFEST_FETCH_ATTEMPTS = 5


@dataclass(frozen=True)
class PrevalidatedRelease:
    record: Mapping[str, object]  # the original release JSON mapping
    tag_name: str
    version: ParsedPluginVersion  # parsed from tag_name[1:]
    published_at: str  # str(record.get("published_at", ""))
    prerelease: bool  # bool(record.get("prerelease", False))
    manifest_asset: Mapping[str, object]
    zip_asset: Mapping[str, object]


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


def _is_fresh_pending_install(pending: Any, now: Callable[[], datetime.datetime]) -> bool:
    if not isinstance(pending, dict):
        return False
    requested_at = (
        pending.get("handoff_confirmed_at")
        if _is_confirmed_pending_install(pending)
        else pending.get("requested_at")
    )
    if not isinstance(requested_at, str) or not requested_at:
        return False

    try:
        requested = datetime.datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    # Intentionally broad
    except Exception:
        return False

    if requested.tzinfo is None:
        requested = requested.replace(tzinfo=datetime.timezone.utc)
    return now() - requested <= _PENDING_INSTALL_MISMATCH_GRACE


def _is_confirmed_pending_install(pending: Any) -> bool:
    if not isinstance(pending, dict):
        return False
    confirmed_at = pending.get("handoff_confirmed_at")
    return isinstance(confirmed_at, str) and bool(confirmed_at)


def _pending_install_matches_loaded_version(pending_version: str, current_version: str) -> bool:
    if pending_version == current_version:
        return True

    parsed_pending = parse_plugin_version(pending_version)
    parsed_current = parse_plugin_version(current_version)
    if not parsed_pending or not parsed_current:
        return False

    if parsed_current.is_dev:
        return False

    if not parsed_pending.is_dev and parsed_pending == parsed_current:
        return True

    return False


def _effective_pending_install_version(
    pending: Any, now: Callable[[], datetime.datetime]
) -> str | None:
    if isinstance(pending, dict) and _is_fresh_pending_install(pending, now):
        version = pending.get("version")
        if isinstance(version, str) and version:
            return version
    return None


def prevalidate_release_candidate(release: object) -> PrevalidatedRelease | None:
    release_record = as_string_key_mapping(release)
    if release_record is None:
        return None
    if release_record.get("draft", False):
        return None

    tag_name = str(release_record.get("tag_name", ""))
    if not tag_name or not tag_name.startswith("v"):
        return None

    version_part = tag_name[1:]
    parsed_version = parse_plugin_version(version_part)
    if parsed_version is None:
        return None

    expected_manifest_name = f"SDH-Ludusavi-{tag_name}.manifest.json"

    assets = release_record.get("assets", [])
    if not isinstance(assets, list):
        return None
    manifest_assets = []
    zip_assets = []
    for a in assets:
        a_dict = as_string_key_mapping(a)
        if a_dict is not None:
            name = str(a_dict.get("name", ""))
            if name == expected_manifest_name:
                manifest_assets.append(a_dict)
            elif name.endswith(".zip"):
                zip_assets.append(a_dict)
    if len(manifest_assets) != 1:
        return None
    if len(zip_assets) != 1:
        return None

    manifest_asset = manifest_assets[0]
    zip_asset = zip_assets[0]

    published_at = str(release_record.get("published_at", ""))
    prerelease = bool(release_record.get("prerelease", False))

    return PrevalidatedRelease(
        record=release_record,
        tag_name=tag_name,
        version=parsed_version,
        published_at=published_at,
        prerelease=prerelease,
        manifest_asset=manifest_asset,
        zip_asset=zip_asset,
    )


def validate_prevalidated_candidate(
    pre: PrevalidatedRelease, client: ReleaseClient
) -> UpdateCandidate | None:
    resp = client.get_manifest(str(pre.manifest_asset.get("browser_download_url", "")))
    if resp.status != 200:
        return None

    manifest = parse_release_manifest(resp.body)
    if manifest is None:
        return None

    if manifest.plugin_name != "SDH-Ludusavi":
        return None
    if manifest.package_name != "sdh-ludusavi":
        return None
    if manifest.tag != pre.tag_name:
        return None
    if "v" + manifest.version != pre.tag_name:
        return None

    if manifest.channel == "stable" and pre.prerelease:
        return None
    if manifest.channel == "dev" and not pre.prerelease:
        return None

    if str(pre.zip_asset.get("name", "")) != manifest.asset_name:
        return None

    channel: Literal["stable", "development"] = (
        "stable" if manifest.channel == "stable" else "development"
    )
    return UpdateCandidate(
        version=manifest.version,
        tag=manifest.tag,
        channel=channel,
        artifact_url=str(pre.zip_asset.get("browser_download_url", "")),
        sha256=manifest.sha256,
        release_url=str(pre.record.get("html_url", "")),
        published_at=pre.published_at,
        action="update",
    )


def validate_release_candidate(release: object, client: ReleaseClient) -> UpdateCandidate | None:
    pre = prevalidate_release_candidate(release)
    if pre is None:
        return None
    return validate_prevalidated_candidate(pre, client)


def select_candidate(
    candidates: List[UpdateCandidate],
    installed_version_str: str,
    preferred_channel: Literal["stable", "development"],
) -> UpdateCandidate | None:
    installed_version = parse_plugin_version(installed_version_str)
    if not installed_version:
        return None

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

    def get_sort_key(c: UpdateCandidate) -> tuple[int, int, int, bool, str]:
        c_ver = parse_plugin_version(c.version)
        assert c_ver is not None
        return (c_ver.major, c_ver.minor, c_ver.patch, not c_ver.is_dev, c.published_at)

    eligible.sort(key=get_sort_key)
    best_candidate = eligible[-1]
    best_ver = parse_plugin_version(best_candidate.version)
    assert best_ver is not None

    is_upgrade = False
    action: Literal["update", "move_to_stable", "downgrade_to_stable"] = "update"

    best_base = (best_ver.major, best_ver.minor, best_ver.patch)
    installed_base = (installed_version.major, installed_version.minor, installed_version.patch)

    if preferred_channel == "stable" and installed_version.is_dev:
        is_upgrade = True
        if best_base == installed_base:
            action = "move_to_stable"
        elif best_base < installed_base:
            action = "downgrade_to_stable"
        else:
            action = "update"
    else:
        if best_ver > installed_version:
            is_upgrade = True
            if not best_ver.is_dev and installed_version.is_dev and best_base == installed_base:
                action = "move_to_stable"
        elif best_ver == installed_version:
            if best_ver.is_dev and installed_version.is_dev:
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


def format_candidate_log(candidate: Any) -> str:
    if not candidate:
        return "none"
    if not isinstance(candidate, dict):
        try:
            version = getattr(candidate, "version", "unknown")
            tag = getattr(candidate, "tag", "unknown")
            channel = getattr(candidate, "channel", "unknown")
            sha256 = getattr(candidate, "sha256", None)
            sha_prefix = sha256[:8] if (isinstance(sha256, str) and len(sha256) >= 8) else "unknown"
            return f"version={version}, tag={tag}, channel={channel}, sha256_prefix={sha_prefix}"
        # Intentionally broad
        except Exception:
            return "malformed candidate"
    version = candidate.get("version", "unknown")
    tag = candidate.get("tag", "unknown")
    channel = candidate.get("channel", "unknown")
    sha256 = candidate.get("sha256")
    sha_prefix = sha256[:8] if (isinstance(sha256, str) and len(sha256) >= 8) else "unknown"
    return f"version={version}, tag={tag}, channel={channel}, sha256_prefix={sha_prefix}"


class PluginUpdater:
    def __init__(
        self,
        *,
        state_lock: AbstractContextManager[object],
        save_callback: Callable[[], None],
        log_callback: Callable[[str, str], None],
        release_client: ReleaseClient,
        version_resolver: Callable[[], str],
        now: Callable[[], datetime.datetime],
        monotonic: Callable[[], float],
    ) -> None:
        self._state_lock = state_lock
        self._save_callback = save_callback
        self._log = log_callback
        self._client = release_client
        self._resolve_version = version_resolver
        self._now = now
        self._monotonic = monotonic

        self._channel = "stable"
        self._automatic_checks = True
        self._cache: dict[str, Any] = {}
        self._rate_limited_until: datetime.datetime | None = None

    def load_state(
        self,
        settings: Mapping[str, object],
        cache: Mapping[str, object],
    ) -> None:
        channel = settings.get("update_channel")
        self._channel = str(channel) if channel in ("stable", "development") else "stable"

        auto = settings.get("automatic_update_checks")
        self._automatic_checks = bool(auto) if isinstance(auto, bool) else True

        self._adopt_cache(cache)

    def adopt_persisted_cache(self, cache: Mapping[str, object]) -> None:
        """Replace update bookkeeping with a freshly persisted snapshot.

        Used before reconciling so a stale in-memory snapshot (taken before a
        concurrent instance promoted the pending install) is never acted on
        or written back.
        """
        with self._state_lock:
            self._adopt_cache(cache)

    def _adopt_cache(self, cache: Mapping[str, object]) -> None:
        c = cache.get("update_check_cache")
        if isinstance(c, dict):
            # Normalize cache fields
            self._cache = dict(c)
        else:
            self._cache = {}

        # Malformed pending install becomes absent
        pending = self._cache.get("pending_update_install")
        if pending is not None:
            if not isinstance(pending, dict) or "version" not in pending:
                self._cache.pop("pending_update_install", None)

        # Malformed timestamps
        for ts_key in ("last_checked_at", "installed_release_published_at"):
            ts_val = self._cache.get(ts_key)
            if ts_val is not None and not isinstance(ts_val, str):
                self._cache.pop(ts_key, None)

        # Invalid last_result
        if "last_result" in self._cache and not isinstance(self._cache["last_result"], dict):
            self._cache.pop("last_result", None)

    def settings_payload(self) -> dict[str, object]:
        return {
            "update_channel": self._channel,
            "automatic_update_checks": self._automatic_checks,
        }

    def cache_payload(self) -> dict[str, object]:
        return {
            "update_check_cache": self._cache,
        }

    def set_channel(self, channel: str) -> None:
        if channel not in ("stable", "development"):
            channel = "stable"
        self._channel = channel
        self._save_callback()
        self._log("info", f"Update channel set to {channel}")

    def set_automatic_checks(self, enabled: bool) -> None:
        self._automatic_checks = bool(enabled)
        self._save_callback()
        self._log("info", f"Automatic update checks {'enabled' if enabled else 'disabled'}")

    def get_context(self) -> dict[str, object]:
        with self._state_lock:
            rate_limited_until_str = None
            if self._rate_limited_until:
                if self._now() >= self._rate_limited_until:
                    self._rate_limited_until = None
                else:
                    rate_limited_until_str = self._rate_limited_until.isoformat()

            installed_version = self._resolve_version()
            pending_install = self._cache.get("pending_update_install")
            pending_version = _effective_pending_install_version(pending_install, self._now)

            return {
                "update_channel": self._channel,
                "automatic_update_checks": self._automatic_checks,
                "installed_version": installed_version,
                "effective_installed_version": pending_version or installed_version,
                "last_checked_at": self._cache.get("last_checked_at"),
                "last_checked_channel": self._cache.get("last_checked_channel"),
                "last_available_tag": self._cache.get("last_available_tag"),
                "last_notified_tag": self._cache.get("last_notified_tag"),
                "installed_release_tag": self._cache.get("installed_release_tag"),
                "installed_release_published_at": self._cache.get("installed_release_published_at"),
                "pending_update_install": pending_install,
                "rate_limited_until": rate_limited_until_str,
            }

    def _clear_stale_cache(self) -> None:
        self._cache.pop("last_result", None)
        self._cache.pop("last_available_tag", None)
        self._cache.pop("last_checked_version", None)

    def check_for_update(
        self,
        current_version: str,
        force: bool = False,
    ) -> dict[str, object]:
        self._log("info", f"Update check started (version={current_version}, force={force})")
        t0 = self._monotonic()

        with self._state_lock:
            if not force:
                pending_install = self._cache.get("pending_update_install")
                if pending_install:
                    effective_installed = _effective_pending_install_version(
                        pending_install, self._now
                    )
                    if effective_installed and effective_installed == current_version:
                        elapsed_ms = round((self._monotonic() - t0) * 1000)
                        self._log(
                            "info",
                            f"Update check pending-install fast path: pending={pending_install.get('version')}, current={current_version}, effective={effective_installed}, channel={self._channel}, force={force}, elapsed_ms={elapsed_ms}",
                        )
                        return {
                            "status": "current",
                            "checked_at": self._now().isoformat(),
                        }

            if self._rate_limited_until and self._now() < self._rate_limited_until:
                elapsed_ms = round((self._monotonic() - t0) * 1000)
                self._log(
                    "warning",
                    f"Update check blocked by rate-limit cooldown until {self._rate_limited_until.isoformat()}, elapsed_ms={elapsed_ms}",
                )
                return {
                    "status": "failed",
                    "checked_at": self._now().isoformat(),
                    "message": "Update check skipped due to rate-limit cooldown",
                    "retry_after": self._rate_limited_until.isoformat(),
                }

            if not force:
                last_checked_at_str = self._cache.get("last_checked_at")
                last_checked_channel = self._cache.get("last_checked_channel")
                last_checked_version = self._cache.get("last_checked_version")
                if isinstance(last_checked_at_str, str):
                    try:
                        last_checked_at = datetime.datetime.fromisoformat(last_checked_at_str)
                        if last_checked_at.tzinfo is None:
                            last_checked_at = last_checked_at.replace(tzinfo=datetime.timezone.utc)
                        if (
                            self._now() - last_checked_at < datetime.timedelta(hours=24)
                            and last_checked_channel == self._channel
                            and last_checked_version == current_version
                        ):
                            last_result = self._cache.get("last_result")
                            if isinstance(last_result, dict):
                                elapsed_ms = round((self._monotonic() - t0) * 1000)
                                self._log(
                                    "info",
                                    f"Update check cache hit (within 24h, channel={last_checked_channel}, version={last_checked_version}), elapsed_ms={elapsed_ms}",
                                )
                                return last_result
                    except (ValueError, TypeError):
                        pass

        self._log("info", "Fetching GitHub releases")
        t0 = self._monotonic()
        resp = self._client.list_releases()
        elapsed_ms = round((self._monotonic() - t0) * 1000)
        self._log(
            "info", f"GitHub releases fetch response: status={resp.status}, elapsed_ms={elapsed_ms}"
        )

        checked_at = self._now().isoformat()

        if resp.status in (403, 429):
            retry_after_str = None
            if "retry-after" in resp.headers:
                try:
                    seconds = int(resp.headers["retry-after"])
                    retry_after_str = (
                        self._now() + datetime.timedelta(seconds=seconds)
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
                retry_after_str = (self._now() + datetime.timedelta(minutes=1)).isoformat()

            msg = "Rate limit exceeded"
            body_record = as_string_key_mapping(resp.body)
            if body_record is not None and "message" in body_record:
                msg = str(body_record["message"])

            self._log(
                "warning",
                f"GitHub releases fetch rate-limited (status={resp.status}, message={msg}), elapsed_ms={elapsed_ms}",
            )

            with self._state_lock:
                try:
                    self._rate_limited_until = datetime.datetime.fromisoformat(retry_after_str)
                # Intentionally broad
                except Exception:
                    pass
                # Cooldown handling: do not overwrite successful result, only transient cooldown

            return {
                "status": "failed",
                "checked_at": checked_at,
                "message": msg,
                "retry_after": retry_after_str,
            }

        if resp.status != 200 or not isinstance(resp.body, list):
            msg = "Failed to check for updates"
            body_record = as_string_key_mapping(resp.body)
            if body_record is not None:
                if "message" in body_record:
                    msg = str(body_record["message"])
                elif "error" in body_record:
                    msg = str(body_record["error"])
            self._log(
                "error",
                f"GitHub releases fetch failed (status={resp.status}, message={msg}), elapsed_ms={elapsed_ms}",
            )
            return {
                "status": "failed",
                "checked_at": checked_at,
                "message": msg,
            }

        prevalidated: list[PrevalidatedRelease] = []
        t1 = self._monotonic()
        for r in resp.body:
            if not isinstance(r, dict):
                continue
            pre = prevalidate_release_candidate(r)
            if pre is None:
                continue
            if self._channel == "stable" and pre.prerelease:
                continue
            prevalidated.append(pre)

        prevalidated.sort(
            key=lambda p: (
                p.version.major,
                p.version.minor,
                p.version.patch,
                not p.version.is_dev,
                p.published_at,
            ),
            reverse=True,
        )

        candidates: list[UpdateCandidate] = []
        attempts = 0
        for pre in prevalidated:
            if attempts >= MAX_MANIFEST_FETCH_ATTEMPTS:
                self._log(
                    "warning",
                    f"Update check stopped after {MAX_MANIFEST_FETCH_ATTEMPTS} manifest validation attempts without a valid candidate",
                )
                break
            attempts += 1
            c = validate_prevalidated_candidate(pre, self._client)
            if c:
                candidates.append(c)
                break

        parse_elapsed_ms = round((self._monotonic() - t1) * 1000)

        self._log(
            "info",
            f"Prevalidated {len(prevalidated)} releases, manifest attempts={attempts}, valid={len(candidates)}, elapsed_ms={parse_elapsed_ms}",
        )

        t2 = self._monotonic()
        preferred_channel = cast(Literal["stable", "development"], self._channel)
        candidate = select_candidate(candidates, current_version, preferred_channel)
        select_elapsed_ms = round((self._monotonic() - t2) * 1000)

        result: dict[str, Any]
        if candidate:
            self._log(
                "info",
                f"Selected update candidate: {format_candidate_log(candidate)}, elapsed_ms={select_elapsed_ms}",
            )
            result = {
                "status": "available",
                "checked_at": checked_at,
                "checked_version": current_version,
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
        else:
            self._log(
                "info",
                f"No upgrade candidate found (already up to date), elapsed_ms={select_elapsed_ms}",
            )
            result = {
                "status": "current",
                "checked_at": checked_at,
                "checked_version": current_version,
                "channel": self._channel,
            }

        with self._state_lock:
            self._cache["last_checked_at"] = result["checked_at"]
            self._cache["last_checked_channel"] = self._channel
            self._cache["last_checked_version"] = current_version
            self._cache["last_result"] = result
            if candidate:
                self._cache["last_available_tag"] = candidate.tag
            self._save_callback()

        # Remove "checked_version" from returned payload to match previous API, it was only for caching.
        ret = dict(result)
        ret.pop("checked_version", None)
        return ret

    def revalidate(
        self,
        candidate: Mapping[str, object],
    ) -> dict[str, object]:
        t0 = self._monotonic()
        self._log("info", f"Revalidation started for candidate: {format_candidate_log(candidate)}")

        with self._state_lock:
            if self._rate_limited_until:
                if self._now() < self._rate_limited_until:
                    elapsed_ms = round((self._monotonic() - t0) * 1000)
                    self._log(
                        "warning",
                        f"Revalidation blocked by rate-limit cooldown until {self._rate_limited_until.isoformat()}, elapsed_ms={elapsed_ms}",
                    )
                    return {
                        "status": "failed",
                        "checked_at": self._now().isoformat(),
                        "message": "Rate limit cooldown active",
                        "retry_after": self._rate_limited_until.isoformat(),
                    }
                else:
                    self._rate_limited_until = None
                    self._save_callback()

        tag = candidate.get("tag")
        if not tag or not isinstance(tag, str):
            self._log("error", "Revalidation failed: Candidate missing tag")
            return {
                "status": "failed",
                "checked_at": self._now().isoformat(),
                "message": "Candidate missing tag",
            }

        self._log("info", f"Fetching candidate release for tag {tag}")
        t1 = self._monotonic()
        resp = self._client.get_release(tag)
        fetch_elapsed_ms = round((self._monotonic() - t1) * 1000)
        self._log(
            "info",
            f"Candidate release fetch response: status={resp.status}, elapsed_ms={fetch_elapsed_ms}",
        )

        if resp.status in (403, 429):
            retry_after_str = None
            if "retry-after" in resp.headers:
                try:
                    seconds = int(resp.headers["retry-after"])
                    retry_after_str = (
                        self._now() + datetime.timedelta(seconds=seconds)
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
                retry_after_str = (self._now() + datetime.timedelta(minutes=1)).isoformat()

            with self._state_lock:
                try:
                    self._rate_limited_until = datetime.datetime.fromisoformat(retry_after_str)
                # Intentionally broad
                except Exception:
                    pass
                self._save_callback()

            msg = "Rate limit exceeded"
            body_record = as_string_key_mapping(resp.body)
            if body_record is not None and "message" in body_record:
                msg = str(body_record["message"])

            self._log(
                "warning",
                f"Revalidation fetch rate-limited (status={resp.status}, message={msg}), elapsed_ms={fetch_elapsed_ms}",
            )

            return {
                "status": "failed",
                "checked_at": self._now().isoformat(),
                "message": msg,
                "retry_after": retry_after_str,
            }

        if resp.status != 200 or not isinstance(resp.body, dict):
            msg = f"Failed to fetch release for tag {tag}: {resp.status}"
            self._log("error", f"Revalidation check failed: {msg}, elapsed_ms={fetch_elapsed_ms}")
            return {
                "status": "failed",
                "checked_at": self._now().isoformat(),
                "message": msg,
            }

        validated = validate_release_candidate(resp.body, self._client)
        if not validated:
            msg = "Release validation failed during revalidation"
            elapsed_ms = round((self._monotonic() - t0) * 1000)
            self._log("error", f"{msg}, elapsed_ms={elapsed_ms}")
            return {
                "status": "failed",
                "checked_at": self._now().isoformat(),
                "message": msg,
            }

        cand_sha = candidate.get("sha256")
        cand_sha_prefix = cand_sha[:8] if isinstance(cand_sha, str) else "none"
        val_sha_prefix = validated.sha256[:8] if isinstance(validated.sha256, str) else "none"

        if validated.sha256 != candidate.get("sha256"):
            msg = f"SHA-256 mismatch during revalidation: candidate={cand_sha_prefix}, fetched={val_sha_prefix}"
            elapsed_ms = round((self._monotonic() - t0) * 1000)
            self._log("error", f"{msg}, elapsed_ms={elapsed_ms}")
            return {
                "status": "failed",
                "checked_at": self._now().isoformat(),
                "message": "SHA-256 mismatch during revalidation",
            }

        if validated.artifact_url != candidate.get("artifact_url"):
            cand_url = candidate.get("artifact_url")
            cand_url_prefix = str(cand_url)[:32] if cand_url else "none"
            val_url_prefix = validated.artifact_url[:32] if validated.artifact_url else "none"
            msg = f"Artifact URL mismatch during revalidation: candidate_prefix={cand_url_prefix}, fetched_prefix={val_url_prefix}"
            elapsed_ms = round((self._monotonic() - t0) * 1000)
            self._log("error", f"{msg}, elapsed_ms={elapsed_ms}")
            return {
                "status": "failed",
                "checked_at": self._now().isoformat(),
                "message": "Artifact URL mismatch during revalidation",
            }

        if validated.version != candidate.get("version"):
            msg = f"Version mismatch during revalidation: candidate={candidate.get('version')}, fetched={validated.version}"
            elapsed_ms = round((self._monotonic() - t0) * 1000)
            self._log("error", f"{msg}, elapsed_ms={elapsed_ms}")
            return {
                "status": "failed",
                "checked_at": self._now().isoformat(),
                "message": "Version mismatch during revalidation",
            }

        elapsed_ms = round((self._monotonic() - t0) * 1000)
        self._log(
            "info",
            f"Revalidation success for version v{validated.version}, elapsed_ms={elapsed_ms}",
        )
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

    def record_install_requested(
        self,
        candidate: Mapping[str, object],
    ) -> dict[str, object]:
        with self._state_lock:
            trace_id = candidate.get("updateTraceId")
            self._cache["pending_update_install"] = {
                "version": candidate.get("version"),
                "tag": candidate.get("tag"),
                "channel": candidate.get("channel"),
                "published_at": candidate.get("published_at"),
                "requested_at": self._now().isoformat(),
                "update_trace_id": trace_id,
            }
            self._clear_stale_cache()
            self._save_callback()
            self._log(
                "info",
                f"Pending install saved: version={candidate.get('version')}, "
                f"tag={candidate.get('tag')}, channel={candidate.get('channel')}, "
                f"action={candidate.get('action')}, trace_id={trace_id}",
            )
            return self.get_context()

    def confirm_install_handoff(self, version: str) -> dict[str, object]:
        with self._state_lock:
            pending = self._cache.get("pending_update_install")
            if isinstance(pending, dict) and pending.get("version") == version:
                pending["handoff_confirmed_at"] = self._now().isoformat()
                self._clear_stale_cache()
                self._save_callback()
                self._log("info", f"Pending install handoff confirmed: version={version}")
            else:
                self._log(
                    "warning", f"Pending install handoff confirmation ignored: version={version}"
                )
            return self.get_context()

    def clear_pending_install(self, version: str | None = None) -> dict[str, object]:
        with self._state_lock:
            pending = self._cache.get("pending_update_install")
            pending_version = pending.get("version") if isinstance(pending, dict) else None
            if pending and (version is None or pending_version == version):
                self._cache.pop("pending_update_install", None)
                self._clear_stale_cache()
                self._save_callback()
                self._log("info", f"Pending install cleared: version={pending_version}")
            return self.get_context()

    def reconcile_pending_install(self, current_version: str) -> None:
        with self._state_lock:
            pending = self._cache.get("pending_update_install")
            if pending:
                pending_version = pending.get("version")
                pending_tag = pending.get("tag")
                if pending_version and _pending_install_matches_loaded_version(
                    pending_version, current_version
                ):
                    self._cache["installed_release_tag"] = pending_tag
                    self._cache["installed_release_published_at"] = pending.get("published_at")
                    self._log(
                        "info",
                        f"Startup reconciliation: Pending update promoted (version={pending_version}, tag={pending_tag})",
                    )
                    self._cache.pop("pending_update_install", None)
                    self._clear_stale_cache()
                    self._save_callback()
                elif _is_fresh_pending_install(pending, self._now):
                    self._log(
                        "info",
                        f"Startup reconciliation: Pending update retained during reload grace window "
                        f"(pending={pending_version}, loaded={current_version})",
                    )
                else:
                    self._log(
                        "warning",
                        f"Startup reconciliation: Pending update cleared due to version mismatch "
                        f"(pending={pending_version}, loaded={current_version})",
                    )
                    self._cache.pop("pending_update_install", None)
                    self._clear_stale_cache()
                    self._save_callback()
            else:
                self._log("info", "Startup reconciliation: No pending update found")

    def has_pending_install(self) -> bool:
        with self._state_lock:
            pending = self._cache.get("pending_update_install")
            return _effective_pending_install_version(pending, self._now) is not None
