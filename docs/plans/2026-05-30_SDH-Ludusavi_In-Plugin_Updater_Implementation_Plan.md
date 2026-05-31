# Implementation Plan: In-Plugin GitHub Release Updates for SDH-Ludusavi

## Problem Definition

`SDH-Ludusavi` is distributed through GitHub Releases rather than the official
Decky Plugin Store. Users currently install a release ZIP manually. After that
first install, the plugin should be able to discover newer GitHub Release builds
and hand installation to Decky Loader's native installer prompt.

The updater must:

- default to stable releases only;
- support opt-in development releases;
- check for updates without blocking the Decky UI or Ludusavi operations;
- never install automatically;
- never overwrite, unzip, or replace the running plugin directory itself;
- validate release identity and checksums before offering an install action;
- degrade to manual release links when Decky's private installer surface is not
  available.

## Architecture Overview

The MVP updater has four cooperating parts:

1. **Backend discovery and validation**
   - New module: `py_modules/sdh_ludusavi/updater.py`.
   - Uses GitHub Releases metadata and release manifest assets.
   - Uses only Python standard library HTTP via `urllib.request`.
   - Validates release identity, channel, ZIP asset name, manifest fields, and
     SHA-256 syntax before producing any installable candidate.

2. **Service persistence and throttling**
   - Existing `SDHLudusaviService` owns user preferences, cache metadata,
     in-session rate-limit cooldown, and pending-install reconciliation.
   - Existing persistence split remains: user preferences in settings, runtime
     metadata in cache.
   - GitHub rate-limit cooldown is in memory only.

3. **Frontend update UI**
   - New component: `src/components/PluginUpdateSection.tsx`.
   - Shows installed version, channel, automatic-check preference, check status,
     update candidate, manual fallback link, and install actions.
   - Starts automatic checks asynchronously after render.
   - Manual install actions revalidate the selected release before invoking
     Decky.

4. **Decky installer adapter**
   - New module: `src/utils/deckyInstaller.ts`.
   - Isolates all private Decky Loader access.
   - Prefers `window.DeckyBackend.callable("utilities/install_plugin")` when
     available.
   - Uses `call(...)` only if live verification of the targeted Decky runtime
     proves that is the available surface.
   - Passes the fixed trusted plugin identity `SDH-Ludusavi`.

Actual plugin replacement and reload remain Decky Loader responsibilities.
`SDH-Ludusavi` downloads only release metadata and small manifest JSON files.
Decky downloads the ZIP only after the user confirms Decky's native prompt.

## Existing Repository Facts To Verify Before Implementation

Before editing code, re-check the current branch because repo state can change.
The implementation assumes these currently verified facts:

- `plugin.json` has `"name": "SDH-Ludusavi"` and `"version": "0.1.0"`.
- `package.json` has matching version `"0.1.0"`.
- `.github/workflows/release.yml` already publishes stable assets:
  - `SDH-Ludusavi-vX.Y.Z.zip`;
  - `SDH-Ludusavi-vX.Y.Z.zip.sha256`;
  - `SDH-Ludusavi-vX.Y.Z.manifest.json`.
- `.github/workflows/dev-release.yml` currently emits
  `X.Y.Z-dev.<short-sha>` and must be changed for future builds.
- `scripts/package_plugin.py` already emits release manifests when
  `--emit-release-metadata` is passed.
- `main.py::_call(...)` already offloads synchronous service methods from the
  Decky async event loop.
- `main.py::DeckySettingsStore.read()` currently reads only the existing
  settings keys and must be extended for update settings.
- `py_modules/sdh_ludusavi/constants.py::SETTINGS_KEYS` currently contains only
  `auto_sync_enabled`, `selected_game`, and `notifications`.
- `src/state/ludusaviState.tsx` currently normalizes only existing settings.

## Release And Versioning Rules

### Stable Releases

Stable releases use:

```text
X.Y.Z
```

Example:

```text
0.2.1
```

Stable GitHub releases must not be prereleases.

### Remote Development Releases

Future remote development releases must use:

```text
X.Y.Z-dev.g<short-sha>
```

Example:

```text
0.2.1-dev.g55d87c
```

SemVer requires prerelease data to start with `-`; it does not require
`-dev.` specifically. The `.g<sha>` convention is required here because:

- `dev` and the git commit identity remain separate structured identifiers;
- the `g` prefix prevents an all-numeric short SHA from becoming a numeric
  prerelease identifier with a leading zero;
- the format is easy to parse and follows the common Git convention that
  `g<sha>` means "git commit".

The updater must also parse legacy remote dev versions for compatibility:

```text
X.Y.Z-dev.<short-sha>
```

Do not order same-base dev builds by SHA token. For dev releases sharing the
same intended stable base, order by validated GitHub `published_at`.

Remote dev builds are prereleases of a future stable. A dev build published
after stable `v0.2.1` should use the next intended stable base, such as:

```text
0.2.2-dev.g55d87c
```

### Local Build Metadata

Local package builds may use build metadata:

```text
X.Y.Z+g<short-sha>
X.Y.Z+<metadata>
```

Examples:

```text
0.2.1+g55d87c
0.2.1+55d87c
```

Local builds represent build metadata for the current source base. Treat
`X.Y.Z+...` as stable-equivalent to `X.Y.Z` for update ordering.

Required behavior:

- Do not offer stable `X.Y.Z` over installed local `X.Y.Z+...`.
- Offer stable versions greater than `X.Y.Z`.
- Offer higher-base dev prereleases only when development releases are enabled.
- Show local builds as local builds in the UI when practical.

## GitHub Release Manifest Contract

`scripts/package_plugin.py` emits a manifest with:

```json
{
  "schemaVersion": 1,
  "pluginName": "SDH-Ludusavi",
  "packageName": "sdh-ludusavi",
  "version": "<published version>",
  "sourceVersion": "<base source version>",
  "tag": "v<published version>",
  "channel": "stable | dev",
  "assetName": "SDH-Ludusavi-v<published version>.zip",
  "sha256": "<raw SHA-256 hex>",
  "generatedAt": "<ISO timestamp>"
}
```

The updater must consume this manifest and pass its `sha256` to Decky's
installer only after validation.

## Candidate Validation Rules

A GitHub release is eligible only when all rules pass:

- `draft` is false.
- Stable mode ignores prereleases.
- Development mode accepts stable releases and valid prereleases.
- The release includes exactly one matching manifest asset.
- The release includes exactly one ZIP whose name equals `manifest.assetName`.
- Manifest `schemaVersion` equals `1`.
- Manifest `pluginName` equals `SDH-Ludusavi`.
- Manifest `packageName` equals `sdh-ludusavi`.
- Manifest `tag` equals GitHub `release.tag_name`.
- Manifest `version` equals the release tag without the leading `v`.
- Manifest `channel === "stable"` requires `release.prerelease === false`.
- Manifest `channel === "dev"` requires `release.prerelease === true`.
- Manifest `sha256` is exactly 64 hexadecimal characters.
- The artifact URL is taken only from the validated ZIP asset's
  `browser_download_url`.
- The release URL is taken from the validated release's `html_url`.

Rejected releases should be logged and ignored, never surfaced as installable
candidates.

## Update Selection Rules

### Stable Channel, Installed Stable Or Local Stable-Equivalent

- Consider only valid stable releases.
- Select the highest SemVer stable release.
- Offer it only when it is greater than the installed base version.
- Do not offer `X.Y.Z` over installed `X.Y.Z+...`.

### Stable Channel, Installed Dev Build

- Consider only valid stable releases.
- If latest stable has the same base as installed dev, offer
  `Move to Stable vX.Y.Z` using install type `UPDATE` (`2`).
- If latest stable is below the installed dev base, offer
  `Revert to Stable vX.Y.Z` using install type `DOWNGRADE` (`3`) and an
  explicit warning.
- Channel changes never install or downgrade automatically.

### Development Channel

- Consider valid stable and valid development releases.
- A stable release wins over a dev prerelease of the same base.
- A dev release may be offered over a stable/local build only when the dev base
  is higher than the installed stable base.
- If the highest relevant base has only dev releases, choose the valid dev
  release with the latest GitHub `published_at`.
- For a manually installed dev build with no recorded publication metadata,
  show a conservative "latest available development build" label rather than
  asserting strict newer/older ordering.

## User-Facing Behavior

Add an **Updates** section to the plugin UI.

Display:

- installed plugin version;
- update channel:
  - `Stable releases only`;
  - `Development releases enabled`;
- automatic update check setting;
- last check state:
  - never checked;
  - checking;
  - up to date;
  - stable update available;
  - development update available;
  - failed to check;
- candidate action:
  - `Update to vX.Y.Z`;
  - `Install development build vX.Y.Z-dev.g<sha>`;
  - `Move to Stable vX.Y.Z`;
  - `Revert to Stable vX.Y.Z`.

Development releases toggle:

- Label: `Receive development releases`.
- Description: `Includes prerelease builds intended for testing. These builds may contain regressions.`
- Default: off.
- Turning on shows a confirmation modal before saving.
- Turning on runs a forced development-enabled check after saving.
- Turning off saves immediately and runs a forced stable-only check.
- Turning off never installs, downgrades, or modifies the installed build.

Automatic update checks:

- Label: `Automatically check for updates`.
- Description: `Checks in the background while the plugin is loaded. Updates are installed only after confirmation.`
- Default: on.
- Automatic checks never invoke Decky's installer.
- Automatic failures should be quiet and visible only inside the Updates section.
- Manual failures may show a toaster because the user requested feedback.

Manual fallback:

- If Decky's private installer API is missing or incompatible, keep discovery
  visible.
- Disable only one-click install.
- Show: `Automatic installation is unavailable in this Decky environment. Install this release manually from GitHub Releases.`
- Provide a `View Release` action using the validated release URL.

## Public Interfaces And Types

### Frontend Types

Extend `src/types/index.ts`:

```ts
export type UpdateChannel = "stable" | "development";

export type PluginUpdateCandidate = {
  version: string;
  tag: string;
  channel: UpdateChannel;
  artifact_url: string;
  sha256: string;
  release_url: string;
  published_at: string;
  action: "update" | "move_to_stable" | "downgrade_to_stable";
};

export type UpdateCheckResult =
  | {
      status: "available";
      checked_at: string;
      candidate: PluginUpdateCandidate;
    }
  | {
      status: "current";
      checked_at: string;
      channel: UpdateChannel;
    }
  | {
      status: "failed";
      checked_at: string;
      message: string;
      retry_after?: string;
    };
```

Extend `Settings`:

```ts
export type Settings = {
  auto_sync_enabled: boolean;
  selected_game: string;
  notifications: NotificationSettings;
  update_channel: UpdateChannel;
  automatic_update_checks: boolean;
};
```

### Backend Data Shapes

In `py_modules/sdh_ludusavi/updater.py`, implement dataclass boundaries similar
to:

```python
@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    plugin_name: str
    package_name: str
    version: str
    source_version: str
    tag: str
    channel: Literal["stable", "dev"]
    asset_name: str
    sha256: str
    generated_at: str

@dataclass(frozen=True)
class UpdateCandidate:
    version: str
    tag: str
    channel: Literal["stable", "development"]
    artifact_url: str
    sha256: str
    release_url: str
    published_at: str
    action: Literal["update", "move_to_stable", "downgrade_to_stable"]

@dataclass(frozen=True)
class JsonResponse:
    status: int
    headers: Mapping[str, str]
    body: dict[str, Any] | list[Any]
```

Suggested testable functions:

```python
def parse_plugin_version(version: str) -> ParsedPluginVersion | None: ...
def fetch_json(url: str, *, timeout_seconds: float = 15.0) -> JsonResponse: ...
def list_releases() -> list[dict[str, Any]]: ...
def get_release_by_tag(tag: str) -> dict[str, Any]: ...
def validate_release_candidate(release: dict[str, Any]) -> UpdateCandidate | None: ...
def select_candidate(...) -> UpdateCandidate | None: ...
def check_for_update(...) -> dict[str, Any]: ...
def revalidate_install_candidate(candidate: dict[str, Any]) -> UpdateCandidate: ...
```

## Settings And Cache Model

Persisted settings:

```json
{
  "update_channel": "stable",
  "automatic_update_checks": true
}
```

Cache metadata:

```json
{
  "last_checked_at": "...",
  "last_checked_channel": "stable",
  "last_available_tag": "v0.2.1",
  "last_notified_tag": "v0.2.1",
  "installed_release_tag": "v0.2.1-dev.g55d87c",
  "installed_release_published_at": "...",
  "pending_update_install": {
    "version": "0.2.1-dev.g55d87c",
    "tag": "v0.2.1-dev.g55d87c",
    "channel": "development",
    "published_at": "...",
    "requested_at": "..."
  }
}
```

Rules:

- Store user preferences in settings.
- Store operational update metadata in cache.
- Do not persist GitHub rate-limit counters or reset timestamps.
- Keep `_update_rate_limited_until` in memory only.
- Do not write `installed_release_tag` when the user merely clicks install.
- Store `pending_update_install` before invoking Decky's installer.
- On plugin startup, compare the actual loaded plugin version with pending
  metadata.
- Promote pending metadata to installed metadata only when versions match.
- Clear pending metadata when the loaded version does not match.

Update `main.py::DeckySettingsStore.read()` so Decky's settings manager reads:

- `auto_sync_enabled`;
- `selected_game`;
- `notifications`;
- `update_channel`, default `"stable"`;
- `automatic_update_checks`, default `true`.

Update `py_modules/sdh_ludusavi/constants.py::SETTINGS_KEYS` with:

- `update_channel`;
- `automatic_update_checks`.

## Backend Implementation Changes

### `py_modules/sdh_ludusavi/updater.py`

Implement:

- SemVer/local-build parser.
- GitHub JSON fetch wrapper using `urllib.request`.
- GitHub release listing and release-by-tag retrieval.
- Manifest asset download and validation.
- Candidate selection for stable and development channels.
- Install-click revalidation.
- Rate-limit response interpretation for `403` and `429`.

HTTP headers:

```python
{
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "SDH-Ludusavi/<installed-version>",
}
```

Use a finite timeout of 10-15 seconds.

Rate-limit handling:

- Automatic checks are normally throttled for 24 hours after a successful
  `current` or `available` result.
- Manual `Check now` bypasses ordinary successful-result cache.
- Manual checks do not bypass active in-session rate-limit cooldown.
- On `403` or `429`, inspect `Retry-After`, `X-RateLimit-Remaining`, and
  `X-RateLimit-Reset`.
- Store a derived retry time only in memory.
- Do not retry in a loop.
- Failed checks must not poison the 24-hour successful-result cache.

### `py_modules/sdh_ludusavi/service.py`

Add initialized members:

```python
self._update_channel = "stable"
self._automatic_update_checks = True
self._update_check_cache = {}
self._update_rate_limited_until = None
```

Add or update methods:

```python
def set_update_channel(self, channel: str) -> dict[str, Any]: ...
def set_automatic_update_checks(self, enabled: bool) -> dict[str, Any]: ...
def get_update_check_context(self) -> dict[str, Any]: ...
def record_update_check_result(self, result: dict[str, Any]) -> None: ...
def record_update_install_requested(self, candidate: dict[str, Any]) -> dict[str, Any]: ...
def reconcile_pending_update_install(self, current_version: str) -> None: ...
```

Responsibilities:

- Coerce invalid stored channel values to stable.
- Default missing settings for older installs.
- Save new settings.
- Save update cache metadata.
- Suppress GitHub requests during an active in-session cooldown.
- Reconcile pending install metadata on startup or first version-aware update
  context call.
- Keep GitHub network logic out of persistence classes.

### `main.py`

Add RPC methods using `_call(...)`:

```python
async def set_update_channel(self, channel: str) -> dict[str, Any]: ...
async def set_automatic_update_checks(self, enabled: bool) -> dict[str, Any]: ...
async def check_for_plugin_update(self, current_version: str, force: bool = False) -> dict[str, Any]: ...
async def revalidate_plugin_update(self, candidate: dict[str, Any]) -> dict[str, Any]: ...
async def record_update_install_requested(self, candidate: dict[str, Any]) -> dict[str, Any]: ...
```

`check_for_plugin_update` and `revalidate_plugin_update` must use `_call(...)`
so network work does not block Decky's async event loop.

Update `DeckySettingsStore.read()` to include new update settings.

### `.github/workflows/dev-release.yml`

Change:

```bash
DEV_VERSION="${{ env.BASE_VERSION }}-dev.${SHORT_SHA}"
```

to:

```bash
DEV_VERSION="${{ env.BASE_VERSION }}-dev.g${SHORT_SHA}"
```

Keep stable release workflow unchanged.

## Frontend Implementation Changes

### `src/state/ludusaviState.tsx`

Update defaults:

```ts
export const defaultSettings = (): Settings => ({
  auto_sync_enabled: false,
  selected_game: "",
  notifications: { ...defaultNotificationSettings },
  update_channel: "stable",
  automatic_update_checks: true
});
```

Update normalization:

```ts
update_channel:
  settings.update_channel === "development" ? "development" : "stable",
automatic_update_checks:
  typeof settings.automatic_update_checks === "boolean"
    ? settings.automatic_update_checks
    : true,
```

Add store methods:

```ts
setUpdateChannel(channel: UpdateChannel): void
setAutomaticUpdateChecks(enabled: boolean): void
```

### `src/utils/deckyInstaller.ts`

Create a small adapter with fixed identity:

```ts
const EXPECTED_PLUGIN_NAME = "SDH-Ludusavi";
export const INSTALL_TYPE_UPDATE = 2;
export const INSTALL_TYPE_DOWNGRADE = 3;
```

Required behavior:

- Guard all `window.DeckyBackend` access.
- Prefer `DeckyBackend.callable("utilities/install_plugin")`.
- Use `call(...)` only through a verified fallback.
- Return availability state for UI.
- Throw or reject with a user-facing error only from explicit install actions,
  not during render.
- Always pass fixed `SDH-Ludusavi`, candidate version, candidate SHA-256, and
  update/downgrade install type.

### `src/components/PluginUpdateSection.tsx`

Create a dedicated component.

Responsibilities:

- Render installed version and local-build status.
- Render development channel toggle and confirmation modal.
- Render automatic check toggle.
- Trigger manual `Check now`.
- Start automatic checks asynchronously after render when enabled.
- Display cached or current update status.
- Display candidate and action button.
- Run revalidation before install.
- Record pending install metadata only after revalidation succeeds and before
  invoking Decky.
- Invoke Decky adapter only after revalidation and pending-record save.
- Show manual fallback if Decky adapter is unavailable or revalidation cannot
  complete.
- Do not interact with backup/restore operation locks.

### `src/index.tsx`

Render `PluginUpdateSection` near existing version/general settings UI, not
inside backup/restore operation controls.

## Install Action Sequence

When the user presses an install/move/revert button:

1. Disable the action button and show a checking/install-prep state.
2. Call backend `revalidate_plugin_update(candidate)`.
3. If revalidation fails, show error/manual fallback and stop.
4. Determine install type locally:
   - `UPDATE` (`2`) for normal updates and same-base dev-to-stable move;
   - `DOWNGRADE` (`3`) only for explicit user-selected return to older stable.
5. Call `record_update_install_requested(revalidatedCandidate)`.
6. Invoke Decky installer adapter with the freshly validated candidate.
7. Let Decky's native confirmation prompt handle user confirmation.

Do not accept install type from remote manifest data.

## Non-Blocking Automatic Checks

Automatic checks should use a fire-and-forget React effect after render:

```tsx
useEffect(() => {
  if (!settings?.automatic_update_checks || !currentVersion) {
    return;
  }

  void checkForUpdates({ force: false, notify: true });
}, [
  settings?.automatic_update_checks,
  settings?.update_channel,
  currentVersion
]);
```

Backend throttle rules:

- successful automatic `current` or `available` result: cache for 24 hours per
  selected channel;
- automatic failure: record/log failure but do not cache as successful current;
- manual check: bypass successful-result throttle;
- active rate-limit cooldown: suppress automatic and manual network requests
  until retry time.

Deduplicate simultaneous update checks with an update-specific in-flight guard
or equivalent. Do not acquire backup/restore operation locks for update checks.

## Security And Integrity Requirements

- Accept installable artifacts only from validated `beallio/SDH-Ludusavi`
  GitHub Releases.
- Use the manifest SHA-256 and pass it to Decky.
- Treat `SDH-Ludusavi` as fixed trusted installer identity.
- Ignore drafts.
- Stable mode ignores prereleases.
- Development mode requires matching prerelease metadata and `channel: "dev"`.
- Do not store GitHub credentials.
- Do not add `requests`, `httpx`, or another network dependency.
- Do not download, stage, unpack, execute, or replace ZIP files inside
  `SDH-Ludusavi`.
- Document Decky's known failure window: Decky currently removes an installed
  prior plugin before rejecting a ZIP hash mismatch in its install path.
- Manual reinstall of the latest stable ZIP remains the recovery path.

## Edge Cases

- **Canceled Decky prompt:** pending install metadata clears on next load because
  actual loaded version did not change.
- **Failed Decky install:** pending metadata clears unless loaded version matches
  the candidate; manual reinstall may be required if Decky removed the plugin.
- **Stale cached candidate:** cached discovery may render UI but never invokes
  Decky; every install action revalidates.
- **Offline first load:** failed automatic check does not create a 24-hour
  current cache.
- **Rate-limited install revalidation:** do not call Decky with stale metadata;
  show retry time for manual checks when available.
- **Local build installed:** treat `X.Y.Z+...` as stable-equivalent and avoid
  same-base stable replacement.
- **Decky API drift:** only one-click installation degrades; discovery and manual
  release links remain usable.
- **Manual reinstall after pending state:** trust actual loaded version during
  reconciliation, not pending metadata.

## Testing Strategy

Follow strict Red-Green-Refactor. Add failing tests before implementation for
each behavior-changing slice.

### Development Workflow Tests

- Dev workflow emits `X.Y.Z-dev.g<sha>`.
- Stable release workflow remains unchanged.
- `scripts/request_dev_release.sh` still rejects non-stable base versions.

### Version Parsing And Selection Tests

- Parser accepts `X.Y.Z`.
- Parser accepts `X.Y.Z-dev.g<sha>`.
- Parser accepts legacy `X.Y.Z-dev.<sha>`.
- Parser accepts `X.Y.Z+g<sha>` and generic build metadata.
- Local `X.Y.Z+...` is stable-equivalent to `X.Y.Z`.
- Same-base stable is not offered over local build.
- Higher stable is offered over local build.
- Stable wins over same-base dev prerelease.
- Same-base dev builds order by `published_at`, not SHA suffix.
- Missing installed dev publication metadata uses conservative labeling.

### Manifest And HTTP Validation Tests

- Valid stable release accepted.
- Valid preferred dev release accepted.
- Legacy dev release accepted.
- Draft ignored.
- Prerelease ignored in stable mode.
- Wrong plugin name rejected.
- Wrong package name rejected.
- Manifest tag mismatch rejected.
- Manifest asset mismatch rejected.
- Invalid SHA-256 rejected.
- Missing manifest rejected.
- Missing ZIP rejected.
- Multiple matching assets rejected.
- Network timeout returns failed result without crash.
- `403`/`429` with `Retry-After` creates in-session cooldown.
- `X-RateLimit-Remaining: 0` and `X-RateLimit-Reset` creates in-session
  cooldown.

### Persistence Tests

- Old settings load with update defaults.
- `DeckySettingsStore.read()` returns new settings with defaults.
- `update_channel` saves and reloads.
- Invalid stored channel normalizes to stable.
- `automatic_update_checks` saves and reloads.
- Cache fields survive update RPC operations.
- Rate-limit cooldown is not persisted.

### Pending Install Reconciliation Tests

- Pending install promotes when loaded version matches.
- Pending install clears when loaded version did not change.
- Pending install clears after failed install.
- Pending install clears or reconciles after manual install of different
  version.
- Installed metadata is never written merely because install was clicked.

### RPC And Offload Tests

- `check_for_plugin_update` uses the `_call(...)` offload path.
- `revalidate_plugin_update` uses the `_call(...)` offload path.
- Automatic check throttle returns cached successful result without network.
- Manual check bypasses successful-result throttle.
- Manual check does not bypass active cooldown.
- Failed automatic checks do not poison successful-result cache.

### Install Revalidation Tests

- Revalidation succeeds and Decky receives freshly validated URL/SHA/version.
- Manifest mismatch blocks Decky invocation.
- Missing ZIP blocks Decky invocation.
- Missing manifest blocks Decky invocation.
- Stale tag/version mismatch blocks Decky invocation.
- Network failure blocks Decky invocation.
- Rate-limit cooldown blocks Decky invocation.
- Revalidation does not trust stale cached candidate metadata.

### Frontend Adapter And UI Tests

- Adapter prefers `DeckyBackend.callable`.
- Adapter uses `call(...)` only through guarded fallback.
- Missing `window.DeckyBackend` does not throw during render.
- Incompatible Decky backend disables one-click install and preserves manual
  release link.
- Adapter always passes fixed `SDH-Ludusavi`.
- Extended settings types build cleanly.
- Missing older settings normalize safely.
- New update section builds against existing Decky UI imports.

### Manual Steam Deck Validation

- Stable-only default displayed.
- Automatic-check toggle displayed and persisted.
- Dev toggle displays confirmation warning.
- Manual stable check displays current/available state.
- Enabling dev exposes latest eligible prerelease.
- Disabling dev removes dev candidate and never downgrades automatically.
- Install button displays Decky's native prompt.
- Confirmed install reloads plugin and shows new version.
- Canceling Decky's prompt does not mark candidate installed.
- Existing Ludusavi settings and cache survive replacement.
- Missing Decky private API shows manual fallback.

## Documentation Updates

### README

Document:

- initial manual ZIP install;
- update checks after installation;
- stable update flow;
- development release opt-in warning;
- remote dev version format `X.Y.Z-dev.g<short-sha>`;
- local build metadata meaning;
- `Move to Stable` and warned `Revert to Stable`;
- manual recovery if update UI or confirmed install fails;
- Decky's install confirmation and known recovery limitation.

### DEVELOPMENT.md

Document:

- release manifest contract;
- stable/dev/local version ordering;
- same-base dev ordering by GitHub `published_at`;
- future dev version format and legacy parser compatibility;
- private Decky dependency and adapter boundary;
- install type `2` for update and `3` for explicit downgrade;
- no plugin-owned ZIP staging in MVP;
- Decky's uninstall-before-hash-check limitation;
- rate-limit policy and cache/throttle behavior;
- end-to-end dev release validation before stable publication.

## Required Validation Commands

Use the wrapper for project tooling:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
./run.sh bash scripts/check_tdd.sh
git diff --check
```

If unrelated user-owned files are modified, avoid broad formatting that touches
them. Prefer targeted formatting for files changed in the implementation
session.

## Acceptance Criteria

Implementation is complete only when:

- fresh stable installs default to stable-only updates;
- older persisted settings migrate safely;
- update settings persist through Decky's settings manager;
- future dev workflow emits `X.Y.Z-dev.g<short-sha>`;
- updater remains compatible with legacy `X.Y.Z-dev.<sha>`;
- parser handles local `X.Y.Z+...` builds;
- local builds are stable-equivalent for same-base ordering;
- manual update checking discovers a valid stable GitHub Release;
- automatic checks run asynchronously and never block initial UI rendering;
- automatic checks never invoke installation;
- failed automatic checks do not poison successful-result cache;
- development releases require warned opt-in;
- dev-to-stable return is user-initiated only;
- same-base dev releases order by GitHub `published_at`;
- install click revalidates release and manifest before Decky invocation;
- cached discovery data alone never invokes Decky;
- pending install metadata is reconciled on startup;
- installed metadata is promoted only after actual version match;
- Decky's installer receives validated ZIP URL, SHA-256, version, fixed plugin
  name, and correct install type;
- missing Decky private API leaves discovery usable with manual fallback;
- MVP does not add local ZIP staging or direct plugin replacement;
- README and DEVELOPMENT document recovery and private API limitations;
- the full validation suite passes;
- the updater is exercised on a Steam Deck using a development release artifact
  before stable publication.
