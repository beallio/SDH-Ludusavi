from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def test_validator_rejects_missing_native_backend(tmp_path: Path) -> None:
    zip_path = tmp_path / "missing-backend.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "SDH-Ludusavi/plugin.json",
            json.dumps(
                {
                    "name": "SDH-Ludusavi",
                    "version": "0.2.1",
                    "backend": "bin/backend",
                    "flags": [],
                }
            ),
        )
        archive.writestr("SDH-Ludusavi/package.json", json.dumps({"version": "0.2.1"}))
        for name in (
            "main.py",
            "LICENSE",
            "NOTICE.md",
            "README.md",
            "dist/index.js",
            "theme/theme.json",
        ):
            archive.writestr(f"SDH-Ludusavi/{name}", "fixture")
        for name in (
            "sdh_ludusavi",
            "pyludusavi",
            "pyludusavi-0.3.0.dist-info",
        ):
            archive.writestr(f"SDH-Ludusavi/py_modules/{name}/fixture.py", "")

    result = subprocess.run(
        [sys.executable, "scripts/validate_plugin_zip.py", str(zip_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "bin/backend" in result.stderr


@pytest.fixture(scope="module")
def packaged_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("native-package")
    subprocess.run(
        [sys.executable, "scripts/package_plugin.py", "--release", "--output-dir", str(output)],
        check=True,
    )
    return output / "SDH-Ludusavi.zip"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "bin/backend"),
        ("dynamic", "static"),
        ("invalid_entry", "static"),
        ("mode", "executable"),
        ("metadata", "backend"),
        ("py_modules", "forbidden"),
        ("backend_source", "forbidden"),
        ("cache", "forbidden"),
        ("node_modules", "forbidden"),
        ("root", "_root"),
    ],
)
def test_validator_rejects_native_package_mutations(
    packaged_zip: Path, tmp_path: Path, mutation: str, message: str
) -> None:
    mutated = tmp_path / "mutated.zip"
    with zipfile.ZipFile(packaged_zip) as original, zipfile.ZipFile(mutated, "w") as result:
        for info in original.infolist():
            data = original.read(info)
            if info.filename == "SDH-Ludusavi/bin/backend":
                if mutation == "missing":
                    continue
                if mutation == "dynamic":
                    data = Path("/bin/ls").read_bytes()
                if mutation == "invalid_entry":
                    data = data[:24] + b"\0" * 8 + data[32:]
                if mutation == "mode":
                    info.external_attr = 0o100644 << 16
            if info.filename == "SDH-Ludusavi/plugin.json" and mutation in ("metadata", "root"):
                metadata = json.loads(data)
                if mutation == "metadata":
                    metadata.pop("backend")
                else:
                    metadata["flags"] = ["_root"]
                data = json.dumps(metadata).encode()
            result.writestr(info, data)
        extra = {
            "py_modules": "py_modules/legacy.py",
            "backend_source": "backend/src/main.rs",
            "cache": "dist/__pycache__/leaked",
            "node_modules": "node_modules/some-lib/index.js",
        }.get(mutation)
        if extra:
            result.writestr(f"SDH-Ludusavi/{extra}", "")

    check = subprocess.run(
        [sys.executable, "scripts/validate_plugin_zip.py", str(mutated)],
        capture_output=True,
        text=True,
    )
    assert check.returncode != 0
    assert message.lower() in check.stderr.lower()


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
