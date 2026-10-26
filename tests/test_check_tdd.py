from __future__ import annotations

import subprocess
from pathlib import Path


GATE = Path(__file__).resolve().parents[1] / "scripts/check_tdd.sh"
SOURCE = "fn answer() -> u32 { 1 }\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn answer_works() { assert_eq!(super::answer(), 1); }\n}\n"


def git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


def test_tdd_gate_requires_a_test_for_rust_behavior(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    source = tmp_path / "backend/src/example.rs"
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE)
    git(tmp_path, "add", ".")
    git(
        tmp_path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )

    source.write_text(SOURCE.replace("{ 1 }", "{ 2 }"))
    git(tmp_path, "add", ".")
    result = subprocess.run(["bash", str(GATE)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert "test" in result.stderr.lower() or "test" in result.stdout.lower()

    source.write_text(SOURCE.replace("{ 1 }", "{ 2 }").replace("answer(), 1", "answer(), 2"))
    git(tmp_path, "add", ".")
    assert subprocess.run(["bash", str(GATE)], cwd=tmp_path).returncode == 0


def test_tdd_gate_accepts_contract_test_or_test_only_changes(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    source = tmp_path / "backend/src/example.rs"
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE)
    git(tmp_path, "add", ".")
    git(
        tmp_path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )

    source.write_text(SOURCE.replace("answer(), 1", "answer(), 2"))
    git(tmp_path, "add", ".")
    assert subprocess.run(["bash", str(GATE)], cwd=tmp_path).returncode == 0

    source.write_text(SOURCE.replace("{ 1 }", "{ 2 }"))
    contract = tmp_path / "tests/contract/test_example.py"
    contract.parent.mkdir(parents=True)
    contract.write_text("def test_answer():\n    assert True\n")
    git(tmp_path, "add", ".")
    assert subprocess.run(["bash", str(GATE)], cwd=tmp_path).returncode == 0
