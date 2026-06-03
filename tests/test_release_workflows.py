from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def test_request_dev_release_rejects_non_stable_version(tmp_path: Path) -> None:
    # 1. Create a mock bin directory containing a mock git and mock gh
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    mock_gh = bin_dir / "gh"
    mock_gh.write_text("#!/bin/sh\necho 'auth ok'\nexit 0\n", encoding="utf-8")
    mock_gh.chmod(mock_gh.stat().st_mode | stat.S_IEXEC)

    # 2. Run the script with invalid versions
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    for invalid in ["0.2.1-alpha", "0.2.1-dev.55d87c6", "v1.2.3", "invalid"]:
        res = subprocess.run(
            ["bash", "scripts/request_dev_release.sh", invalid],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res.returncode != 0
        assert "stable" in res.stderr.lower() or "error" in res.stderr.lower()


def test_request_dev_release_calls_gh_workflow_run(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Mock gh to write its arguments to a temporary file
    gh_calls_log = tmp_path / "gh_calls.log"
    mock_gh = bin_dir / "gh"
    mock_gh.write_text(
        f"#!/bin/sh\n"
        f'if [ "$1" = "auth" ]; then echo "Logged in as user"; exit 0; fi\n'
        f'echo "$@" >> {gh_calls_log}\n'
        f"exit 0\n",
        encoding="utf-8",
    )
    mock_gh.chmod(mock_gh.stat().st_mode | stat.S_IEXEC)

    # Mock git to return a fixed commit hash
    mock_git = bin_dir / "git"
    mock_git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "rev-parse" ]; then echo "1234567890abcdef1234567890abcdef12345678"; exit 0; fi\n'
        "exit 1\n",
        encoding="utf-8",
    )
    mock_git.chmod(mock_git.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    # Run request_dev_release.sh with stable base version
    res = subprocess.run(
        ["bash", "scripts/request_dev_release.sh", "0.2.1"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, f"Script failed: {res.stderr}"

    # Verify gh was called with the resolved commit SHA and base version
    assert gh_calls_log.exists()
    calls = gh_calls_log.read_text(encoding="utf-8").strip()
    assert "workflow run dev-release.yml" in calls
    assert "-f commit=1234567890abcdef1234567890abcdef12345678" in calls
    assert "-f base_version=0.2.1" in calls


def test_request_dev_release_with_explicit_commit(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    gh_calls_log = tmp_path / "gh_calls.log"
    mock_gh = bin_dir / "gh"
    mock_gh.write_text(
        f"#!/bin/sh\n"
        f'if [ "$1" = "auth" ]; then echo "Logged in as user"; exit 0; fi\n'
        f'echo "$@" >> {gh_calls_log}\n'
        f"exit 0\n",
        encoding="utf-8",
    )
    mock_gh.chmod(mock_gh.stat().st_mode | stat.S_IEXEC)

    mock_git = bin_dir / "git"
    mock_git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "rev-parse" ]; then echo "abcdefabcdefabcdefabcdefabcdefabcdefabcdef"; exit 0; fi\n'
        "exit 1\n",
        encoding="utf-8",
    )
    mock_git.chmod(mock_git.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    # Run with explicit commit argument
    res = subprocess.run(
        ["bash", "scripts/request_dev_release.sh", "0.2.1", "abcdef"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, f"Script failed: {res.stderr}"

    assert gh_calls_log.exists()
    calls = gh_calls_log.read_text(encoding="utf-8").strip()
    assert "workflow run dev-release.yml" in calls
    assert "-f commit=abcdefabcdefabcdefabcdefabcdefabcdefabcdef" in calls
    assert "-f base_version=0.2.1" in calls


def test_workflows_trigger_and_overwrite_and_checksum_verification() -> None:
    # 1. Verify stable release trigger tag glob pattern
    release_content = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "tags:" in release_content
    assert "v*.*.*" in release_content
    assert "!v*.*.*-*" in release_content
    assert release_content.index("v*.*.*") < release_content.index("!v*.*.*-*")

    # 2. Verify dev-release.yml prerelease settings
    dev_content = Path(".github/workflows/dev-release.yml").read_text(encoding="utf-8")
    assert "prerelease: true" in dev_content
    assert (
        'SETUPTOOLS_SCM_PRETEND_VERSION="${{ env.BASE_VERSION }}" ./run.sh uv sync' in dev_content
    )

    # 3. Verify overwrite_files: false is set for release publishing in both workflows
    assert "overwrite_files: false" in release_content
    assert "overwrite_files: false" in dev_content

    # Ensure the incorrect 'overwrite: false' parameter is not used
    assert "overwrite: false" not in release_content
    assert "overwrite: false" not in dev_content

    # 4. Verify checksum verification sha256sum -c is executed in all workflows
    assert "sha256sum -c" in release_content
    assert "sha256sum -c" in dev_content

    ci_content = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "sha256sum -c" in ci_content
    assert "PKG_VER=$(jq -r .version package.json)" in ci_content
    assert 'SETUPTOOLS_SCM_PRETEND_VERSION="$PKG_VER" ./run.sh uv sync' in ci_content

    # 5. Verify absence of bad/lowercase asset names in all workflows
    for path, content in [
        (".github/workflows/release.yml", release_content),
        (".github/workflows/dev-release.yml", dev_content),
        (".github/workflows/ci.yml", ci_content),
    ]:
        assert "SDH-ludusavi.zip" not in content, f"Bad asset name found in {path}"


def test_workflows_use_node24_action_runtime_and_current_action_majors() -> None:
    workflows = {
        ".github/workflows/ci.yml": Path(".github/workflows/ci.yml").read_text(encoding="utf-8"),
        ".github/workflows/release.yml": Path(".github/workflows/release.yml").read_text(
            encoding="utf-8"
        ),
        ".github/workflows/dev-release.yml": Path(".github/workflows/dev-release.yml").read_text(
            encoding="utf-8"
        ),
    }

    for path, content in workflows.items():
        assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true" in content, (
            f"{path} must opt GitHub JavaScript actions into the Node 24 runtime"
        )
        assert "uses: actions/checkout@v6" in content
        assert "uses: actions/setup-node@v6" in content
        assert "uses: pnpm/action-setup@v6" in content
        assert "uses: actions/cache@v5" in content
        assert "uses: actions/setup-python@v6" in content
        assert "uses: astral-sh/setup-uv@v8.1.0" in content

    assert "uses: actions/upload-artifact@v7" in workflows[".github/workflows/ci.yml"]
    assert "uses: softprops/action-gh-release@v3" in workflows[".github/workflows/release.yml"]
    assert "uses: softprops/action-gh-release@v3" in workflows[".github/workflows/dev-release.yml"]
