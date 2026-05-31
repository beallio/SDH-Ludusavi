from __future__ import annotations

import functools
import re
from dataclasses import dataclass


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
