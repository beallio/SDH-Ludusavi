#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Decky plugin ZIP.")
    parser.add_argument("zip_path", type=Path, help="Path to the ZIP file to validate.")
    parser.add_argument("--expected-version", type=str, help="Expected version of the plugin.")
    parser.add_argument(
        "--expected-name", type=str, default="SDH-Ludusavi", help="Expected name of the plugin."
    )
    args = parser.parse_args()

    zip_path = args.zip_path
    if not zip_path.is_file():
        print(f"Error: ZIP file does not exist: {zip_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            namelist = archive.namelist()

            # 1. Exactly one top-level directory: expected-name/
            prefix = f"{args.expected_name}/"
            non_conforming = [name for name in namelist if not name.startswith(prefix)]
            if non_conforming:
                print(
                    f"Error: ZIP contains paths not starting with root directory '{prefix}': {non_conforming[:5]}",
                    file=sys.stderr,
                )
                sys.exit(1)

            if not namelist:
                print("Error: ZIP file is empty", file=sys.stderr)
                sys.exit(1)

            # 2. Required files must exist
            required_files = [
                "LICENSE",
                "main.py",
                "package.json",
                "plugin.json",
                "dist/index.js",
            ]
            for file_name in required_files:
                archive_path = f"{prefix}{file_name}"
                if archive_path not in namelist:
                    print(f"Error: Missing required file in ZIP: {archive_path}", file=sys.stderr)
                    sys.exit(1)

            # 3. Required directories
            required_dirs = [
                "py_modules/sdh_ludusavi/",
                "py_modules/pyludusavi/",
                "py_modules/pyludusavi-0.2.5.dist-info/",
            ]
            for dir_prefix in required_dirs:
                full_dir_prefix = f"{prefix}{dir_prefix}"
                if not any(name.startswith(full_dir_prefix) for name in namelist):
                    print(
                        f"Error: Missing required directory in ZIP: {full_dir_prefix}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            # 4. Forbidden paths
            forbidden_prefixes = [
                "node_modules/",
                "src/",
                "tests/",
                "docs/",
                ".git/",
                "__pycache__/",
                ".cache/",
                ".pytest_cache/",
                ".ruff_cache/",
                ".venv/",
                "backend/",
                "defaults/",
            ]
            for name in namelist:
                rel_path = name[len(prefix) :]
                if any(rel_path.startswith(f_pref) for f_pref in forbidden_prefixes):
                    print(f"Error: ZIP contains forbidden path: {name}", file=sys.stderr)
                    sys.exit(1)
                if rel_path.endswith(".pyc") or rel_path.endswith(".pyo"):
                    print(f"Error: ZIP contains forbidden file: {name}", file=sys.stderr)
                    sys.exit(1)

            # 5. Metadata verification
            plugin_json_path = f"{prefix}plugin.json"
            package_json_path = f"{prefix}package.json"

            plugin_data = json.loads(archive.read(plugin_json_path).decode("utf-8"))
            package_data = json.loads(archive.read(package_json_path).decode("utf-8"))

            plugin_name = plugin_data.get("name")
            if plugin_name != args.expected_name:
                print(
                    f"Error: plugin.json name '{plugin_name}' does not match expected '{args.expected_name}'",
                    file=sys.stderr,
                )
                sys.exit(1)

            plugin_version = plugin_data.get("version")
            package_version = package_data.get("version")
            if plugin_version != package_version:
                print(
                    f"Error: Version mismatch in ZIP: plugin.json={plugin_version}, package.json={package_version}",
                    file=sys.stderr,
                )
                sys.exit(1)

            if args.expected_version and plugin_version != args.expected_version:
                print(
                    f"Error: ZIP version '{plugin_version}' does not match expected '{args.expected_version}'",
                    file=sys.stderr,
                )
                sys.exit(1)

            publish_data = plugin_data.get("publish", {})
            image_url = publish_data.get("image", "")
            if "SteamDeckHomebrew/PluginLoader" in image_url:
                print(
                    "Error: plugin.json publish image still references SteamDeckHomebrew/PluginLoader",
                    file=sys.stderr,
                )
                sys.exit(1)

            flags = plugin_data.get("flags", [])
            if "_root" in flags:
                print("Error: plugin.json flags contains forbidden '_root'", file=sys.stderr)
                sys.exit(1)

    except zipfile.BadZipFile:
        print(f"Error: Bad ZIP file: {zip_path}", file=sys.stderr)
        sys.exit(1)

    print("Success: ZIP is valid and compliant!")


if __name__ == "__main__":
    main()
