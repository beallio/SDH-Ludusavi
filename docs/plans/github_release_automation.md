# GitHub Release Automation

## Problem Definition
The current release process requires manual generation of the plugin zip file. We want to automate this process so that creating a GitHub release (e.g., via the `gh` CLI) automatically builds the frontend, packages the plugin, and attaches the resulting zip file to the release. Additionally, local builds currently append the git commit hash to the version string. We need to ensure that automated release builds use the strict version number without the commit hash, while local builds continue to include it for debugging purposes. Furthermore, the local build script currently pushes to a hardcoded local IP address; this needs to be updated to use the configured SSH host alias `steamdeck`.

## Architecture Overview
1.  **Packaging Script (`scripts/package_plugin.py`)**: Will be updated to accept a `--release` flag. When this flag is provided, the script will omit the git commit hash from the version string in `plugin.json` and `package.json` inside the generated zip.
2.  **GitHub Actions Workflow (`.github/workflows/release.yml`)**: A new workflow will be created. It will trigger on the `release: published` event, build the project (frontend and Python requirements), run the packaging script with the `--release` flag, and upload the zip to the GitHub release.
3.  **Agent Protocol (`AGENTS.md`)**: The repository's operational contract will be updated to document the release packaging workflow, specifically instructing agents on when to use the `--release` flag versus standard local builds.
4.  **Post-Commit Script (`scripts/post_commit.sh`)**: The local `scp` command will be updated to target `steamdeck:/home/deck/Downloads/` instead of `deck@10.168.168.20:/home/deck/Downloads/`, and the ping check will be updated or removed to rely directly on SSH connectivity to the `steamdeck` alias.

## Core Data Structures
*   No new data structures required.

## Public Interfaces
*   `scripts/package_plugin.py --release`: New command-line flag.

## Dependency Requirements
*   No new dependencies required. The workflow will use standard GitHub Actions (`actions/checkout`, `actions/setup-node`, `pnpm/action-setup`, `actions/setup-python`, `softprops/action-gh-release`).

## Testing Strategy
1.  **Script Validation**: Run `python scripts/package_plugin.py` locally and verify the zip contains the git hash in `plugin.json`.
2.  **Release Flag Validation**: Run `python scripts/package_plugin.py --release` locally and verify the zip contains only the base version in `plugin.json`.
3.  **Post-Commit Validation**: Run `./scripts/post_commit.sh` locally and ensure the generated zip is successfully transferred via `scp` to the `steamdeck` alias.
4.  **Workflow Validation**: After merging, create a draft release or pre-release using the `gh` CLI (`gh release create vX.Y.Z-test --notes "test"`) and verify that the GitHub Action runs successfully and attaches `SDH-ludusavi.zip` to the release with the correct version format.