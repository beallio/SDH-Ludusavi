#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path

PROJECT_NAME = "SDH-Ludusavi"
ZIP_FILENAME = "SDH-Ludusavi.zip"
ARCHIVE_ROOT = "SDH-Ludusavi"

REQUIRED_FILES = (
    "LICENSE",
    "NOTICE",
    "main.py",
    "package.json",
    "plugin.json",
)
REQUIRED_RUNTIME_FILES = ("dist/index.js",)
REQUIRED_DIRECTORIES = (
    "dist",
    "py_modules/pyludusavi",
    "py_modules/pyludusavi-0.3.0.dist-info",
    "py_modules/sdh_ludusavi",
)
EXCLUDED_PARTS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def iter_required_plugin_paths(project_root: Path) -> tuple[str, ...]:
    plugin_paths = set(REQUIRED_FILES)

    for directory_name in REQUIRED_DIRECTORIES:
        directory = project_root / directory_name
        if not directory.is_dir():
            raise FileNotFoundError(f"Required plugin directory is missing: {directory_name}")

        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(project_root)
            if EXCLUDED_PARTS.intersection(relative.parts):
                continue
            if path.suffix in EXCLUDED_SUFFIXES:
                continue
            plugin_paths.add(relative.as_posix())

    return tuple(sorted(plugin_paths))


def iter_required_archive_names(project_root: Path) -> tuple[str, ...]:
    return tuple(
        f"{ARCHIVE_ROOT}/{plugin_path}" for plugin_path in iter_required_plugin_paths(project_root)
    )


def validate_required_files(project_root: Path) -> None:
    for file_name in REQUIRED_FILES + REQUIRED_RUNTIME_FILES:
        path = project_root / file_name
        if not path.is_file():
            raise FileNotFoundError(f"Required plugin file is missing: {file_name}")


def validate_static_files(project_root: Path) -> None:
    for file_name in REQUIRED_FILES:
        path = project_root / file_name
        if not path.is_file():
            raise FileNotFoundError(f"Required plugin file is missing: {file_name}")


def missing_runtime_files(project_root: Path) -> tuple[str, ...]:
    return tuple(
        file_name
        for file_name in REQUIRED_RUNTIME_FILES
        if not (project_root / file_name).is_file()
    )


def build_frontend_bundle(project_root: Path) -> None:
    subprocess.run(["pnpm", "run", "build"], cwd=project_root, check=True)


def ensure_required_files(project_root: Path, is_release: bool = False) -> None:
    validate_static_files(project_root)
    if not is_release or missing_runtime_files(project_root):
        build_frontend_bundle(project_root)
    validate_required_files(project_root)


def validate_package_versions(project_root: Path) -> str:
    plugin_version = _metadata_version(project_root / "plugin.json")
    package_version = _metadata_version(project_root / "package.json")

    missing = [
        file_name
        for file_name, metadata_version in (
            ("plugin.json", plugin_version),
            ("package.json", package_version),
        )
        if not metadata_version
    ]
    if missing:
        raise ValueError(f"Plugin metadata versions must be set in: {', '.join(missing)}")
    if plugin_version != package_version:
        raise ValueError(
            "Plugin metadata versions must match: "
            f"plugin.json={plugin_version}, package.json={package_version}"
        )
    return plugin_version


def _metadata_version(path: Path) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    value = data.get("version")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _get_git_hash() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode("ascii")
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def build_plugin_zip(
    project_root: Path,
    output_dir: Path,
    is_release: bool = False,
    release_version: str | None = None,
    release_tag: str | None = None,
    versioned_output: bool = False,
    emit_release_metadata: bool = False,
) -> Path:
    ensure_required_files(project_root, is_release=is_release)
    base_version = validate_package_versions(project_root)
    if release_version:
        version = release_version
    elif is_release:
        version = base_version
    else:
        git_hash = _get_git_hash()
        version = f"{base_version}+{git_hash}" if git_hash else base_version

    plugin_paths = iter_required_plugin_paths(project_root)

    output_dir.mkdir(parents=True, exist_ok=True)
    if versioned_output:
        zip_filename = f"SDH-Ludusavi-v{version}.zip"
    else:
        zip_filename = ZIP_FILENAME

    zip_path = output_dir / zip_filename
    temporary_zip_path = output_dir / f".{zip_filename}.tmp"

    if temporary_zip_path.exists():
        temporary_zip_path.unlink()

    with zipfile.ZipFile(temporary_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for plugin_path in plugin_paths:
            full_path = project_root / plugin_path
            archive_name = f"{ARCHIVE_ROOT}/{plugin_path}"

            if plugin_path in ("plugin.json", "package.json"):
                data = json.loads(full_path.read_text(encoding="utf-8"))
                data["version"] = version
                if plugin_path == "plugin.json" and is_release:
                    # The debug flag makes Decky hot-reload on every file
                    # event after install, racing import_plugin and orphaning
                    # backend processes (Decky v3.2.4, observed 2026-06-12).
                    # Local builds keep it for the push-to-deck dev loop.
                    flags = data.get("flags")
                    if isinstance(flags, list):
                        data["flags"] = [flag for flag in flags if flag != "debug"]
                if plugin_path == "plugin.json" and release_tag:
                    if "publish" in data and "image" in data["publish"]:
                        data["publish"]["image"] = (
                            f"https://raw.githubusercontent.com/beallio/SDH-Ludusavi/{release_tag}/assets/icon.png"
                        )
                archive.writestr(archive_name, json.dumps(data, indent=2))
            else:
                archive.write(full_path, archive_name)

    temporary_zip_path.replace(zip_path)

    if emit_release_metadata:
        import datetime
        import hashlib

        # Calculate SHA256
        sha256_hash = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        checksum = sha256_hash.hexdigest()

        # Write checksum file
        sha_path = output_dir / f"{zip_filename}.sha256"
        sha_path.write_text(f"{checksum}  {zip_filename}\n", encoding="utf-8")

        # Write manifest file
        tag = release_tag if release_tag else f"v{version}"
        channel = "dev" if "-" in version else "stable"
        manifest_data = {
            "schemaVersion": 1,
            "pluginName": PROJECT_NAME,
            "packageName": "sdh-ludusavi",
            "version": version,
            "sourceVersion": base_version,
            "tag": tag,
            "channel": channel,
            "assetName": zip_filename,
            "sha256": checksum,
            "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        manifest_path = output_dir / f"SDH-Ludusavi-v{version}.manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    return zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Decky plugin runtime zip.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing plugin runtime files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out"),
        help="Directory where SDH-Ludusavi.zip will be written.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Omit the git hash from the version string for release builds.",
    )
    parser.add_argument(
        "--release-version",
        type=str,
        help="Stamped version for release builds.",
    )
    parser.add_argument(
        "--release-tag",
        type=str,
        help="Release tag for manifest URL mapping.",
    )
    parser.add_argument(
        "--versioned-output",
        action="store_true",
        help="Output ZIP is named SDH-Ludusavi-v{VERSION}.zip.",
    )
    parser.add_argument(
        "--emit-release-metadata",
        action="store_true",
        help="Generate sha256 checksum and manifest files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir

    zip_path = build_plugin_zip(
        project_root,
        output_dir,
        is_release=args.release,
        release_version=args.release_version,
        release_tag=args.release_tag,
        versioned_output=args.versioned_output,
        emit_release_metadata=args.emit_release_metadata,
    )
    print(f"Created {zip_path}")


if __name__ == "__main__":
    main()
