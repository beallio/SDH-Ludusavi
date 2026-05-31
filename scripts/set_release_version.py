#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Set the release version in metadata files.")
    parser.add_argument("version", type=str, help="Stable semver version (e.g. 0.2.1).")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing package.json and plugin.json.",
    )
    args = parser.parse_args()

    # Validate version is a stable semantic version (X.Y.Z)
    if not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", args.version):
        print(
            f"Error: Version '{args.version}' is not a stable semantic version. Must match X.Y.Z.",
            file=sys.stderr,
        )
        sys.exit(1)

    project_root = args.project_root.resolve()
    plugin_path = project_root / "plugin.json"
    package_path = project_root / "package.json"

    if not plugin_path.is_file():
        print(f"Error: plugin.json not found at: {plugin_path}", file=sys.stderr)
        sys.exit(1)
    if not package_path.is_file():
        print(f"Error: package.json not found at: {package_path}", file=sys.stderr)
        sys.exit(1)

    try:
        plugin_data = json.loads(plugin_path.read_text(encoding="utf-8"))
        plugin_data["version"] = args.version
        plugin_path.write_text(json.dumps(plugin_data, indent=2) + "\n", encoding="utf-8")
        print(f"Updated plugin.json version to {args.version}")
    except Exception as e:
        print(f"Error updating plugin.json: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        package_data = json.loads(package_path.read_text(encoding="utf-8"))
        package_data["version"] = args.version
        package_path.write_text(json.dumps(package_data, indent=2) + "\n", encoding="utf-8")
        print(f"Updated package.json version to {args.version}")
    except Exception as e:
        print(f"Error updating package.json: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
