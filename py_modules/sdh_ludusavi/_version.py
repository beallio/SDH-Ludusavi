from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT_DISTRIBUTION_NAME = "SDH-ludusavi"
UNKNOWN_VERSION = "unknown"


def resolve_version(project_root: Path | None = None) -> str:
    python_version = _python_package_version()
    if _is_vcs_dev_version(python_version):
        return python_version

    release_version = _packaged_release_version(project_root or _project_root())
    if release_version:
        return release_version

    return python_version or UNKNOWN_VERSION


def _python_package_version() -> str:
    try:
        return version(PROJECT_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


def _is_vcs_dev_version(candidate: str) -> bool:
    return candidate != UNKNOWN_VERSION and ".dev" in candidate


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _packaged_release_version(project_root: Path) -> str | None:
    plugin_version = _json_version(project_root / "plugin.json")
    package_version = _json_version(project_root / "package.json")
    if plugin_version and package_version and plugin_version == package_version:
        return plugin_version
    return None


def _json_version(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    value = data.get("version")
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    return stripped or None


__version__ = resolve_version()
