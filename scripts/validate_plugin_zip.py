#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
import sys
import zipfile
from pathlib import Path


def validate_static_elf(data: bytes) -> None:
    """Reject non-x86-64, malformed, or dynamically linked ELF executables."""
    error = "backend must be a statically linked x86_64 ELF executable"
    try:
        if len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01":
            raise ValueError(error)
        elf_type, machine = struct.unpack_from("<HH", data, 16)
        entrypoint = struct.unpack_from("<Q", data, 24)[0]
        phoff = struct.unpack_from("<Q", data, 32)[0]
        ehsize, phentsize, phnum = struct.unpack_from("<HHH", data, 52)
        if (
            elf_type not in (2, 3)
            or machine != 62
            or not entrypoint
            or ehsize != 64
            or phentsize < 56
            or not phnum
            or phoff + phentsize * phnum > len(data)
        ):
            raise ValueError(error)
        executable_load = False
        for index in range(phnum):
            offset = phoff + index * phentsize
            segment_type, flags = struct.unpack_from("<II", data, offset)
            segment_offset = struct.unpack_from("<Q", data, offset + 8)[0]
            segment_address = struct.unpack_from("<Q", data, offset + 16)[0]
            segment_size = struct.unpack_from("<Q", data, offset + 32)[0]
            if segment_offset + segment_size > len(data):
                raise ValueError(error)
            if segment_type == 3:
                raise ValueError(error)
            if (
                segment_type == 1
                and flags & 1
                and segment_address <= entrypoint < segment_address + segment_size
            ):
                executable_load = True
            if segment_type == 2:
                if segment_size % 16:
                    raise ValueError(error)
                for entry in range(segment_offset, segment_offset + segment_size, 16):
                    tag = struct.unpack_from("<q", data, entry)[0]
                    if tag == 1:
                        raise ValueError(error)
                    if tag == 0:
                        break
                else:
                    raise ValueError(error)
        if not executable_load:
            raise ValueError(error)
    except struct.error as exc:
        raise ValueError(error) from exc


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
                "NOTICE.md",
                "main.py",
                "package.json",
                "plugin.json",
                "README.md",
                "bin/backend",
                "theme/theme.json",
                "theme/clean.css",
                "theme/custom.css",
                "dist/index.js",
            ]
            for file_name in required_files:
                archive_path = f"{prefix}{file_name}"
                if archive_path not in namelist:
                    print(f"Error: Missing required file in ZIP: {archive_path}", file=sys.stderr)
                    sys.exit(1)

            # 3. Required directories
            required_dirs = ["theme/"]
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
                "py_modules/",
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
                if (
                    any(rel_path.startswith(f_pref) for f_pref in forbidden_prefixes)
                    or any(
                        part in {"__pycache__", ".cache", ".pytest_cache", ".ruff_cache", ".venv"}
                        for part in Path(rel_path).parts
                    )
                    or ".." in Path(rel_path).parts
                ):
                    print(f"Error: ZIP contains forbidden path: {name}", file=sys.stderr)
                    sys.exit(1)
                if rel_path.endswith(".pyc") or rel_path.endswith(".pyo"):
                    print(f"Error: ZIP contains forbidden file: {name}", file=sys.stderr)
                    sys.exit(1)

            backend_info = archive.getinfo(f"{prefix}bin/backend")
            if not (backend_info.external_attr >> 16) & 0o111:
                print("Error: bin/backend is not executable", file=sys.stderr)
                sys.exit(1)
            try:
                validate_static_elf(archive.read(backend_info))
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)

            # 5. Metadata verification
            plugin_json_path = f"{prefix}plugin.json"
            package_json_path = f"{prefix}package.json"

            plugin_data = json.loads(archive.read(plugin_json_path).decode("utf-8"))
            package_data = json.loads(archive.read(package_json_path).decode("utf-8"))
            if plugin_data.get("backend") != "bin/backend":
                print("Error: plugin.json backend must be bin/backend", file=sys.stderr)
                sys.exit(1)

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
