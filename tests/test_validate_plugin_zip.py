from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


def test_validator_accepts_valid_zip(tmp_path: Path) -> None:
    # 1. Create a valid zip using the packager script
    subprocess.run(
        [
            sys.executable,
            "scripts/package_plugin.py",
            "--release",
            "--release-version",
            "0.2.1",
            "--versioned-output",
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )
    zip_path = tmp_path / "SDH-Ludusavi-v0.2.1.zip"
    assert zip_path.exists()

    # 2. Run validator (this will fail initially because the validator script doesn't exist)
    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_plugin_zip.py",
            str(zip_path),
            "--expected-version",
            "0.2.1",
            "--expected-name",
            "SDH-Ludusavi",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Validator failed: {res.stderr}"


def test_validator_rejects_invalid_zip(tmp_path: Path) -> None:
    # Create an invalid zip manually
    zip_path = tmp_path / "invalid.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        # missing expected root directory, files are top-level
        archive.writestr("plugin.json", json.dumps({"name": "SDH-Ludusavi", "version": "0.2.1"}))
        archive.writestr("package.json", json.dumps({"version": "0.2.1"}))
        archive.writestr("main.py", "# main")
        archive.writestr("LICENSE", "BSD")
        archive.writestr("dist/index.js", "// index")

    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_plugin_zip.py",
            str(zip_path),
            "--expected-version",
            "0.2.1",
            "--expected-name",
            "SDH-Ludusavi",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "root" in res.stderr.lower() or "root" in res.stdout.lower()


def test_validator_rejects_missing_required_files(tmp_path: Path) -> None:
    zip_path = tmp_path / "missing_files.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        # correct root, but missing main.py
        archive.writestr(
            "SDH-Ludusavi/plugin.json", json.dumps({"name": "SDH-Ludusavi", "version": "0.2.1"})
        )
        archive.writestr("SDH-Ludusavi/package.json", json.dumps({"version": "0.2.1"}))
        archive.writestr("SDH-Ludusavi/LICENSE", "BSD")
        archive.writestr("SDH-Ludusavi/dist/index.js", "// index")

    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_plugin_zip.py",
            str(zip_path),
            "--expected-version",
            "0.2.1",
            "--expected-name",
            "SDH-Ludusavi",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "missing" in res.stderr.lower() or "missing" in res.stdout.lower()


def test_validator_rejects_missing_notice(tmp_path: Path) -> None:
    zip_path = tmp_path / "missing_notice.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "SDH-Ludusavi/plugin.json",
            json.dumps(
                {
                    "name": "SDH-Ludusavi",
                    "version": "0.2.1",
                    "flags": [],
                    "publish": {},
                }
            ),
        )
        archive.writestr("SDH-Ludusavi/package.json", json.dumps({"version": "0.2.1"}))
        archive.writestr("SDH-Ludusavi/main.py", "# main")
        archive.writestr("SDH-Ludusavi/LICENSE", "MIT")
        archive.writestr("SDH-Ludusavi/dist/index.js", "// index")
        archive.writestr("SDH-Ludusavi/py_modules/sdh_ludusavi/dummy.py", "# dummy")
        archive.writestr("SDH-Ludusavi/py_modules/pyludusavi/dummy.py", "# dummy")
        archive.writestr(
            "SDH-Ludusavi/py_modules/pyludusavi-0.3.0.dist-info/dummy.py",
            "# dummy",
        )

    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_plugin_zip.py",
            str(zip_path),
            "--expected-version",
            "0.2.1",
            "--expected-name",
            "SDH-Ludusavi",
        ],
        capture_output=True,
        text=True,
    )

    assert res.returncode != 0
    assert "NOTICE.md" in res.stderr or "NOTICE.md" in res.stdout


def test_validator_rejects_forbidden_paths(tmp_path: Path) -> None:
    zip_path = tmp_path / "forbidden.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "SDH-Ludusavi/plugin.json", json.dumps({"name": "SDH-Ludusavi", "version": "0.2.1"})
        )
        archive.writestr("SDH-Ludusavi/package.json", json.dumps({"version": "0.2.1"}))
        archive.writestr("SDH-Ludusavi/main.py", "# main")
        archive.writestr("SDH-Ludusavi/LICENSE", "BSD")
        archive.writestr("SDH-Ludusavi/NOTICE.md", "notices")
        archive.writestr("SDH-Ludusavi/dist/index.js", "// index")
        archive.writestr("SDH-Ludusavi/py_modules/sdh_ludusavi/dummy.py", "# dummy")
        archive.writestr("SDH-Ludusavi/py_modules/pyludusavi/dummy.py", "# dummy")
        archive.writestr("SDH-Ludusavi/py_modules/pyludusavi-0.3.0.dist-info/dummy.py", "# dummy")
        # forbidden node_modules folder
        archive.writestr("SDH-Ludusavi/node_modules/some-lib/index.js", "// lib")

    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_plugin_zip.py",
            str(zip_path),
            "--expected-version",
            "0.2.1",
            "--expected-name",
            "SDH-Ludusavi",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "forbidden" in res.stderr.lower() or "forbidden" in res.stdout.lower()


def test_validator_rejects_casing_bugs(tmp_path: Path) -> None:
    # 1. Create a zip with lowercase root folder SDH-ludusavi/ instead of SDH-Ludusavi/
    zip_path = tmp_path / "SDH-ludusavi.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "SDH-ludusavi/plugin.json", json.dumps({"name": "SDH-Ludusavi", "version": "0.2.1"})
        )
        archive.writestr("SDH-ludusavi/package.json", json.dumps({"version": "0.2.1"}))
        archive.writestr("SDH-ludusavi/main.py", "# main")
        archive.writestr("SDH-ludusavi/LICENSE", "BSD")
        archive.writestr("SDH-ludusavi/dist/index.js", "// index")
        archive.writestr("SDH-ludusavi/py_modules/sdh_ludusavi/dummy.py", "# dummy")
        archive.writestr("SDH-ludusavi/py_modules/pyludusavi/dummy.py", "# dummy")
        archive.writestr("SDH-ludusavi/py_modules/pyludusavi-0.3.0.dist-info/dummy.py", "# dummy")

    # Run validator with --expected-name SDH-Ludusavi
    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_plugin_zip.py",
            str(zip_path),
            "--expected-version",
            "0.2.1",
            "--expected-name",
            "SDH-Ludusavi",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    # Must fail because expected-name is SDH-Ludusavi but root folder is SDH-ludusavi/
    assert "starting with root directory" in res.stderr.lower()
