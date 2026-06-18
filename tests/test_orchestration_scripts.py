"""Behavioral tests for the orchestration helper scripts.

These drive the real scripts under ``scripts/orchestration`` inside a throwaway
git repository so the resume-loop hardening (implementer exits per round,
committed-note trust, and a content-addressed round-complete marker) stays
correct.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ORCH = Path(__file__).resolve().parents[1] / "scripts" / "orchestration"
SLUG = "demo-feature"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _run(script: str, *args: str, repo: Path, env: dict[str, str] | None = None):
    full_env = dict(os.environ)
    full_env["ORCH_TMP_ROOT"] = str(repo / ".orch_tmp")
    if env:
        full_env.update(env)
    return subprocess.run(
        [str(ORCH / script), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=full_env,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    (tmp_path / "docs" / "review").mkdir(parents=True)
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / ".orch_tmp").mkdir(parents=True)
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _write_note(repo: Path, round_no: int, status: str) -> Path:
    note = repo / "docs" / "review" / f"{SLUG}-review-{round_no:02d}.md"
    note.write_text(f"# Review\n\nbody\n\nSTATUS: {status}\n", encoding="utf-8")
    return note


def _commit(repo: Path, path: Path, message: str) -> None:
    subprocess.run(["git", "add", str(path.relative_to(repo))], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)


# --- #1: resume-driven loop (implementer exits per round) -------------------


def test_implementer_prompts_are_resume_driven() -> None:
    start = (ORCH / "start-implementer").read_text(encoding="utf-8")
    cont = (ORCH / "continue-implementer").read_text(encoding="utf-8")

    # The implementer must be told to exit after marking a round complete,
    # not to linger and poll for review notes in-session.
    assert "exit cleanly" in start
    assert "exit cleanly" in cont
    assert "remain active" not in start
    assert "remains active" not in cont


# --- #2: review-status trusts only committed notes --------------------------


def test_review_status_ignores_uncommitted_note(repo: Path) -> None:
    _write_note(repo, 1, "APPROVED")  # written but NOT committed
    result = _run("review-status", SLUG, repo=repo)
    assert result.returncode == 0
    assert result.stdout.strip() == "NO_REVIEW"


def test_review_status_reads_committed_note(repo: Path) -> None:
    note = _write_note(repo, 1, "APPROVED")
    _commit(repo, note, "review 01")
    result = _run("review-status", SLUG, repo=repo)
    assert result.stdout.strip() == "APPROVED"


def test_review_status_uses_latest_committed_only(repo: Path) -> None:
    note1 = _write_note(repo, 1, "CHANGES_REQUESTED")
    _commit(repo, note1, "review 01")
    # A newer note exists in the working tree but is not committed yet.
    _write_note(repo, 2, "APPROVED")
    result = _run("review-status", SLUG, repo=repo)
    assert result.stdout.strip() == "CHANGES_REQUESTED"


# --- #4: content-addressed round-complete marker ---------------------------


def test_mark_finished_writes_head_sha(repo: Path) -> None:
    result = _run("mark-finished", SLUG, repo=repo)
    assert result.returncode == 0, result.stderr
    marker = repo / ".orch_tmp" / f"{SLUG}_finished"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == _git(repo, "rev-parse", "HEAD")


def test_wait_for_finished_since_blocks_on_stale_marker(repo: Path) -> None:
    stale = _git(repo, "rev-parse", "HEAD")
    _run("mark-finished", SLUG, repo=repo)  # marker now holds `stale`
    # With ORCH_FINISHED_SINCE == stale, the marker is stale -> should time out.
    result = _run(
        "wait-for-finished",
        SLUG,
        "2",
        repo=repo,
        env={"ORCH_FINISHED_SINCE": stale, "POLL_SECS": "1"},
    )
    assert result.returncode != 0


def test_wait_for_finished_since_returns_on_new_marker(repo: Path) -> None:
    stale = _git(repo, "rev-parse", "HEAD")
    # Advance HEAD so a fresh mark-finished records a different sha.
    (repo / "README.md").write_text("seed\nmore\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-aqm", "advance"], cwd=repo, check=True)
    _run("mark-finished", SLUG, repo=repo)
    result = _run(
        "wait-for-finished",
        SLUG,
        "5",
        repo=repo,
        env={"ORCH_FINISHED_SINCE": stale, "POLL_SECS": "1"},
    )
    assert result.returncode == 0
