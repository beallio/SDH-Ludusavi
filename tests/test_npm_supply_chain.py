from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_package_json_without_duplicate_keys() -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        data: dict[str, object] = {}
        for key, value in pairs:
            assert key not in data, f"duplicate key in package.json: {key}"
            data[key] = value
        return data

    return json.loads(
        (ROOT / "package.json").read_text(encoding="utf-8"),
        object_pairs_hook=no_duplicates,
    )


def test_package_json_uses_pnpm_and_exact_dependency_versions() -> None:
    package = load_package_json_without_duplicate_keys()

    assert package["private"] is True
    assert package["packageManager"] == "pnpm@10.23.0"

    dependencies = package["dependencies"]
    dev_dependencies = package["devDependencies"]
    assert isinstance(dependencies, dict)
    assert isinstance(dev_dependencies, dict)
    assert "react-router" in dependencies
    assert "@types/webpack" not in dev_dependencies

    for dependency_set in (dependencies, dev_dependencies):
        for package_name, specifier in dependency_set.items():
            assert isinstance(specifier, str), package_name
            assert not specifier.startswith(("^", "~", ">", "<", "*")), package_name


def test_package_json_exposes_frontend_supply_chain_scripts() -> None:
    package = load_package_json_without_duplicate_keys()

    scripts = package["scripts"]
    assert isinstance(scripts, dict)
    assert scripts["typecheck"] == "tsc --noEmit"
    assert scripts["audit"] == "pnpm audit --audit-level high"
    assert scripts["test"] == "pnpm run typecheck"
    assert scripts["verify"] == "bash scripts/check_frontend_supply_chain.sh"


def test_npmrc_contains_required_security_defaults() -> None:
    npmrc = (ROOT / ".npmrc").read_text(encoding="utf-8")

    for required_line in [
        "package-lock=true",
        "save-exact=true",
        "audit=true",
        "fund=false",
        "ignore-scripts=true",
        "min-release-age=14d",
    ]:
        assert required_line in npmrc


def test_pnpm_workspace_contains_supply_chain_policy() -> None:
    workspace = (ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8")

    for required_text in [
        "minimumReleaseAge: 20160",
        "storeDir: /tmp/sdh_ludusavi/.pnpm-store",
        "virtualStoreDir: /tmp/sdh_ludusavi/pnpm-virtual-store",
        "sideEffectsCache: false",
        "picomatch@^4.0.0: 4.0.4",
        "picomatch@^2.0.0: 2.3.2",
        "brace-expansion@^2.0.0: 2.0.3",
        "minimatch@^3.0.0: 3.1.5",
        "minimatch@^9.0.0: 9.0.9",
    ]:
        assert required_text in workspace


def test_pnpm_install_script_checker_rejects_unapproved_build_scripts(
    tmp_path: Path,
) -> None:
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text(
        """
lockfileVersion: '9.0'
packages:
  native-addon@1.0.0:
    resolution: {integrity: sha512-example}
    requiresBuild: true
""".strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_pnpm_install_scripts.py"),
            str(lockfile),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "native-addon@1.0.0" in result.stdout


def test_frontend_supply_chain_script_runs_audit_before_install() -> None:
    source = (ROOT / "scripts" / "check_frontend_supply_chain.sh").read_text(encoding="utf-8")

    pre_install_audit = source.index("pnpm audit --audit-level high")
    install = source.index("pnpm install --frozen-lockfile --ignore-scripts")
    assert pre_install_audit < install
    assert "scripts/check_pnpm_install_scripts.py pnpm-lock.yaml" in source
    assert "npx " not in source


def test_local_hooks_run_frontend_supply_chain_checks() -> None:
    pre_commit = (ROOT / "scripts" / "pre_commit.sh").read_text(encoding="utf-8")
    post_commit = (ROOT / "scripts" / "post_commit.sh").read_text(encoding="utf-8")

    assert "pnpm run verify" in pre_commit
    assert "pnpm run verify" in post_commit
    assert "./node_modules/.bin/rollup" not in post_commit


def test_known_package_lock_gap_is_documented() -> None:
    review = (ROOT / "docs" / "review" / "npm_known_potential_vulnerability.md").read_text(
        encoding="utf-8"
    )

    assert "Known Potential Vulnerability" in review
    assert "package-lock.json" in review
    assert "pnpm-lock.yaml" in review
