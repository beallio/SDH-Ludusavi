#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


APPROVED_BUILD_PACKAGES: set[str] = set()


def packages_requiring_build(lockfile: Path) -> list[str]:
    offenders: list[str] = []
    current_package: str | None = None

    for line in lockfile.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped.endswith(":"):
            current_package = None
            continue
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            current_package = stripped[:-1].strip("'\"")
            continue
        if current_package and stripped == "requiresBuild: true":
            offenders.append(current_package)

    return offenders


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail if pnpm-lock.yaml contains unapproved build/install scripts."
    )
    parser.add_argument(
        "lockfile",
        nargs="?",
        type=Path,
        default=Path("pnpm-lock.yaml"),
        help="pnpm lockfile to inspect.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    offenders = [
        package
        for package in packages_requiring_build(args.lockfile)
        if package not in APPROVED_BUILD_PACKAGES
    ]
    if not offenders:
        print("No unapproved pnpm packages require build/install scripts.")
        return 0

    print("Unapproved pnpm packages require build/install scripts:")
    for package in offenders:
        print(f"- {package}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
