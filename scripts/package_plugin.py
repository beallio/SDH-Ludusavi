#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path

PROJECT_NAME = "SDH-ludusavi"
ZIP_FILENAME = "SDH-ludusavi.zip"
ARCHIVE_ROOT = "SDH-ludusavi"

REQUIRED_FILES = (
    "LICENSE",
    "main.py",
    "package.json",
    "plugin.json",
)
REQUIRED_RUNTIME_FILES = ("dist/index.js",)
REQUIRED_DIRECTORIES = (
    "dist",
    "py_modules/pyludusavi",
    "py_modules/pyludusavi-0.2.2.dist-info",
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


def build_plugin_zip(project_root: Path, output_dir: Path) -> Path:
    validate_required_files(project_root)
    base_version = validate_package_versions(project_root)
    git_hash = _get_git_hash()
    version = f"{base_version}+{git_hash}" if git_hash else base_version

    plugin_paths = iter_required_plugin_paths(project_root)

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / ZIP_FILENAME
    temporary_zip_path = output_dir / f".{ZIP_FILENAME}.tmp"

    if temporary_zip_path.exists():
        temporary_zip_path.unlink()

    with zipfile.ZipFile(temporary_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for plugin_path in plugin_paths:
            full_path = project_root / plugin_path
            archive_name = f"{ARCHIVE_ROOT}/{plugin_path}"

            if plugin_path in ("plugin.json", "package.json"):
                data = json.loads(full_path.read_text(encoding="utf-8"))
                data["version"] = version
                archive.writestr(archive_name, json.dumps(data, indent=2))
            else:
                archive.write(full_path, archive_name)

    temporary_zip_path.replace(zip_path)
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
        help="Directory where SDH-ludusavi.zip will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir

    zip_path = build_plugin_zip(project_root, output_dir)
    print(f"Created {zip_path}")


if __name__ == "__main__":
    main()
