import json
import tomllib
from pathlib import Path


def test_plans_directory():
    assert Path("docs/plans").exists()


def test_agents_file():
    assert Path("AGENTS.md").exists()


def test_decky_required_plugin_files_exist():
    for required_path in [
        "plugin.json",
        "package.json",
        "main.py",
        "LICENSE",
        "NOTICE",
        "rollup.config.js",
        "tsconfig.json",
        "src/index.tsx",
        "py_modules/sdh_ludusavi/service.py",
        "py_modules/pyludusavi/__init__.py",
        "py_modules/pyludusavi-0.3.0.dist-info/licenses/LICENSE",
    ]:
        assert Path(required_path).exists()


def test_project_license_metadata_is_mit() -> None:
    package_data = json.loads(Path("package.json").read_text(encoding="utf-8"))
    project_data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert package_data["license"] == "MIT"
    assert project_data["project"]["license"] == {"text": "MIT"}
    assert "License :: OSI Approved :: MIT License" in project_data["project"]["classifiers"]


def test_notice_preserves_project_lineage_and_design_credit() -> None:
    notice = Path("NOTICE").read_text(encoding="utf-8")
    license_text = Path("LICENSE").read_text(encoding="utf-8")

    assert "https://github.com/GedasFX/decky-ludusavi" in notice
    assert "originally began as a fork" in notice
    assert "https://github.com/AkazaRenn/SDH-GameSync" in notice
    assert "game-launch pause and pre-launch save-check concept" in notice
    assert "Copyright (c) 2024-2025, GedasFX" in license_text


def test_backend_package_uses_decky_py_modules_path():
    assert Path("py_modules/sdh_ludusavi").is_dir()
    assert Path("py_modules/pyludusavi").is_dir()
    assert not Path("src/sdh_ludusavi").exists()


def test_template_only_files_are_removed():
    for removed_path in [
        "backend",
        "defaults",
        "assets/logo.png",
        ".vscode/build.sh",
        ".vscode/setup.sh",
        ".vscode/defsettings.json",
    ]:
        assert not Path(removed_path).exists()


def test_tracked_pre_commit_hook_uses_current_project_checks():
    hook = Path("scripts/pre_commit.sh").read_text()

    assert "quality_gates.sh" in hook
    assert "git add -u" not in hook
    assert "git diff --cached --name-only --diff-filter=ACMR" in hook
    assert 'git add -- "${staged_paths[@]}"' in hook
    assert "./run.sh bash scripts/check_tdd.sh" in hook
