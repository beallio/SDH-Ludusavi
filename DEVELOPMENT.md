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
- `NOTICE`: source lineage, third-party licenses, API integrations, and artwork provenance.

### Frontend Dependencies

Install frontend dependencies when needed:

```bash
./run.sh pnpm install --frozen-lockfile --ignore-scripts
```

The repository uses `pnpm-lock.yaml` as the canonical frontend lockfile. Do not use `npm install` or add `package-lock.json`. The pnpm store and heavy virtual store are configured under `/tmp/sdh_ludusavi`; the local `node_modules/` directory is ignored and contains only pnpm links/bin shims needed by package scripts.

## Build & Packaging

### Run backend tests:

```bash
./run.sh uv run pytest
```

### Build the Decky frontend:

```bash
./run.sh pnpm run build
```

### Run frontend supply-chain checks:

```bash
./run.sh pnpm run verify
```

### Create the Decky plugin zip locally:

```bash
./run.sh uv run python scripts/package_plugin.py
```

The package is written to `out/SDH-Ludusavi.zip` and contains a top-level `SDH-Ludusavi/` plugin directory. `LICENSE` and `NOTICE` are required package files. The local post-commit hook runs `scripts/post_commit.sh`, which rebuilds `dist/` and recreates that zip after each commit.

## Licensing and Provenance

Project-authored SDH-Ludusavi code is licensed under MIT. The project originally began as a fork
of GedasFX/decky-ludusavi, and retained portions from that project and the underlying
SteamDeckHomebrew Decky plugin template remain BSD-3-Clause. Vendored `pyludusavi` remains
MIT-licensed under its own included license. Frontend libraries, icon sets, external runtime
integrations, and SteamGridDB artwork retain their respective upstream terms. SDH-GameSync is
credited as design inspiration for the game-launch pause and pre-launch save-check concept; no
SDH-GameSync code is bundled. Keep `LICENSE` and `NOTICE` synchronized with dependency, asset,
and packaging changes.

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
5. Immediately run the post-release sync script to bump `dev` to the next patch version and sync it with `main`:
   ```bash
   ./scripts/post_release_sync.sh
   ```
   This will automatically commit the version bump and push `dev`.

#### Prerelease (Dev) Release Process

To publish a development prerelease for testing, run:
```bash
./scripts/request_dev_release.sh <base_version> [commit]
```
This triggers the manual `dev-release.yml` GitHub workflow for the specified base version and commit.

`<base_version>` must be the next *unreleased* stable version. Both `request_dev_release.sh`
and the `dev-release.yml` workflow refuse a base that is not strictly ahead of the highest
released stable tag (not just an exact tag match), using the shared rule in
`scripts/version_guard.py` (`check-base`). This prevents the `dev` branch from drifting
behind `main` and emitting dev builds that sort *below* the current stable release. If you
hit this refusal, sync `main` into `dev` and bump `package.json`/`plugin.json` to the next
version first. A CI test (`tests/test_version_config.py::test_dev_version_ahead_of_stable`)
also asserts the declared version stays strictly ahead of the highest stable tag.

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

## Code Quality Boundaries

### Backend: Updater Orchestration and State
The updater architecture enforces strict boundaries between domain models, transport, and state orchestration:
- **`PluginUpdater` Ownership**: The `PluginUpdater` class is the sole owner of updater settings, cache persistence, cooldown logic, update checks, and installer reconciliation.
- **Model/Client/State Separation**:
  - `updater_models.py` contains pure dataclasses for JSON definitions and candidate logic.
  - `updater_client.py` isolates all network transport (`urllib.request`).
  - `updater_rate_limit.py` is a pure helper that parses `Retry-After` / `X-RateLimit-Reset`
    headers into the cooldown deadline, shared by both `check_for_update()` and `revalidate()`.
  - `updater_discovery.py` holds the pure release parsing/validation/selection logic
    (prevalidate → validate → select candidate).
  - `updater_pending.py` owns the pending-install ledger (load/promote/reconcile of the
    persisted cache payload).
  - `updater.py` is the small façade that orchestrates discovery/validation, the rate-limit
    cooldown policy, the pending-install ledger, and persistence using the modules above.
- **Service Isolation**: The `SDHLudusaviService` acts merely as a facade. It holds an instance of `PluginUpdater` and delegates RPC methods to it. Updater modules never import the service or access private service fields.
- **Unchanged Persistence**: While the logic is decomposed, the data schema in `cache.json` and `settings.json` remains entirely backward-compatible and unchanged. `main.py` simply acts as an async adapter passing calls to the facade.

### Backend: Syncthing Connectivity and Activity

Syncthing watch startup resolves the deepest configured folder containing Ludusavi's
backup path. The `/rest/system/connections` endpoint is used only to intersect currently
connected device IDs with the remote devices configured for that folder. Its global and
per-device byte counters are intentionally ignored because a single connection can carry
traffic for multiple folders.

BrowserView activity and transfer direction instead come from folder-scoped sources:
`/rest/db/status?folder=<folder-id>` and events whose `folder` matches the resolved
folder. Watched-folder syncing/download/item evidence indicates downloading, and
non-empty watched-folder `RemoteDownloadProgress` indicates uploading. Scan, index,
sequence, and need signals may keep an update in progress without inventing a transfer
direction.

### Frontend: Steam Runtime and View Ownership
The frontend strictly isolates untyped runtime access and splits massive components by responsibility:
- **Steam Runtime Validation**: All direct accesses to private global objects like `(window as any).SteamClient` are banned outside `steamRuntime.ts`. This module safely guards, wraps, and exposes the required Steam runtime methods, preventing fatal crashes during render.
- **Controller/Source/Surface Ownership**:
  - **Controllers**: Modules like `gameLifecycleController.tsx` and `pluginUpdateController.tsx` handle business logic and state machine transitions.
  - **Sources**: Modules like `steamLifecycleSource.ts` adapt Decky/Steam events (e.g. `onAppStart`) into standard observables for the controllers.
  - **Surfaces**: React UI components (like `autoSyncStatusSurface.tsx`) act as thin adapters, delegating DOM operations to decoupled rendering modules (`autoSyncStatusRenderer.tsx`) and native view management (`autoSyncStatusBrowserView.ts`).

## Technical Reference: Status & Operations

### Frontend Diagnostic Logging

Frontend user flows log through `src/utils/logging.ts`, which writes to the matching
browser console level and forwards the same entry to the backend diagnostic log buffer.
Structured UI entries use this format:

```text
SDH-Ludusavi:[LABEL] [GAME_NAME]: message
```

Fields are sorted for stable searching. UI code should log transitions at controller
and action boundaries: requested, started, completed, skipped, superseded, failed, or
rolled back.

**Diagnostic Logging Contract:**
Do not log React renders, full settings objects, environment values, full checksums, or high-frequency polling samples.
Explicitly prohibited in routine logs:
- Full RPC-result object serialization (e.g., `JSON.stringify(operationResult)`).
- Raw save paths, home directories (e.g., `/home/deck`), or nested file registries.
- Massive JSON payloads or runtime property inventories.

Instead, use `summarizeLifecycleResult` or similar pure summary helpers to log bounded fields (status, operation, reason, canonical game, and aggregate counts).

**Log Regression Analyzer:**
To run deterministic regression checks against field logs, pull them to `/tmp/sdh_ludusavi` and run the analyzer:
```bash
./run.sh uv run python scripts/pull_plugin_logs.py --host steamdeck
./run.sh uv run python scripts/analyze_plugin_logs.py /tmp/sdh_ludusavi/steamdeck/logs
./run.sh uv run python scripts/analyze_plugin_logs.py --strict --format json <path>...
```
The JSON format output can be inspected for automated processing. The analyzer checks for the following stable rule IDs:
- `launch_gate.backend_match_after_untracked_start`
- `launch_gate.resume_before_resolution`
- `launch_gate.lease_expired`
- `syncthing.watch_ttl_expired`
- `diagnostics.error_or_traceback`
- `diagnostics.oversized_or_raw_payload`

The primary operation labels are:

- `ui`: plugin, QAM, initialization, and cache-selection events.
- `ui_settings`: optimistic settings requests and persistence outcomes.
- `refresh`: manual game-list refresh events.
- `Backup` / `Restore`: manual game operations.
- `launcher`: Ludusavi launcher actions.
- `logs`: plugin and Ludusavi log-modal actions.
- `lifecycle`: Steam lifecycle source setup, fallback, and failures.

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
./run.sh pnpm run build
```
