from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def load_package_module():
    spec = importlib.util.spec_from_file_location("package_plugin", "scripts/package_plugin.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_script_defines_decky_runtime_files_only() -> None:
    module = load_package_module()

    assert module.PROJECT_NAME == "SDH-ludusavi"
    assert module.ZIP_FILENAME == "SDH-ludusavi.zip"
    assert module.ARCHIVE_ROOT == "SDH-ludusavi"
    assert module.REQUIRED_FILES == (
        "LICENSE",
        "main.py",
        "package.json",
        "plugin.json",
    )
    assert module.REQUIRED_RUNTIME_FILES == ("dist/index.js",)
    assert module.REQUIRED_DIRECTORIES == (
        "dist",
        "py_modules/pyludusavi",
        "py_modules/pyludusavi-0.1.1.dist-info",
        "py_modules/sdh_ludusavi",
    )


def test_package_script_creates_exact_decky_plugin_zip(tmp_path: Path) -> None:
    module = load_package_module()

    subprocess.run(
        [sys.executable, "scripts/package_plugin.py", "--output-dir", str(tmp_path)],
        check=True,
    )

    zip_path = tmp_path / "SDH-ludusavi.zip"
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        plugin_metadata = json.loads(archive.read("SDH-ludusavi/plugin.json"))
        package_metadata = json.loads(archive.read("SDH-ludusavi/package.json"))

    assert names == set(module.iter_required_archive_names(Path.cwd()))
    assert all(name.startswith("SDH-ludusavi/") for name in names)
    assert "SDH-ludusavi/plugin.json" in names
    assert plugin_metadata["version"] == "0.1.0"
    assert package_metadata["version"] == "0.1.0"
    assert "SDH-ludusavi/dist/index.js" in names
    assert "SDH-ludusavi/dist/index.js.map" in names
    assert "README.md" not in names
    assert "SDH-ludusavi/README.md" not in names
    assert "src/index.tsx" not in names
    assert "SDH-ludusavi/src/index.tsx" not in names
    assert "docs/plans/sdh_ludusavi.md" not in names
    assert "SDH-ludusavi/docs/plans/sdh_ludusavi.md" not in names
    assert "node_modules/.modules.yaml" not in names
    assert "SDH-ludusavi/node_modules/.modules.yaml" not in names


def test_package_metadata_versions_match_release_version() -> None:
    module = load_package_module()
    plugin_metadata = json.loads(Path("plugin.json").read_text())
    package_metadata = json.loads(Path("package.json").read_text())

    assert plugin_metadata["version"] == "0.1.0"
    assert package_metadata["version"] == "0.1.0"
    assert "_root" not in plugin_metadata.get("flags", [])
    assert "root" not in plugin_metadata["publish"]["tags"]
    assert module.validate_package_versions(Path.cwd()) == "0.1.0"


def test_package_validation_rejects_mismatched_metadata(tmp_path: Path) -> None:
    module = load_package_module()
    (tmp_path / "plugin.json").write_text(
        json.dumps({"name": "SDH-ludusavi", "version": "0.1.0"}),
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "sdh-ludusavi", "version": "0.1.1"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Plugin metadata versions must match"):
        module.validate_package_versions(tmp_path)


def test_post_commit_script_builds_the_project_zip() -> None:
    source = Path("scripts/post_commit.sh").read_text()

    assert "./run.sh uv run python scripts/package_plugin.py" in source
