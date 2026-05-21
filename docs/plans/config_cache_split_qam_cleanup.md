# Config/Cache Split And QAM Cleanup

## Problem Definition

SDH-Ludusavi currently stores user settings and runtime cache data together. Decky
provides separate plugin directories for these concerns, so settings should live in
`DECKY_PLUGIN_SETTINGS_DIR` and derived cache/runtime data should live in
`DECKY_PLUGIN_RUNTIME_DIR`. The QAM UI also has spacing and separator regressions in
the GAME, Notifications, Logs, and Versions panels.

## Architecture Overview

Use Decky's injected directory values in `main.py` and pass separated persistence
dependencies into `SDHLudusaviService`. Keep the frontend RPC payloads unchanged.
Settings are read and written via Decky's `SettingsManager`; runtime cache data is
written as JSON under the runtime directory.

## Core Data Structures

- Settings: `auto_sync_enabled`, `selected_game`, `notifications`.
- Cache/runtime data: `games`, `aliases`, `ids`, `installed_app_ids`,
  `ludusavi_config_mtime_ns`, `game_history`, `ludusaviLauncherShortcutAppId`.

## Public Interfaces

No RPC contract changes. Existing calls such as `get_settings`, `refresh_games`,
`set_notification_settings`, and shortcut cache RPCs retain their current payloads.

## Dependency Requirements

Use Decky's runtime-provided `settings.SettingsManager` when initializing the plugin.
Tests may provide a fake `settings` module.

## Testing Strategy

Add failing backend tests for separate Decky settings/runtime paths and separated JSON
payloads. Add frontend static tests for compact GAME spacing, restored dividers, removed
GAME action divider, and left-aligned Versions content. Validate with focused tests,
then the full project checks.
