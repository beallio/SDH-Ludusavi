from __future__ import annotations

import json
from pathlib import Path

from sdh_ludusavi import _version


def write_release_metadata(root: Path, version: str = "0.1.0") -> None:
    (root / "plugin.json").write_text(
        json.dumps({"name": "SDH-ludusavi", "version": version}),
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"name": "sdh-ludusavi", "version": version}),
        encoding="utf-8",
    )


def test_resolve_version_prefers_vcs_dev_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_release_metadata(tmp_path, "0.1.0")
    monkeypatch.setattr(_version, "_python_package_version", lambda: "0.1.dev104+gabcdef")

    assert _version.resolve_version(tmp_path) == "0.1.dev104+gabcdef"


def test_resolve_version_uses_packaged_json_for_release_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_release_metadata(tmp_path, "0.1.0")
    monkeypatch.setattr(_version, "_python_package_version", lambda: "9.9.9")

    assert _version.resolve_version(tmp_path) == "0.1.0"


def test_resolve_version_has_deterministic_unknown_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(_version, "_python_package_version", lambda: "unknown")

    assert _version.resolve_version(tmp_path) == "unknown"
