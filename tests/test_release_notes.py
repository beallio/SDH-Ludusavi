"""Tests for ``scripts/release_notes.py``.

Release notes are authored in-repo at ``docs/releases/vX.Y.Z.md`` and resolved at
publish time. When a release ships without an authored file the workflow must
fall back to GitHub's generated notes rather than publishing a blank body.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_notes.py"

NOTES = """# v1.2.3 — Something Useful

## Fixed

- A real bug.
"""


def _resolve(
    tag: str, repo_root: Path, out_dir: Path, github_output: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if github_output is not None:
        env["GITHUB_OUTPUT"] = str(github_output)
    else:
        env.pop("GITHUB_OUTPUT", None)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "resolve",
            tag,
            "--repo-root",
            str(repo_root),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def _outputs(text: str) -> dict[str, str]:
    pairs = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
    return pairs


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "releases").mkdir(parents=True)
    return tmp_path


def test_authored_notes_supply_title_and_body(repo: Path, tmp_path: Path) -> None:
    (repo / "docs" / "releases" / "v1.2.3.md").write_text(NOTES, encoding="utf-8")
    out_dir = tmp_path / "out"

    result = _resolve("v1.2.3", repo, out_dir)

    assert result.returncode == 0, result.stderr
    outputs = _outputs(result.stdout)
    assert outputs["title"] == "v1.2.3 — Something Useful"
    assert outputs["generate"] == "false"

    body = Path(outputs["body_path"]).read_text(encoding="utf-8")
    assert "A real bug." in body
    assert "# v1.2.3 — Something Useful" not in body, (
        "the H1 becomes the release title, not part of the body"
    )
    assert body.startswith("## Fixed"), "subheadings below the H1 are preserved"


def test_missing_notes_fall_back_to_generated(repo: Path, tmp_path: Path) -> None:
    result = _resolve("v9.9.9", repo, tmp_path / "out")

    assert result.returncode == 0, result.stderr
    outputs = _outputs(result.stdout)
    assert outputs["generate"] == "true"
    assert outputs["title"] == ""
    assert outputs["body_path"] == ""


def test_notes_without_heading_keep_full_body(repo: Path, tmp_path: Path) -> None:
    (repo / "docs" / "releases" / "v1.2.3.md").write_text(
        "Just a paragraph of notes.\n", encoding="utf-8"
    )
    out_dir = tmp_path / "out"

    result = _resolve("v1.2.3", repo, out_dir)

    outputs = _outputs(result.stdout)
    assert outputs["title"] == "", "no H1 means GitHub keeps its tag-name default"
    assert outputs["generate"] == "false"
    assert "Just a paragraph" in Path(outputs["body_path"]).read_text(encoding="utf-8")


def test_outputs_are_written_to_github_output(repo: Path, tmp_path: Path) -> None:
    (repo / "docs" / "releases" / "v1.2.3.md").write_text(NOTES, encoding="utf-8")
    github_output = tmp_path / "gh_output"
    github_output.write_text("", encoding="utf-8")

    _resolve("v1.2.3", repo, tmp_path / "out", github_output=github_output)

    written = _outputs(github_output.read_text(encoding="utf-8"))
    assert written["title"] == "v1.2.3 — Something Useful"
    assert written["generate"] == "false"
    assert written["body_path"].endswith(".md")


@pytest.mark.parametrize(
    "tag",
    ["0.4.2", "v1.2", "v1.2.3-dev.abc123", "../../etc/passwd", "v1.2.3/../../secrets", ""],
)
def test_malformed_tags_are_rejected(repo: Path, tmp_path: Path, tag: str) -> None:
    result = _resolve(tag, repo, tmp_path / "out")

    assert result.returncode != 0, f"tag {tag!r} must be rejected"
    assert "generate=" not in result.stdout


def test_release_notes_exist_for_every_stable_tag() -> None:
    """Backfilled and current releases keep their notes under version control."""
    releases = Path(__file__).resolve().parents[1] / "docs" / "releases"

    for tag in ("v0.4.0", "v0.4.1", "v0.4.2"):
        notes = releases / f"{tag}.md"
        assert notes.exists(), f"missing authored release notes for {tag}"
        assert notes.read_text(encoding="utf-8").startswith("# "), (
            f"{notes.name} must open with an H1 title line"
        )
