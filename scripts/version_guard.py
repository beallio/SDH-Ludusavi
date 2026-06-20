import sys
import re
import subprocess
from typing import Iterable


def parse_semver(text: str) -> tuple[int, int, int]:
    text = text.lstrip("v")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", text)
    if not match:
        raise ValueError(f"Invalid stable semver: {text}")

    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def highest_stable_version(tags: Iterable[str]) -> tuple[int, int, int] | None:
    max_version = None
    for tag in tags:
        try:
            ver = parse_semver(tag)
            if max_version is None or ver > max_version:
                max_version = ver
        except ValueError:
            pass
    return max_version


def is_base_ahead_of_stable(base: str, tags: Iterable[str]) -> bool:
    base_ver = parse_semver(base)
    max_stable = highest_stable_version(tags)

    if max_stable is None:
        return True

    return base_ver > max_stable


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "check-base":
        print("Usage: python version_guard.py check-base <BASE_VERSION>", file=sys.stderr)
        sys.exit(1)

    base_version = sys.argv[2]

    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True
        )
        tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        parse_semver(base_version)

        if not is_base_ahead_of_stable(base_version, tags):
            max_stable = highest_stable_version(tags)
            max_stable_str = (
                f"{max_stable[0]}.{max_stable[1]}.{max_stable[2]}" if max_stable else "unknown"
            )
            print(
                f"dev base {base_version} is not ahead of released stable {max_stable_str}; merge main into dev and bump package.json/plugin.json",
                file=sys.stderr,
            )
            sys.exit(1)

        sys.exit(0)
    except subprocess.CalledProcessError as e:
        print(f"Error running git tag: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error parsing version: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
