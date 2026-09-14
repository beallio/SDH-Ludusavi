"""Behavioral tests for the repository's private orchestration-run contract."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ORCH = Path(__file__).resolve().parents[1] / "scripts" / "orchestration"
pytestmark = pytest.mark.skipif(
    not (ORCH / "mark-finished").exists(),
    reason="orchestration scripts are a local-only symlink (../agent-orchestration); absent on CI runners",
)
SLUG = "demo-feature"


def _run(script: str, *args: str, repo: Path, env: dict[str, str] | None = None):
    full_env = dict(os.environ)
    full_env.pop("ORCH_TMP_ROOT", None)
    full_env.pop("ORCH_STATE_ROOT", None)
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
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _start_run(repo: Path) -> dict[str, object]:
    created = _run("new-plan", SLUG, "Demo feature", repo=repo)
    assert created.returncode == 0, created.stderr
    state = _run("status", SLUG, "--json", repo=repo)
    assert state.returncode == 0, state.stderr
    run = json.loads(state.stdout)
    subprocess.run(["git", "checkout", "-qb", f"feat/{SLUG}"], cwd=repo, check=True)
    return run


def test_new_plan_is_private_and_status_exposes_its_identity(repo: Path) -> None:
    run = _start_run(repo)
    assert run["phase"] == "PLANNED"
    assert run["round"] == 1
    assert isinstance(run["run_id"], str) and len(run["run_id"]) == 32
    assert str(run["plan"]).startswith(str(repo / ".git"))
    assert not (repo / "docs" / "plans").exists()


def test_mark_finished_requires_the_current_identity_and_records_reviewable_head(
    repo: Path,
) -> None:
    run = _start_run(repo)
    stale = _run("mark-finished", SLUG, "--run-id", "0" * 32, "--round", "1", repo=repo)
    assert stale.returncode != 0
    result = _run(
        "mark-finished",
        SLUG,
        "--run-id",
        str(run["run_id"]),
        "--round",
        str(run["round"]),
        repo=repo,
    )
    assert result.returncode == 0, result.stderr
    status = json.loads(_run("status", SLUG, "--json", repo=repo).stdout)
    assert status["phase"] == "AWAITING_REVIEW"
    assert status["finished"]["valid"] is True
    assert status["finished"]["sha"] == status["head"]


def test_wait_for_finished_observes_the_private_state_transition(repo: Path) -> None:
    run = _start_run(repo)
    finished = _run(
        "mark-finished",
        SLUG,
        "--run-id",
        str(run["run_id"]),
        "--round",
        str(run["round"]),
        repo=repo,
    )
    assert finished.returncode == 0, finished.stderr
    waited = _run(
        "wait-for-finished",
        SLUG,
        "2",
        "--run-id",
        str(run["run_id"]),
        "--round",
        str(run["round"]),
        repo=repo,
        env={"POLL_SECS": "1"},
    )
    assert waited.returncode == 0, waited.stderr
    assert waited.stdout.strip() == f"round ready: {SLUG}"
