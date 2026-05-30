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

### Create the Decky plugin zip:

```bash
./run.sh uv run python scripts/package_plugin.py
```

The package is written to `out/SDH-Ludusavi.zip` and contains a top-level `SDH-Ludusavi/` plugin directory. The local post-commit hook runs `scripts/post_commit.sh`, which rebuilds `dist/` and recreates that zip after each commit.

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
