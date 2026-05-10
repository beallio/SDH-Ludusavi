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
        "rollup.config.js",
        "tsconfig.json",
        "src/index.tsx",
        "py_modules/sdh_ludusavi/service.py",
    ]:
        assert Path(required_path).exists()


def test_backend_package_uses_decky_py_modules_path():
    assert Path("py_modules/sdh_ludusavi").is_dir()
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
