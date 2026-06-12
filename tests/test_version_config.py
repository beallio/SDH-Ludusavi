import tomllib
from pathlib import Path


def test_vcs_version_config_excludes_dev_tags():
    """
    Asserts that the pyproject.toml hatch-vcs configuration explicitly excludes
    tags matching '*-dev*'.

    Why: Dev-release tags (e.g., 'v0.3.0-dev.g86c69a5') are not PEP-440
    compliant. If hatch-vcs matches them, parsing fails and breaks uv sync and
    pre-commit hooks.
    """
    pyproject_path = Path("pyproject.toml")
    assert pyproject_path.exists()

    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)

    hatch_version = pyproject.get("tool", {}).get("hatch", {}).get("version", {})
    assert hatch_version.get("source") == "vcs"

    raw_options = hatch_version.get("raw-options", {})
    describe_cmd = raw_options.get("git_describe_command", [])

    assert "--match" in describe_cmd, "Must use --match to restrict tag shapes"
    assert "--exclude" in describe_cmd, "Must use --exclude to filter out dev tags"

    exclude_idx = describe_cmd.index("--exclude")
    assert describe_cmd[exclude_idx + 1] == "*-dev*", "Must specifically exclude '*-dev*' tags"
