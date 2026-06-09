from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Literal, Mapping
from typing import cast

UpdateChannel = Literal["stable", "development"]
UpdateAction = Literal["update", "move_to_stable", "downgrade_to_stable"]


@dataclass(frozen=True)
class JsonResponse:
    status: int
    headers: Mapping[str, str]
    body: object


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
    channel: UpdateChannel
    artifact_url: str
    sha256: str
    release_url: str
    published_at: str
    action: UpdateAction


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


_SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


def as_string_key_mapping(payload: object) -> Mapping[str, object] | None:
    if isinstance(payload, dict) and all(isinstance(k, str) for k in payload):
        return cast(Mapping[str, object], payload)
    return None


def parse_release_manifest(payload: object) -> ReleaseManifest | None:
    record = as_string_key_mapping(payload)
    if record is None:
        return None

    schema_version = record.get("schemaVersion")
    plugin_name = record.get("pluginName")
    package_name = record.get("packageName")
    version = record.get("version")
    source_version = record.get("sourceVersion")
    tag = record.get("tag")
    channel = record.get("channel")
    asset_name = record.get("assetName")
    sha256 = record.get("sha256")
    generated_at = record.get("generatedAt")

    if not isinstance(schema_version, int):
        return None
    if not isinstance(plugin_name, str):
        return None
    if not isinstance(package_name, str):
        return None
    if not isinstance(version, str):
        return None
    if not isinstance(source_version, str):
        return None
    if not isinstance(tag, str):
        return None
    if channel not in ("stable", "dev"):
        return None
    if not isinstance(asset_name, str):
        return None
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        return None
    if not isinstance(generated_at, str):
        return None

    return ReleaseManifest(
        schema_version=schema_version,
        plugin_name=plugin_name,
        package_name=package_name,
        version=version,
        source_version=source_version,
        tag=tag,
        channel=channel,  # type: ignore
        asset_name=asset_name,
        sha256=sha256,
        generated_at=generated_at,
    )


@dataclass
class UpdaterCacheModel:
    last_checked_at: str | None = None
    last_checked_channel: str | None = None
    last_checked_version: str | None = None
    last_available_tag: str | None = None
    last_notified_tag: str | None = None
    last_result: Mapping[str, object] | None = None
    pending_update_install: Mapping[str, object] | None = None
    extras: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: object) -> UpdaterCacheModel:
        record = as_string_key_mapping(payload)
        if not record:
            return cls()

        m = cls()
        for k, v in record.items():
            if k == "last_checked_at":
                m.last_checked_at = v if isinstance(v, str) else None
            elif k == "last_checked_channel":
                m.last_checked_channel = (
                    v if isinstance(v, str) and v in ("stable", "development") else None
                )
            elif k == "last_checked_version":
                m.last_checked_version = v if isinstance(v, str) else None
            elif k == "last_available_tag":
                m.last_available_tag = v if isinstance(v, str) else None
            elif k == "last_notified_tag":
                m.last_notified_tag = v if isinstance(v, str) else None
            elif k == "last_result":
                m.last_result = as_string_key_mapping(v) if isinstance(v, dict) else None
            elif k == "pending_update_install":
                m.pending_update_install = as_string_key_mapping(v) if isinstance(v, dict) else None
            else:
                m.extras[k] = v
        return m

    def to_dict(self) -> dict[str, object]:
        res: dict[str, object] = {}
        if self.last_checked_at is not None:
            res["last_checked_at"] = self.last_checked_at
        if self.last_checked_channel is not None:
            res["last_checked_channel"] = self.last_checked_channel
        if self.last_checked_version is not None:
            res["last_checked_version"] = self.last_checked_version
        if self.last_available_tag is not None:
            res["last_available_tag"] = self.last_available_tag
        if self.last_notified_tag is not None:
            res["last_notified_tag"] = self.last_notified_tag
        if self.last_result is not None:
            res["last_result"] = self.last_result
        if self.pending_update_install is not None:
            res["pending_update_install"] = self.pending_update_install
        res.update(self.extras)
        return res
