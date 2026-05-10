from pathlib import Path


def test_plans_directory():
    assert Path("docs/plans").exists()


def test_agents_file():
    assert Path("AGENTS.md").exists()
