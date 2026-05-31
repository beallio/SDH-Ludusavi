# Decky-Compliant Release Packaging and Automation

## Problem Definition

SDH-Ludusavi needs a release process that builds Decky-compliant plugin ZIPs while
preserving the existing local development workflow.

Local packaging must remain unchanged for development:

```bash
./run.sh uv run python scripts/package_plugin.py
# writes: out/SDH-Ludusavi.zip
```

Public GitHub release packaging must be automated, validated, and versioned:

```text
SDH-Ludusavi-vX.Y.Z.zip
SDH-Ludusavi-vX.Y.Z.zip.sha256
SDH-Ludusavi-vX.Y.Z.manifest.json
```

Development releases must be GitHub prereleases named:

```text
vX.Y.Z-dev.SHORTSHA
SDH-Ludusavi-vX.Y.Z-dev.SHORTSHA.zip
```

## Architecture Overview

Keep `scripts/package_plugin.py` as the single source of truth for package
creation. Do not introduce a second shell-based packager.

GitHub Actions owns publication:

- CI builds and validates package artifacts but never publishes releases.
- Stable releases are tag-driven and publish versioned public assets.
- Dev releases are manual GitHub prereleases requested through a local helper
  script.

All published installable ZIPs must pass the full project quality gate.

## Exact File Changes

Modify:

```text
scripts/package_plugin.py
scripts/post_commit.sh
plugin.json
package.json
README.md
DEVELOPMENT.md
AGENTS.md
tests/test_package_plugin.py
tests/test_protocol.py
tests/test_npm_supply_chain.py
.github/workflows/release.yml
```

Add:

```text
assets/icon.png
scripts/validate_plugin_zip.py
scripts/set_release_version.py
scripts/request_dev_release.sh
.github/workflows/ci.yml
.github/workflows/dev-release.yml
tests/test_validate_plugin_zip.py
tests/test_release_workflows.py
docs/plans/decky_release_artifacts.md
docs/agent_conversations/YYYY-MM-DD_decky_release_artifacts.json
```

Do not remove or change the local post-commit package behavior unless tests
prove it is incompatible with Decky packaging requirements.

## Public Interfaces

### Package CLI Contract

Extend `scripts/package_plugin.py` with these exact options:

```text
--project-root PATH
--output-dir PATH
--release
--release-version VERSION
--release-tag TAG
--versioned-output
--emit-release-metadata
```

Rules:

- Default command remains backward compatible and writes
  `out/SDH-Ludusavi.zip`.
- `--release` omits local git build metadata.
- `--release-version VERSION` stamps only staged ZIP copies of `plugin.json`
  and `package.json`.
- `--release-version` must accept stable semver and prerelease semver:
  - `0.2.1`
  - `0.2.1-dev.55d87c6`
- `--versioned-output` changes ZIP name to
  `SDH-Ludusavi-v{VERSION}.zip`.
- `--emit-release-metadata` writes:
  - `SDH-Ludusavi-v{VERSION}.zip.sha256`
  - `SDH-Ludusavi-v{VERSION}.manifest.json`
- `--release-tag TAG` defaults to `v{VERSION}` and is used only for manifest
  metadata.
- Source-tree `plugin.json` and `package.json` must never be mutated by
  packaging.

Manifest JSON must include:

```json
{
  "schemaVersion": 1,
  "pluginName": "SDH-Ludusavi",
  "packageName": "sdh-ludusavi",
  "version": "0.2.1",
  "sourceVersion": "0.2.1",
  "tag": "v0.2.1",
  "channel": "stable",
  "assetName": "SDH-Ludusavi-v0.2.1.zip",
  "sha256": "...",
  "generatedAt": "..."
}
```

For prereleases, `channel` must be `"dev"`.

### ZIP Contract

The ZIP must contain exactly one top-level folder:

```text
SDH-Ludusavi/
```

Required contents:

```text
SDH-Ludusavi/dist/index.js
SDH-Ludusavi/main.py
SDH-Ludusavi/package.json
SDH-Ludusavi/plugin.json
SDH-Ludusavi/LICENSE
SDH-Ludusavi/py_modules/sdh_ludusavi/
SDH-Ludusavi/py_modules/pyludusavi/
SDH-Ludusavi/py_modules/pyludusavi-0.2.3.dist-info/
```

Package `assets/icon.png` only if `plugin.json.publish.image` references it as
a packaged or runtime asset. Otherwise keep it tracked for repository and store
metadata and do not force it into the runtime ZIP.

Reject these paths inside the ZIP:

```text
node_modules/
src/
tests/
docs/
.git/
__pycache__/
*.pyc
.cache/
.pytest_cache/
.ruff_cache/
.venv/
```

### New Scripts

Add `scripts/validate_plugin_zip.py`.

Interface:

```bash
./run.sh uv run python scripts/validate_plugin_zip.py \
  PATH_TO_ZIP \
  --expected-version VERSION \
  --expected-name SDH-Ludusavi
```

It must validate ZIP layout, required files, forbidden files, metadata
versions, and `plugin.json.name`.

Add `scripts/set_release_version.py`.

Interface:

```bash
./run.sh uv run python scripts/set_release_version.py 0.2.1
```

It must:

- reject non-stable semver
- update `package.json.version`
- update `plugin.json.version`
- keep JSON formatting stable enough for tests

Add `scripts/request_dev_release.sh`.

Interface:

```bash
./scripts/request_dev_release.sh 0.2.1 [commit]
```

It must:

- default commit to `HEAD`
- resolve commit to full SHA
- validate stable base version
- check `gh auth status`
- run:

```bash
gh workflow run dev-release.yml \
  -f commit="$FULL_SHA" \
  -f base_version="$BASE_VERSION"
```

It must not create tags, build ZIPs, upload assets, or edit source versions.

## Workflow Contracts

### Stable Release Workflow

Replace `.github/workflows/release.yml`.

Trigger:

```yaml
on:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+"
  workflow_dispatch:
    inputs:
      tag:
        required: true
        type: string
```

Behavior:

- Checkout the tag.
- Validate tag equals `v{package.json.version}`.
- Validate `plugin.json.version == package.json.version`.
- Run full gate:
  - `./run.sh uv run ruff check .`
  - `./run.sh uv run ruff format --check .`
  - `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  - `./run.sh uv run pytest`
  - `./run.sh pnpm run verify`
- Package with versioned release flags.
- Validate ZIP.
- Verify SHA-256.
- Publish using `softprops/action-gh-release`.
- Use `permissions: contents: write`.
- Use versioned asset globs only.
- Do not overwrite existing assets.

### Development Release Workflow

Add `.github/workflows/dev-release.yml`.

Trigger:

```yaml
on:
  workflow_dispatch:
    inputs:
      commit:
        required: false
        type: string
      base_version:
        required: true
        type: string
```

Behavior:

- Resolve commit to full SHA and short SHA.
- Validate `base_version` is stable semver.
- Build `DEV_VERSION="${base_version}-dev.${short_sha}"`.
- Build tag `v${DEV_VERSION}`.
- Fail if tag already exists.
- Run same full gate as stable release.
- Package with `--release-version "$DEV_VERSION"`.
- Publish prerelease with `prerelease: true` and `make_latest: false`.
- Do not mutate source versions.

### CI Workflow

Add `.github/workflows/ci.yml`.

Trigger:

```yaml
on:
  pull_request:
  push:
    branches:
      - main
  workflow_dispatch:
```

Behavior:

- Run full gate.
- Build a dry-run package.
- Validate ZIP.
- Upload artifact.
- Do not create releases or tags.

## Version and Release Flows

Stable semantic release:

```bash
./run.sh uv run python scripts/set_release_version.py 0.2.1
./run.sh uv run ruff check .
./run.sh uv run ruff format --check .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
git add package.json plugin.json assets/icon.png
git commit -m "chore(release): prepare v0.2.1"
git tag v0.2.1
git push origin main v0.2.1
```

Dev release for current HEAD:

```bash
./scripts/request_dev_release.sh 0.2.1
```

Dev release for a specific commit:

```bash
./scripts/request_dev_release.sh 0.2.1 55d87c6f77dafcddc8e802a3f3e97d4f594d295b
```

Use the next intended stable line as the dev base. If `v0.2.1` is already
public and testing the next patch, use `0.2.2`.

## Icon and Template Cleanup

Track `assets/icon.png`.

Update `plugin.json.publish.image` to remove:

```text
https://opengraph.githubassets.com/1/SteamDeckHomebrew/PluginLoader
```

Use a project-owned icon reference. Prefer a tag-stable raw GitHub URL for
releases:

```text
https://raw.githubusercontent.com/beallio/SDH-Ludusavi/vX.Y.Z/assets/icon.png
```

The release packager may stamp this URL inside staged `plugin.json` when
`--release-tag` is provided.

Add tests rejecting:

```text
SteamDeckHomebrew/PluginLoader
out/SDH-ludusavi.zip
backend/
defaults/
_root
```

Retain or restore the original Decky template BSD notice below the project GPL
license if this repo remains derived from the Decky template.

## Documentation

Update `DEVELOPMENT.md` as the maintainer runbook.

Include:

- local package command
- stable release command sequence
- dev release helper command
- artifact names
- checksum and manifest explanation
- note that GitHub Actions is the only publisher

Update `AGENTS.md` as the future-agent protocol.

Add:

- do not publish releases unless explicitly instructed
- use `./run.sh` for project tooling
- stable release instructions
- dev release instructions
- never upload mutable public ZIP aliases
- preserve local post-commit packaging

Update `README.md` for users only.

Include:

- GitHub Releases link
- download `SDH-Ludusavi-vX.Y.Z.zip`
- prerelease warning for dev builds
- no maintainer-only release commands

## Testing Strategy

Add failing tests before implementation.

Required tests:

- default packager output remains `SDH-Ludusavi.zip`
- release packager output is versioned
- checksum file is generated and verifies
- manifest file contains expected metadata
- source JSON files are unchanged after release packaging
- ZIP validator accepts valid release ZIP
- ZIP validator rejects wrong root folder
- ZIP validator rejects missing runtime files
- ZIP validator rejects forbidden source/cache/dependency paths
- stable workflow is tag-driven
- dev workflow is manual-only prerelease
- release workflow has no `out/SDH-ludusavi.zip`
- release workflow refuses overwrite semantics
- `request_dev_release.sh` dispatches `dev-release.yml`
- `set_release_version.py` updates both metadata files
- `plugin.json.publish.image` no longer references Decky template assets

## Final Validation

Run:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
./run.sh uv run python scripts/package_plugin.py
./run.sh uv run python scripts/package_plugin.py --release --release-version 0.1.0 --release-tag v0.1.0 --versioned-output --emit-release-metadata --output-dir /tmp/sdh_ludusavi/release
./run.sh uv run python scripts/validate_plugin_zip.py /tmp/sdh_ludusavi/release/SDH-Ludusavi-v0.1.0.zip --expected-version 0.1.0 --expected-name SDH-Ludusavi
```

## Assumptions

- Local post-commit ZIP generation remains enabled.
- Public release assets are versioned only.
- GitHub Actions is the only publisher.
- Dev releases never mutate source metadata.
- Stable releases require a committed version bump and tag.
- README is user-facing; DEVELOPMENT is the maintainer runbook; AGENTS is the
  future-agent protocol.
