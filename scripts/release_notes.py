"""Resolve authored release notes for a stable tag.

Notes live at ``docs/releases/vX.Y.Z.md``. The first line, when it is an H1,
becomes the GitHub release title; the rest becomes the body. When a release
ships without an authored file, the resolver asks the publish step to fall back
to GitHub's generated notes rather than publishing an empty body.

Stdlib only, like ``version_guard.py`` and ``set_release_version.py``, so it
runs before the project virtualenv exists.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
NOTES_DIR = Path("docs") / "releases"


def split_title_and_body(text: str) -> tuple[str, str]:
    """Split an authored notes file into its H1 title and remaining body."""
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).strip() + "\n"
    return "", text.strip() + "\n"


def resolve(tag: str, repo_root: Path, out_dir: Path) -> dict[str, str]:
    if not STABLE_TAG.match(tag):
        raise ValueError(f"Invalid stable release tag: {tag!r} (expected vX.Y.Z)")

    notes_path = repo_root / NOTES_DIR / f"{tag}.md"
    if not notes_path.is_file():
        return {"title": "", "body_path": "", "generate": "true"}

    title, body = split_title_and_body(notes_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    body_path = out_dir / f"release_notes_{tag}.md"
    body_path.write_text(body, encoding="utf-8")

    return {"title": title, "body_path": str(body_path), "generate": "false"}


def emit(outputs: dict[str, str]) -> None:
    rendered = "".join(f"{key}={value}\n" for key, value in outputs.items())

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(rendered)

    sys.stdout.write(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve", help="resolve notes for a stable tag")
    resolve_parser.add_argument("tag", help="stable release tag, e.g. v0.4.2")
    resolve_parser.add_argument("--repo-root", default=".", type=Path)
    resolve_parser.add_argument("--out-dir", default=Path("out"), type=Path)

    args = parser.parse_args(argv)

    try:
        outputs = resolve(args.tag, args.repo_root, args.out_dir)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    emit(outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
