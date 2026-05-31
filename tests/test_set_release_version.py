from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_set_version_rejects_non_stable_semver(tmp_path: Path) -> None:
    # 1. Create dummy plugin.json and package.json
    plugin_path = tmp_path / "plugin.json"
    package_path = tmp_path / "package.json"
    plugin_path.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    package_path.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")

    # 2. Try setting invalid / non-stable semver versions
    for invalid_version in ["0.2.1-dev.55d87c6", "0.2.1-alpha", "invalid", "1.2.3.4", "v1.2.3"]:
        res = subprocess.run(
            [
                sys.executable,
                "scripts/set_release_version.py",
                invalid_version,
                "--project-root",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0
        assert "stable" in res.stderr.lower() or "error" in res.stderr.lower()

        # Check version did not change
        assert json.loads(plugin_path.read_text(encoding="utf-8"))["version"] == "0.1.0"
        assert json.loads(package_path.read_text(encoding="utf-8"))["version"] == "0.1.0"


def test_set_version_updates_metadata_files(tmp_path: Path) -> None:
    # 1. Create dummy files
    plugin_path = tmp_path / "plugin.json"
    package_path = tmp_path / "package.json"
    plugin_path.write_text(
        json.dumps({"name": "SDH-Ludusavi", "version": "0.1.0"}, indent=2), encoding="utf-8"
    )
    package_path.write_text(
        json.dumps({"name": "sdh-ludusavi", "version": "0.1.0"}, indent=2), encoding="utf-8"
    )

    # 2. Run set_release_version
    res = subprocess.run(
        [
            sys.executable,
            "scripts/set_release_version.py",
            "0.2.1",
            "--project-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    # 3. Verify files updated
    plugin_data = json.loads(plugin_path.read_text(encoding="utf-8"))
    package_data = json.loads(package_path.read_text(encoding="utf-8"))

    assert plugin_data["version"] == "0.2.1"
    assert package_data["version"] == "0.2.1"

    # Make sure JSON formatting is preserved nicely (e.g. indentation)
    assert '"version": "0.2.1"' in plugin_path.read_text(encoding="utf-8")
    assert '"version": "0.2.1"' in package_path.read_text(encoding="utf-8")
