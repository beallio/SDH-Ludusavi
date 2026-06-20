import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts.package_plugin import validate_package_versions
from scripts.version_guard import highest_stable_version, is_version_behind_stable


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


def test_dev_version_not_behind_stable():
    """
    Asserts the project's declared version (package.json/plugin.json) is not strictly
    behind the highest released stable tag. This guards against version drift on the
    dev branch (declared < highest stable) while allowing equality, which is the valid
    state during and immediately after a stable release of that version.

    Strict-ahead enforcement for *dispatching a dev release* lives in Guard A
    (`request_dev_release.sh` / `version_guard.is_base_ahead_of_stable`) and is not run
    during a stable release's quality gates. This test runs in every quality-gates
    context (dev, dev-release, and the stable release itself), so it must allow the
    declared version to equal the tag being released.

    Requires git tags to be fetched to run correctly. Skips if no stable tags exist.
    """
    # 1. Read declared version
    declared_version = validate_package_versions(Path.cwd())

    # 2. Get tags
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True
        )
        tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to run git tag: {e}")

    # 3. Check if there are stable tags at all
    if highest_stable_version(tags) is None:
        pytest.skip("No stable tags found; skipping drift check.")

    # 4. Assert dev version is not behind the highest stable tag (equality is allowed)
    assert not is_version_behind_stable(declared_version, tags), (
        f"Declared version {declared_version} is behind the highest stable tag. "
        f"Ensure dev is merged with main and the version is bumped."
    )
