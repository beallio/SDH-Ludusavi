# SDH-Ludusavi Development Documentation

This document contains technical information for building, maintaining, and understanding the internal architecture of the SDH-Ludusavi plugin.

## Development Setup

Use the wrapper so Python virtual environments and caches stay outside Dropbox:

```bash
./run.sh uv sync
```

The wrapper stores Python tooling state under `/tmp/sdh_ludusavi`.

## Project Structure

The installable Decky plugin is built from these required files:

- `plugin.json`: Decky plugin metadata.
- `package.json`: frontend package metadata and version.
- `main.py`: Python backend entry point for Decky RPC calls.
- `py_modules/sdh_ludusavi/`: Python backend modules on Decky's runtime import path.
- `py_modules/pyludusavi/`: vendored pure-Python Ludusavi adapter dependency.
- `src/index.tsx`: TypeScript frontend source.
- `assets/steamgrid/ludusavi/`: bundled local artwork source files for the plugin-managed Ludusavi launcher shortcut.
- `dist/`: generated frontend bundle, source map, and built frontend assets from `pnpm run build`, including hashed artwork files emitted from the local assets.
- `LICENSE`: redistributable license text.

### Frontend Dependencies

Install frontend dependencies when needed:

```bash
pnpm install --frozen-lockfile --ignore-scripts
```

The repository uses `pnpm-lock.yaml` as the canonical frontend lockfile. Do not use `npm install` or add `package-lock.json`. The pnpm store and heavy virtual store are configured under `/tmp/sdh_ludusavi`; the local `node_modules/` directory is ignored and contains only pnpm links/bin shims needed by package scripts.

## Build & Packaging

### Run backend tests:

```bash
./run.sh uv run pytest
```

### Build the Decky frontend:

```bash
pnpm run build
```

### Run frontend supply-chain checks:

```bash
pnpm run verify
```

### Create the Decky plugin zip locally:

```bash
./run.sh uv run python scripts/package_plugin.py
```

The package is written to `out/SDH-Ludusavi.zip` and contains a top-level `SDH-Ludusavi/` plugin directory. The local post-commit hook runs `scripts/post_commit.sh`, which rebuilds `dist/` and recreates that zip after each commit.

### Release Packaging and Workflows

GitHub Actions is the only publisher for public releases. Do not build, upload, or tag releases manually on GitHub unless instructed.

#### Stable Release Process

To create a stable release:
1. Bump and align the versions in `package.json` and `plugin.json`:
   ```bash
   ./run.sh uv run python scripts/set_release_version.py X.Y.Z
   ```
2. Run quality checks locally:
   ```bash
   ./run.sh uv run ruff check . --fix
   ./run.sh uv run ruff format .
   ./run.sh uv run ty check py_modules/sdh_ludusavi/
   ./run.sh uv run pytest
   ./run.sh pnpm run verify
   ```
3. Commit the changes and tag it:
   ```bash
   git add package.json plugin.json assets/icon.png
   git commit -m "chore(release): prepare vX.Y.Z"
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```
4. The GitHub Actions release workflow will trigger on tag push to validate, build, and publish the release.

#### Prerelease (Dev) Release Process

To publish a development prerelease for testing, run:
```bash
./scripts/request_dev_release.sh <base_version> [commit]
```
This triggers the manual `dev-release.yml` GitHub workflow for the specified base version and commit.

#### Release Artifacts

The packaging automation produces the following versioned artifacts:
- `SDH-Ludusavi-vX.Y.Z.zip`: The Decky-compliant plugin archive containing a single `SDH-Ludusavi/` root directory.
- `SDH-Ludusavi-vX.Y.Z.zip.sha256`: A checksum file containing the SHA-256 hash of the ZIP.
- `SDH-Ludusavi-vX.Y.Z.manifest.json`: A manifest metadata file containing information about the release version, source version, release tag, update channel (e.g. `stable` or `dev`), and archive checksum.

## State and Runtime Privileges

Runtime settings are stored through Decky's `SettingsManager` in `DECKY_PLUGIN_SETTINGS_DIR/settings.json`. Runtime cache data is stored separately in `DECKY_PLUGIN_RUNTIME_DIR/cache.json`, including cached Ludusavi game status, app ID markers, shortcut IDs, and operation history. The plugin does not write mutable data under `DECKY_PLUGIN_DIR`, because Decky can replace that directory during updates. Tooling caches still live under `/tmp/sdh_ludusavi`.

`plugin.json` does not request Decky's `_root` flag. The backend runs as the Decky user so the Ludusavi Flatpak can see that user's Ludusavi configuration, backup metadata, and Flatpak runtime state.

## Ludusavi Integration Details

The backend locates Ludusavi through the vendored `pyludusavi` package. It constructs `pyludusavi.Ludusavi(flatpak_id="com.github.mtkennerly.ludusavi", env=...)` with Deck-compatible environment overrides. The overrides provide `XDG_RUNTIME_DIR` when Decky omits it and clear `LD_LIBRARY_PATH` for Ludusavi subprocesses.

### Ludusavi Launcher Shortcut

When launching the Ludusavi GUI, the plugin uses a visible non-Steam shortcut named `"Ludusavi"`. The plugin searches Steam's app list by that exact name before using the cached AppID. If a matching shortcut already exists, the plugin adopts the matching shortcut and refreshes its cached AppID instead of creating a duplicate.

If no named shortcut exists, the plugin validates the cached AppID and renames that shortcut to `"Ludusavi"` when it is still present. If the cache points to a deleted shortcut, the plugin creates a new visible `"Ludusavi"` shortcut, stores the new AppID, and updates its executable, launch options, compatibility tool, and bundled artwork before launch.

### QAM Cache Markers & Limitations

To support instant Quick Access Menu (QAM) load times (< 1ms) after a system reboot, the plugin utilizes a composite modification time marker. The adapter stats three core configuration and database metadata files in Ludusavi's config directory: `config.yaml`, `cache.yaml`, and `manifest.yaml`. 

This composite marker changes whenever the user modifies Ludusavi settings, backs up/restores a game, or downloads a manifest update using the Ludusavi GUI or CLI.

**Limitation on External Backups Modifications:**
Because the plugin uses an $O(1)$ constant-time metadata check to prevent blocking the Steam Deck UI thread, it does not scan the backups directory directly. If folders or files are added, modified, or deleted within the backups directory externally (e.g., via Dropbox, Syncthing, or manual folder management outside of the Ludusavi executable), the config markers remain unchanged. In such multi-device or manual sync environments, the cached status will not immediately update until a fresh backup/restore is run via Ludusavi or the user manually presses the refresh button in the QAM.

### SteamOS Multi-Window UI & CSS Styling Constraints

The Steam Deck user interface (SteamOS Big Picture Mode / Overlay / QAM) runs inside a multi-window Chromium Embedded Framework (CEF) environment. This has critical implications for UI styling and lifecycle logic:

#### Multi-Window DOM Isolation
- **The Problem:** The Quick Access Menu (QAM) overlay panel and the background plugin loader context run in separate window contexts with isolated `document` instances.
- **Why it matters:** Programmatically appending a stylesheet (`<style>` tag) to `document.head` during plugin initialization inside `definePlugin` only affects the background/main window. The stylesheet will **not** be loaded or visible inside the QAM's document window.
- **The Solution:** To style QAM components reliably, stylesheets must be rendered **declaratively directly within the React JSX tree** of the visible component (e.g. `<style>{dropdownStyleEl.textContent}</style>`). This forces React to mount the styles directly into the active QAM window's DOM.

#### Flexbox Layout & Text Truncation Constraints
- **Case-Insensitive Class Selectors:** SteamOS frequently updates its UI stylesheets, including randomized class suffixes (e.g., `.dropdown_DropdownButton_12345` vs `.dropdown_DropdownButton_Label_abcde`). CSS selectors targeting these elements should use case-insensitive matches (e.g., `[class*="dropdown" i]`) to prevent breaking changes on client updates.
- **Flex Shrink Propagation:** Interactive components (like `DropdownItem`) are nested inside several layers of flex containers. If a child element has `white-space: nowrap` (e.g., a long game title), it forces the flex items to expand to their maximum width unless `min-width: 0 !important` and `max-width: 100% !important` are recursively applied to all elements in the parent chain.

## In-Plugin Updater Architecture

The updater architecture handles background update checking, version validation, and update installation without blocking the main event loops or unzipping files directly.

### 1. Discovery & Validation
- **Path**: `py_modules/sdh_ludusavi/updater.py`
- **JSON Fetch**: Uses only Python's standard library `urllib.request` to fetch GitHub Release assets (limiting timeouts to 10-15s).
- **Candidate Validation**: Enforces strict verification of:
  - Draft state (ignored).
  - Single release manifest JSON (enforces name, package, version, tag, channel, and a 64-char hexadecimal SHA-256).
  - Matches tag name exactly to the manifest tag.
  - Matches the channel value (`stable` or `dev`) to the GitHub prerelease flag.
  - Exactly one matching ZIP whose name is defined in `manifest.assetName`.

### 2. Version Comparison & Selection
- **Stable Channel**: Inspects only stable versions. Stable `X.Y.Z` wins over installed prerelease or local build of the same base.
- **Development Channel**: Considers both stable and prereleases.
- **Prerelease & Dev Suffixes**: Handles stable `X.Y.Z`, development `X.Y.Z-dev.g<sha>`, legacy dev `X.Y.Z-dev.<sha>`, and local build metadata `X.Y.Z+<metadata>`.
- **Local Build Metadata**: `X.Y.Z+...` is treated as stable-equivalent to `X.Y.Z` (preventing same-base stable updates).
- **Dev Ordering**: For dev releases with the same base (e.g. `0.2.0-dev.g123` vs `0.2.0-dev.g456`), they are ordered by validated GitHub `published_at` timestamp.

### 3. Settings & Cache Persistence
- **Settings**: Persistent preferences (`update_channel`, `automatic_update_checks`) are stored in Decky settings.
- **Cache**: Operational metadata (`last_checked_at`, `pending_update_install`, etc.) are written to cache.
- **Rate-limit interpretation**: On `403` or `429`, retry timelines are stored in-memory only. Successful checks cache findings for 24 hours.

### 4. Revalidation & Installation Flow
- **Direct Installer Adapter**: Exposes `src/utils/deckyInstaller.ts` to isolate `window.DeckyBackend` calls.
- **Pre-install Revalidation**: The installer action first calls `revalidate_plugin_update(candidate)` to verify the release URL and SHA-256 immediately before installation.
- **Decky Hand-off**: Determines the installation type (`UPDATE: 2` or `DOWNGRADE: 3`) and enqueues `record_update_install_requested` before invoking Decky Loader's `utilities/install_plugin` method.

## Technical Reference: Status & Operations

### Game Status Values
- `has_backup`: Ludusavi recognizes at least one backup for the game.
- `needs_first_backup`: Ludusavi recognizes the game, but no backup exists yet.
- `configured`: Fallback state for ambiguous status data.
- `error`: Ludusavi reported a failed file, registry item, or invalid game state.

### Operation Result Values
- `backed_up`: A backup operation completed.
- `restored`: A restore operation completed.
- `skipped`: The plugin intentionally did not run backup or restore.
- `failed`: The frontend caught an unexpected operation failure.

### Skip Reasons
- `auto_sync_disabled`: Automatic Sync is off.
- `operation_running`: Another refresh, backup, restore, or version lookup is already running.
- `unmatched_game`: Confident match with a Ludusavi game name failed.
- `no_backup`: Restore requested, but no backup exists.
- `local_current`: Local save is already current.
- `ambiguous_recency`: Recency could not be proven; launch-gated conflict modal was shown.
- `conflict_unresolved`: User dismissed the conflict modal.

### Durable History Entries
- `last_backup`: Latest successful backup.
- `last_restore`: Latest successful restore.
- `last_skip`: Latest intentional skip.
- `last_failure`: Latest game-scoped exception.

### Operation Status Fields
- `is_running`: `true` while the global operation lock is held.
- `name`: Active operation name (`refresh`, `backup`, `restore`, `versions`).
- `game_name`: Game associated with the active operation.
- `last_result`: `ok`, `failed`, or `null`.
- `last_error`: Latest operation error text.

## Validation

Before committing changes, run:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run build
```
