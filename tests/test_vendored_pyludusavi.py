import re
import tomllib
from pathlib import Path


def test_exactly_one_dist_info():
    """Assert there is only one vendored version of pyludusavi."""
    dirs = sorted(Path("py_modules").glob("pyludusavi-*.dist-info"))
    assert len(dirs) == 1, f"Expected exactly 1 dist-info directory, found {len(dirs)}"


def test_pin_matches_vendored_version():
    """Assert the vendored pyludusavi version matches the pin in pyproject.toml."""
    dirs = sorted(Path("py_modules").glob("pyludusavi-*.dist-info"))
    assert len(dirs) == 1
    metadata_path = dirs[0] / "METADATA"

    vendored_version = None
    with open(metadata_path, "r") as f:
        for line in f:
            if line.startswith("Version: "):
                vendored_version = line.strip().split("Version: ")[1]
                break

    assert vendored_version is not None, "Failed to read version from METADATA"
    assert dirs[0].name == f"pyludusavi-{vendored_version}.dist-info"

    with open("pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)

    dependencies = pyproject.get("project", {}).get("dependencies", [])
    pyludusavi_dep = next((dep for dep in dependencies if dep.startswith("pyludusavi")), None)
    assert pyludusavi_dep is not None, "pyludusavi not found in pyproject.toml dependencies"

    match = re.search(r"pyludusavi\s*[><=~!]+=?\s*([0-9][0-9a-zA-Z.]*)", pyludusavi_dep)
    assert match is not None, f"Could not parse version from dependency string: {pyludusavi_dep}"
    pin_version = match.group(1)

    assert vendored_version == pin_version, (
        f"Vendored version {vendored_version} does not match pin {pin_version}"
    )


def test_upstream_timeout_behavior_present():
    """
    Assert the upstream discovery timeout is present in pyludusavi.
    """
    discovery_path = Path("py_modules/pyludusavi/discovery.py")
    assert discovery_path.exists(), "discovery.py not found in vendored pyludusavi"

    content = discovery_path.read_text()
    assert "SDH-Ludusavi local patch" not in content, "Local patch marker must be absent"
    assert "_DISCOVERY_VERIFY_TIMEOUT_SECONDS = 15.0" in content, (
        "Upstream timeout constant missing"
    )
    assert content.count("timeout=_DISCOVERY_VERIFY_TIMEOUT_SECONDS") == 2, (
        "Upstream timeout constant not passed to subprocess calls"
    )
    assert "subprocess.TimeoutExpired" in content, "TimeoutExpired must be handled"
