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


def test_package_script_creates_exact_decky_plugin_zip(tmp_path: Path) -> None:
    module = load_package_module()

    subprocess.run(
        [sys.executable, "scripts/package_plugin.py", "--output-dir", str(tmp_path)],
        check=True,
    )

    zip_path = tmp_path / "SDH-Ludusavi.zip"
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        plugin_metadata = json.loads(archive.read("SDH-Ludusavi/plugin.json"))
        package_metadata = json.loads(archive.read("SDH-Ludusavi/package.json"))
        theme_manifest = json.loads(archive.read("SDH-Ludusavi/theme/theme.json"))

    mode = theme_manifest["patches"]["Save Status"]
    assert mode["type"] == "slider"
    assert mode["default"] == "Default"
    assert list(mode["values"]) == ["Default", "Clean View", "Custom"]
    assert mode["values"]["Default"] == {}
    colors = mode["components"]
    assert len(colors) == 4
    assert all(color["type"] == "color-picker" and color["on"] == "Custom" for color in colors)
    assert len({color["css_variable"] for color in colors}) == len(colors)
    outline = theme_manifest["patches"]["Outline Width"]
    assert outline["type"] == "slider"
    assert outline["values"][outline["default"]]["--sdh-status-outline-width"][0] == "0px"
    assert len(outline["values"]) >= 3
    assert "SDH-Ludusavi/theme/clean.css" in names
    assert "SDH-Ludusavi/theme/custom.css" in names

    assert all(name.startswith("SDH-Ludusavi/") for name in names)
    assert "SDH-Ludusavi/plugin.json" in names
    assert "SDH-Ludusavi/NOTICE.md" in names

    # Version should start with the repository's source version (the single
    # source of truth) and may include a git hash, so releases don't require
    # editing this test.
    assert plugin_metadata["version"].startswith(module.validate_package_versions(Path.cwd()))
    assert package_metadata["version"] == plugin_metadata["version"]
    assert "SDH-Ludusavi/dist/index.js" in names
    assert "SDH-Ludusavi/dist/index.js.map" in names
    for asset_prefix in [
        "SDH-Ludusavi/dist/assets/grid_p-",
        "SDH-Ludusavi/dist/assets/grid_l-",
        "SDH-Ludusavi/dist/assets/hero-",
        "SDH-Ludusavi/dist/assets/logo-",
    ]:
        assert any(name.startswith(asset_prefix) and name.endswith(".png") for name in names)
    assert "README.md" not in names
    assert "SDH-Ludusavi/README.md" not in names
    assert "src/index.tsx" not in names
    assert "SDH-Ludusavi/src/index.tsx" not in names
    assert "node_modules/.modules.yaml" not in names
    assert "SDH-Ludusavi/node_modules/.modules.yaml" not in names


def test_package_rejects_symlinked_theme_assets_outside_checkout(tmp_path: Path) -> None:
    module = load_package_module()
    project_root = tmp_path / "project"
    project_root.mkdir()
    for directory in module.REQUIRED_DIRECTORIES:
        (project_root / directory).mkdir(parents=True)
    outside = tmp_path / "private-data"
    outside.write_text("must not ship", encoding="utf-8")
    (project_root / "theme" / "extra.css").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        module.iter_required_plugin_paths(project_root)


def test_package_script_rebuilds_missing_runtime_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_package_module()
    project_root = tmp_path / "project"
    project_root.mkdir()

    for file_name in module.REQUIRED_FILES:
        target = project_root / file_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
    (project_root / "LICENSE").write_text("license", encoding="utf-8")

    build_calls: list[Path] = []

    def build_frontend_bundle(project_root_arg: Path) -> None:
        build_calls.append(project_root_arg)
        (project_root_arg / "dist").mkdir()
        (project_root_arg / "dist" / "index.js").write_text("bundle", encoding="utf-8")

    monkeypatch.setattr(module, "build_frontend_bundle", build_frontend_bundle)

    module.ensure_required_files(project_root)

    assert build_calls == [project_root]


def test_package_metadata_versions_match_release_version() -> None:
    module = load_package_module()
    plugin_metadata = json.loads(Path("plugin.json").read_text())
    package_metadata = json.loads(Path("package.json").read_text())

    # Derive the expected version from the single source of truth rather than
    # hardcoding it (releases shouldn't require editing this test). The call also
    # raises if plugin.json and package.json disagree.
    expected_version = module.validate_package_versions(Path.cwd())
    assert plugin_metadata["version"] == expected_version
    assert package_metadata["version"] == expected_version
    assert "_root" not in plugin_metadata.get("flags", [])
    assert "root" not in plugin_metadata["publish"]["tags"]


def test_package_validation_rejects_mismatched_metadata(tmp_path: Path) -> None:
    module = load_package_module()
    (tmp_path / "plugin.json").write_text(
        json.dumps({"name": "SDH-Ludusavi", "version": "0.1.0"}),
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


def test_package_script_supports_release_arguments(tmp_path: Path) -> None:
    import hashlib

    # Record source versions and ensure they aren't modified
    plugin_src = Path("plugin.json").read_text(encoding="utf-8")
    package_src = Path("package.json").read_text(encoding="utf-8")

    # Run release packaging with new args
    subprocess.run(
        [
            sys.executable,
            "scripts/package_plugin.py",
            "--release",
            "--release-version",
            "0.3.0",
            "--release-tag",
            "v0.3.0",
            "--versioned-output",
            "--emit-release-metadata",
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )

    # Ensure source JSONs are untouched
    assert Path("plugin.json").read_text(encoding="utf-8") == plugin_src
    assert Path("package.json").read_text(encoding="utf-8") == package_src

    zip_path = tmp_path / "SDH-Ludusavi-v0.3.0.zip"
    sha_path = tmp_path / "SDH-Ludusavi-v0.3.0.zip.sha256"
    manifest_path = tmp_path / "SDH-Ludusavi-v0.3.0.manifest.json"

    assert zip_path.exists()
    assert sha_path.exists()
    assert manifest_path.exists()

    # Verify checksum
    zip_bytes = zip_path.read_bytes()
    expected_sha = hashlib.sha256(zip_bytes).hexdigest()
    assert (
        sha_path.read_text(encoding="utf-8").strip() == f"{expected_sha}  SDH-Ludusavi-v0.3.0.zip"
    )

    # Verify manifest
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["schemaVersion"] == 1
    assert manifest_data["pluginName"] == "SDH-Ludusavi"
    assert manifest_data["packageName"] == "sdh-ludusavi"
    assert manifest_data["version"] == "0.3.0"
    assert manifest_data["sourceVersion"] == json.loads(plugin_src)["version"]
    assert manifest_data["tag"] == "v0.3.0"
    assert manifest_data["channel"] == "stable"
    assert manifest_data["assetName"] == "SDH-Ludusavi-v0.3.0.zip"
    assert manifest_data["sha256"] == expected_sha
    assert "generatedAt" in manifest_data

    # Verify contents of zip metadata
    with zipfile.ZipFile(zip_path) as archive:
        zip_plugin = json.loads(archive.read("SDH-Ludusavi/plugin.json"))
        zip_package = json.loads(archive.read("SDH-Ludusavi/package.json"))
        # Staged files must have the release version
        assert zip_plugin["version"] == "0.3.0"
        assert zip_package["version"] == "0.3.0"
        # Staged plugin.json must have the tag-stable Raw GitHub URL for the publish image
        assert (
            zip_plugin["publish"]["image"]
            == "https://raw.githubusercontent.com/beallio/SDH-Ludusavi/v0.3.0/assets/icon.png"
        )


def test_package_script_dev_prerelease(tmp_path: Path) -> None:
    # Run release packaging with a dev/prerelease version
    subprocess.run(
        [
            sys.executable,
            "scripts/package_plugin.py",
            "--release",
            "--release-version",
            "0.2.1-dev.55d87c6",
            "--versioned-output",
            "--emit-release-metadata",
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )

    zip_path = tmp_path / "SDH-Ludusavi-v0.2.1-dev.55d87c6.zip"
    manifest_path = tmp_path / "SDH-Ludusavi-v0.2.1-dev.55d87c6.manifest.json"

    assert zip_path.exists()
    assert manifest_path.exists()

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["version"] == "0.2.1-dev.55d87c6"
    assert manifest_data["tag"] == "v0.2.1-dev.55d87c6"
    assert manifest_data["channel"] == "dev"
    assert manifest_data["assetName"] == "SDH-Ludusavi-v0.2.1-dev.55d87c6.zip"


def test_release_zip_strips_debug_flag(tmp_path: Path) -> None:
    plugin_src = json.loads(Path("plugin.json").read_text(encoding="utf-8"))
    assert "debug" in plugin_src.get("flags", []), "precondition: repo keeps debug for dev"

    subprocess.run(
        [
            sys.executable,
            "scripts/package_plugin.py",
            "--release",
            "--release-version",
            "0.3.0",
            "--release-tag",
            "v0.3.0",
            "--versioned-output",
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )

    with zipfile.ZipFile(tmp_path / "SDH-Ludusavi-v0.3.0.zip") as archive:
        zip_plugin = json.loads(archive.read("SDH-Ludusavi/plugin.json"))

    # Shipping the debug flag makes Decky hot-reload the plugin on every file
    # event after install, which races import_plugin and orphans backend
    # processes (observed on Decky v3.2.4, 2026-06-12).
    assert "debug" not in zip_plugin.get("flags", [])
    # Source file stays untouched so the local push-to-deck dev loop keeps
    # watchdog hot-reload.
    assert "debug" in json.loads(Path("plugin.json").read_text(encoding="utf-8"))["flags"]


def test_local_zip_keeps_debug_flag(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "scripts/package_plugin.py", "--output-dir", str(tmp_path)],
        check=True,
    )

    with zipfile.ZipFile(tmp_path / "SDH-Ludusavi.zip") as archive:
        zip_plugin = json.loads(archive.read("SDH-Ludusavi/plugin.json"))

    assert "debug" in zip_plugin.get("flags", [])
