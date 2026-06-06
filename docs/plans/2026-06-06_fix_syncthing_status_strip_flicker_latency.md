# Fix Syncthing Status Strip Flicker, Latency, and Icons

## Problem Definition

The Syncthing activity status strip is implemented, but field testing shows three
user-visible defects:

1. The strip blinks or flashes while Syncthing activity is being refreshed.
2. There is avoidable delay between Ludusavi completing its local operation and the
   first confirmed Syncthing activity appearing.
3. The strip uses handwritten cloud SVGs rather than the requested Ionicons:

   ```tsx
   import { IoMdCloudDownload } from "react-icons/io";
   import { IoMdCloudUpload } from "react-icons/io";
   import { IoMdCloudDone } from "react-icons/io";
   ```

The implementation must eliminate avoidable display churn and monitoring latency while
preserving one key product rule: upload or download status must be based on activity
reported by Syncthing. The UI must not claim that a transfer is occurring merely
because the lifecycle phase implies an expected direction.

This is a correction to the Syncthing feature currently present on
`feat/syncthing-status-strip-activity`. The feature is not present on `main`, so the
implementation branch must be based on the current feature branch rather than directly
on `main`.

## Confirmed Current Behavior and Root Causes

### BrowserView reload causes visible flashing

`src/surfaces/autoSyncStatusSurface.tsx` currently processes every status publication
through `syncAutoSyncStatusBrowserView()`. For every visible state, that function:

1. calls `browserView.SetVisible(false)`;
2. recalculates bounds;
3. generates a new data URL;
4. calls `browserView.LoadURL(url)`;
5. waits `AUTO_SYNC_STATUS_SHOW_DELAY`, currently 100 ms;
6. calls `browserView.SetVisible(true)`.

`SyncthingMonitor` republishes the same download or upload status as fresh activity
samples arrive. Consequently, an unchanged status repeatedly hides and reloads the
BrowserView. The reported blink is therefore consistent with the code.

There is no current render identity, last-loaded status, or same-status fast path.

### Frontend polling adds at least one second

`src/controllers/syncthingMonitor.ts` starts polling with an asynchronous
`window.setInterval(..., 1000)`. It does not poll immediately after `startWatch`
returns. The first frontend observation therefore waits for the first interval tick.

The asynchronous interval also permits overlapping polls if an RPC takes longer than
the interval. Overlap can produce stale or out-of-order processing and complicates
cleanup.

### Backend initialization initially exposes no sample

`SyncthingWatch.latest_sample` starts as an empty dictionary. The daemon thread must
resolve initial folder state and obtain the event cursor before it publishes a sample.
Frontend polling during that window receives an empty sample.

If initialization exits early, the watch can remain registered with no useful sample.
The frontend then has no definitive failure to consume.

### Backend activity from events is published one cycle late

`SyncthingWatch._tick()` currently computes and stores a sample before calling
`_tick_events()`. Activity discovered in the current event response therefore cannot
affect the sample until the following loop.

### Completion can count repeated reads

The frontend increments `settledCount` whenever a poll returns `sample.settled`.
Because the backend returns its latest cached sample, multiple frontend polls can read
the same backend sample. The existing code does not use `timestamp_unix` to distinguish
new samples, so one settled sample can be counted multiple times.

### Syncthing active states use result-state timeout behavior

`scheduleAutoSyncStatusHide()` treats only `checking`, `backing_up`, and `restoring` as
running states. Syncthing download and upload states therefore use the two-second
result timeout. Continued polling happens to republish and reset that timeout, but it
also triggers BrowserView reloads. This coupling must be removed.

## Goals

- Keep an unchanged visible Syncthing status continuously visible without hiding,
  navigating, or replaying the 100 ms reveal delay.
- Preserve BrowserView recreation and delayed reveal for genuine state transitions
  where stale pixels must be avoided.
- Poll once immediately after watch creation.
- Prevent overlapping frontend poll RPCs.
- Process fresh samples at a bounded cadence without treating repeated reads as new
  evidence.
- Make event-derived activity visible in the same backend sampling cycle.
- Ensure initialization failures produce a consumable failure result.
- Render the requested `react-icons` cloud download, upload, and done glyphs.
- Keep all Syncthing monitoring advisory and non-blocking.
- Preserve conflict and error precedence.
- Preserve existing RPC names and response envelopes.

## Non-Goals

- Do not show speculative upload/download status immediately after a Ludusavi operation.
- Do not add a neutral "Syncthing checking" status in this change.
- Do not block game launch, game exit, backup, restore, or conflict resolution while
  Syncthing initializes or settles.
- Do not add a user setting for polling intervals or Syncthing behavior.
- Do not add a new frontend or Python dependency.
- Do not replace the BrowserView status strip with a React overlay.
- Do not change Syncthing folder resolution or Ludusavi `backupPath` ownership.
- Do not change package versions, create release tags, publish releases, or dispatch
  release workflows.
- Do not merge the implementation branch.

## Branch and Repository Protocol

The implementation agent must:

1. Start from the clean current branch:

   ```bash
   git switch feat/syncthing-status-strip-activity
   git status --short
   git switch -c fix/syncthing-status-strip-flicker-latency
   ```

2. Stop and report if that branch is not clean. Do not stash, revert, overwrite, or
   commit unrelated user work.
3. Keep every implementation and documentation commit on
   `fix/syncthing-status-strip-flicker-latency`.
4. Read `AGENTS.md`, `.protocol`, `DEVELOPMENT.md`, this plan, and the implementer
   skill before source changes.
5. Perform and print the `AGENT_PROTOCOL_HANDSHAKE`.
6. Run project tooling through `./run.sh`.
7. Keep generated caches and temporary artifacts under `/tmp/sdh_ludusavi`.
8. Use `ty` as the Python type checker.
9. Follow strict Red-Green-Refactor for every behavior-changing phase.
10. Use atomic Conventional Commits. Do not combine unrelated backend, monitor, UI,
    and documentation work into one commit.

The plan file should be committed first as a documentation-only commit:

```text
docs(syncthing): plan status strip stability correction
```

## Architecture Overview

Relevant ownership remains:

- `src/surfaces/autoSyncStatusSurface.tsx`
  - BrowserView creation and normalization;
  - HTML/data URL rendering;
  - status text and icon markup;
  - visibility, reveal, and hide timers;
  - BrowserView destruction and global reset.
- `src/controllers/syncthingMonitor.ts`
  - frontend watch lifecycle;
  - start/poll/stop RPC sequencing;
  - sample-to-status mapping;
  - completion settling policy;
  - frontend timeout and disposal.
- `src/controllers/gameLifecycleController.tsx`
  - starts monitoring before automatic pre-game and post-game Ludusavi RPCs;
  - owns conflict, error, backup, restore, and lifecycle precedence.
- `py_modules/sdh_ludusavi/syncthing/watcher.py`
  - backend watch thread;
  - initial state and cursor acquisition;
  - event/status/rate sampling;
  - latest-sample publication;
  - watch manager start, poll, stop, and cleanup.
- `py_modules/sdh_ludusavi/syncthing/activity.py`
  - activity computation;
  - `_serialize_sample()`, including `timestamp_unix`.
- `tests/test_frontend_static.py`
  - established frontend architecture and behavior regression fence.
- `tests/test_syncthing.py`
  - backend activity and watch-manager regression coverage.

No new subsystem, RPC endpoint, persistence model, or public setting is required.

## Core State and Invariants

### BrowserView render identity

Add private module state that records which status is currently loaded in the
BrowserView. A suitable representation is:

```ts
let loadedAutoSyncStatus: AutoSyncStatusKind | null = null;
```

The rendered HTML currently varies only by `state.status`; game name, application ID,
source, tracked state, and result status are logged metadata and are not included in
the BrowserView HTML. Therefore, the loaded render identity should be the status kind,
not the entire `AutoSyncStatusState` object.

Required invariants:

- `loadedAutoSyncStatus` is assigned only after `LoadURL(url)` returns successfully.
- It is reset to `null` when:
  - the strip is hidden and navigated to `about:blank`;
  - the BrowserView is destroyed;
  - the status surface is reset;
  - a verification reset destroys and recreates the BrowserView;
  - BrowserView creation or navigation fails in a way that leaves loaded content
    uncertain.
- A visible state whose status equals `loadedAutoSyncStatus` must not hide or reload
  the BrowserView.
- A changed status must continue through the existing hide/load/delayed-show flow.

### Frontend poll scheduling

Replace interval ownership with one pending timeout:

```ts
private activePollTimeout: number | null = null;
```

There must be no `setInterval` in `SyncthingMonitor`.

Required scheduling constants:

```ts
const EMPTY_SAMPLE_RETRY_MS = 250;
const ACTIVE_POLL_INTERVAL_MS = 500;
const MAX_WATCH_DURATION_MS = 120_000;
```

Required invariants:

- At most one poll RPC is in flight.
- At most one next-poll timeout is scheduled.
- The first poll starts immediately after a successful start result.
- The next timeout is scheduled only after the prior poll resolves and its result is
  processed.
- Stop, replacement start, timeout, backend stop, failure, and dispose all cancel the
  pending timeout.
- Stale asynchronous results cannot publish or schedule another poll.

### Distinct backend samples

Use the existing `sample.timestamp_unix` as the sample identity.

Maintain:

```ts
let lastProcessedTimestamp: number | null = null;
```

Rules:

- A missing or non-finite timestamp is not valid fresh evidence. Log it at debug or
  warning level and continue polling without changing activity/settled counters.
- If `timestamp_unix === lastProcessedTimestamp`, do not:
  - republish download/upload;
  - set `activityObserved`;
  - increment or reset `settledCount`.
- Update `lastProcessedTimestamp` before processing a valid fresh sample so errors in
  callbacks cannot cause the same sample to be counted again.
- A fresh activity sample resets `settledCount` to zero.
- Completion requires three fresh, distinct, consecutive settled samples after
  activity has been observed.

## Detailed Implementation

### Phase 1: Baseline and RED tests

Before source changes:

1. Run baseline focused tests:

   ```bash
   ./run.sh uv run pytest tests/test_syncthing.py tests/test_frontend_static.py
   ./run.sh pnpm run typecheck
   ```

2. If baseline fails, save output under `/tmp/sdh_ludusavi/`, diagnose it, and do not
   attribute existing failures to the new implementation.
3. Add focused failing tests before each behavior change.
4. Run the focused tests and preserve the expected RED output in the session log.

Frontend RED coverage must assert:

- exact imports for `IoMdCloudDownload`, `IoMdCloudUpload`, and `IoMdCloudDone`;
- a mapping from the three Syncthing statuses to those imported components;
- removal of the old handwritten Syncthing SVG path fragments;
- existence of loaded-status state;
- same-status fast path appears before the normal `SetVisible(false)` and `LoadURL`
  path;
- the same-status path does not clear a still-needed reveal timeout;
- download/upload are recognized as Syncthing active states;
- Syncthing active timeout does not set `autoSyncStatusTimedOut`;
- monitor polling uses recursive `setTimeout`, not `setInterval`;
- first polling is invoked immediately after successful watch start;
- duplicate timestamps are ignored;
- pending poll timeout is cleared on stop and dispose.

Backend RED coverage must assert:

- baseline sample publication occurs before event-cursor acquisition completes;
- event processing occurs before sample serialization in a tick;
- initialization failure stores a structured failure result;
- polling returns an atomic complete dictionary rather than exposing partial mutation.

Static tests may be used where the project already relies on them, but backend timing
and ordering behavior should use executable unit tests with mocks/events rather than
source-string assertions alone.

### Phase 2: BrowserView idempotent refresh

Refactor `syncAutoSyncStatusBrowserView()` carefully:

1. Obtain or create the BrowserView and validate methods as today.
2. Compute current bounds.
3. If `state.visible` is false:
   - cancel reveal state as today;
   - hide the BrowserView;
   - navigate to `about:blank` best-effort;
   - set `loadedAutoSyncStatus = null`;
   - return.
4. If `state.visible` is true and `state.status === loadedAutoSyncStatus`:
   - update bounds;
   - ensure stacking order and non-focus state remain correct;
   - if no initial reveal is pending, ensure the BrowserView remains visible;
   - if an initial reveal timeout is pending, do not clear or replace it;
   - do not generate/reload the data URL;
   - return.
5. For a visible changed or initially unloaded status:
   - clear the previous reveal timeout;
   - increment the show generation;
   - render HTML and build the data URL;
   - hide the BrowserView;
   - apply bounds;
   - call `LoadURL(url)`;
   - set `loadedAutoSyncStatus = state.status`;
   - schedule the existing 100 ms guarded reveal;
   - preserve stacking order and focus behavior.
6. On an exception during the changed-status path:
   - set `loadedAutoSyncStatus = null`;
   - log the existing warning;
   - leave the next publication able to retry.

Do not remove the 100 ms delay globally. It remains useful when loading genuinely new
BrowserView content.

`publishAutoSyncStatus()` must continue updating `currentAutoSyncStatusState`, logging
metadata, and rescheduling the hide/watchdog timer even when rendering is deduplicated.

### Phase 3: Syncthing timer classification

Introduce explicit helpers instead of growing a dense boolean expression:

```ts
function isLudusaviRunningStatus(status: AutoSyncStatusKind): boolean
function isSyncthingActiveStatus(status: AutoSyncStatusKind): boolean
```

Rules:

- Ludusavi running statuses:
  - `checking`;
  - `backing_up`;
  - `restoring`.
- Syncthing active statuses:
  - `syncthing_downloading`;
  - `syncthing_uploading`.
- Both groups use a ten-second watchdog.
- Only expiration of a Ludusavi running status sets `autoSyncStatusTimedOut = true`.
- Syncthing active expiration simply hides the strip.
- `syncthing_complete`, `has_backup`, `unknown`, `error`, and `conflict` retain the
  existing two-second result timeout unless existing behavior specifies otherwise.

The ten-second Syncthing watchdog is not a transfer timeout. Fresh status publications
refresh it. Its purpose is to remove a stale strip if monitoring fails or stops
publishing.

### Phase 4: Requested Ionicons in BrowserView HTML

Use the exact named imports from `react-icons/io`.

The BrowserView displays raw HTML from a data URL, so JSX cannot be mounted inside it.
Do not import `react-dom/server`. Instead, add a narrow serializer for the known
`react-icons` element shape:

1. Call the selected `IconType` with:

   ```ts
   {
     size: 18,
     "aria-hidden": true,
     focusable: false
   }
   ```

2. The returned element is the `IconBase` React element. Read:
   - `element.props.attr.viewBox`;
   - `element.props.children`, which contains the icon's path element tree.
3. Serialize only the supported intrinsic tags used by these three icons:
   - `path`;
   - optionally `g` if the installed pinned icon representation requires it.
4. Serialize only a fixed allowlist of SVG attributes required by those nodes:
   - `d`;
   - `fill`;
   - `fillRule`;
   - `clipRule`;
   - `stroke`;
   - `strokeWidth`;
   - `strokeLinecap`;
   - `strokeLinejoin`;
   - `opacity`;
   - `transform`.
5. Convert React camel-case attribute names to SVG markup names.
6. Escape attribute values for `&`, `"`, `<`, and `>`.
7. Reject unsupported tags or malformed elements by logging a warning and falling back
   to a minimal safe empty SVG. Do not inject arbitrary `dangerouslySetInnerHTML`.
8. Wrap the serialized children in:

   ```html
   <svg viewBox="..." width="18" height="18"
        fill="currentColor" aria-hidden="true" focusable="false">
   ```

9. Cache the resulting string for each Syncthing status at module scope or through a
   lazy memoized map.

Map:

- `syncthing_downloading` -> `IoMdCloudDownload`;
- `syncthing_uploading` -> `IoMdCloudUpload`;
- `syncthing_complete` -> `IoMdCloudDone`.

Keep existing handwritten SVG handling for checking, backup, restore, success, unknown,
and error states.

The implementation must compile under the existing strict TypeScript settings,
including `noUnusedLocals`, `noImplicitAny`, and `noImplicitReturns`.

### Phase 5: Serialized frontend polling

Refactor `SyncthingMonitor` around a private polling method.

Recommended internal structure:

```ts
private schedulePoll(delayMs: number, context: WatchContext): void
private async pollOnce(context: WatchContext): Promise<void>
private processSample(context: WatchContext, sample: SyncthingActivitySample): boolean
```

`WatchContext` may be a private type containing:

- watch ID;
- session token;
- phase;
- game name;
- application ID;
- source;
- started-at timestamp;
- activity-observed flag;
- settled count;
- last processed sample timestamp.

If a private context type is introduced, it replaces closure variables and becomes the
single state used for one watch. Do not expose it publicly.

Required flow:

1. Increment the session token.
2. Stop any previous watch and cancel its timeout.
3. Await `startWatch`.
4. If the session token changed while awaiting:
   - stop the newly returned backend watch when applicable;
   - return without publishing.
5. If start was skipped or failed:
   - log and return;
   - do not change Ludusavi status.
6. Create/store active context.
7. Call `pollOnce(context)` immediately without a preceding timeout.
8. `pollOnce` validates context before and after awaiting `pollWatch`.
9. On an empty sample, schedule another poll after 250 ms.
10. On a fresh populated sample:
    - process it;
    - if still active and incomplete, schedule after 500 ms.
11. On a duplicate sample:
    - do not republish or change counters;
    - schedule after 500 ms.
12. Before polling or scheduling, compare `Date.now() - startedAt` with 120,000 ms.
13. On timeout:
    - clear active frontend state;
    - stop the backend watch best-effort;
    - do not publish complete.
14. On completion:
    - publish `syncthing_complete` exactly once;
    - clear active state before awaiting backend stop;
    - stop the backend watch best-effort.
15. On RPC error or thrown exception:
    - log;
    - clear active state;
    - stop the backend watch best-effort.

Status mapping for a fresh sample:

1. If `sample.downloading`, publish `syncthing_downloading`.
2. Else if `sample.uploading`, publish `syncthing_uploading`.
3. Else if `sample.update_in_progress`, publish:
   - `syncthing_downloading` for `pre_game`;
   - `syncthing_uploading` for `post_game`.
4. Else if activity was previously observed and `sample.settled`:
   - increment the fresh settled count;
   - publish complete only at three.
5. Else reset settled count to zero.

Activity is considered observed when a fresh sample has any existing activity signal:

- `downloading`;
- `uploading`;
- `update_in_progress`;
- status `ACTIVE_TRANSFER`;
- status `SCANNING`;
- status `UPDATE_NEEDED`;
- status `PREPARING`;
- status `INDEXING_OR_SEQUENCE_UPDATE`.

Preserve fire-and-forget calls in `gameLifecycleController.tsx`. Do not `await`
`syncthingMonitor.start()` in lifecycle handlers.

### Phase 6: Backend initial and event-fresh samples

Refactor `SyncthingWatch` with the following exact ordering.

Initialization:

1. Resolve initial folder state/runtime.
2. Initialize local calculation state:
   - previous totals;
   - rates;
   - remote progress;
   - local activity;
   - polling constants.
3. Compute and publish a baseline sample immediately.
4. Obtain the event cursor.
5. Enter the normal loop.

If initial folder-state or event-cursor setup fails:

- assign a complete failure dictionary to `latest_sample`:

  ```python
  {
      "status": "failed",
      "reason": "watch_initialization_failed",
      "message": str(exc),
  }
  ```

- log the warning without secrets;
- return from the thread.

Normal tick ordering:

1. Capture a monotonic timestamp for connection and folder polling.
2. Poll connection totals and compute rates.
3. Poll current folder status and detect sequence changes.
4. Poll/process events.
5. Capture a new monotonic timestamp after the event request returns.
6. Prune remote and local activity using the post-event timestamp.
7. Compute and atomically assign the latest sample using the post-event state.
8. Return updated calculation state.

This ordering ensures events received during the current long poll are included in the
sample published immediately afterward.

Do not mutate `latest_sample` in place. Build a complete dictionary and assign it once.
`poll_watch()` may continue returning `dict(watch.latest_sample)` because the nested
sample is immutable after publication. If tests reveal callers can mutate nested state,
use `copy.deepcopy` at the manager boundary and document that decision.

Do not change `_serialize_sample()` or remove `timestamp_unix`. Each serialization must
continue producing a new wall-clock timestamp.

### Phase 7: Documentation and session record

Update user-facing or durable documentation only where behavior descriptions are now
incorrect:

- `docs/specs/custom_status_bar_ui.md`
  - unchanged statuses do not navigate/reveal again;
  - active Syncthing statuses use an activity watchdog;
  - requested Ionicon mapping.
- Existing Syncthing plan may remain historical; do not rewrite its original design
  decisions.
- Add a session record under `docs/agent_conversations/` including:
  - date;
  - objective;
  - branch;
  - files modified;
  - RED tests and observed failures;
  - implementation decisions;
  - focused/full validation results;
  - Codex review findings and fixes;
  - any network-only validation blocker.

README changes are not required unless the implementation changes documented
user-visible capability rather than correcting the existing behavior.

## Edge Cases and Failure Modes

The implementation and tests must address:

- An identical status arrives during the original 100 ms reveal delay. It must not
  cancel the only reveal timer.
- Bounds change while the status remains the same. Bounds must update without reload.
- `LoadURL` throws. The loaded marker must remain clear so a later update retries.
- The BrowserView is destroyed while a reveal timeout is pending. Existing generation
  and visibility guards must prevent showing a destroyed/stale view.
- A backend start resolves after a newer session starts. The stale watch must be
  stopped and must never poll or publish.
- A poll resolves after stop/dispose/replacement. It must not publish or schedule.
- The backend returns the same sample many times. It must count once.
- The backend returns a non-finite or absent timestamp. It must not count as fresh
  evidence or complete the watch.
- A poll RPC takes longer than 500 ms. No second poll may overlap it.
- Activity alternates download/upload. Genuine state changes may reload once; repeated
  samples for either state must not flicker.
- Activity resumes during settling. Settled count resets to zero.
- Backend initialization fails before cursor acquisition. Frontend receives failure
  and tears down rather than polling an empty sample until timeout.
- Syncthing is not running or the Ludusavi path is outside Syncthing. Existing skipped
  behavior remains silent and non-blocking.
- The watcher reaches 120 seconds without observed activity or completion. It stops
  without falsely publishing complete.
- Plugin unload occurs with an active watch or pending frontend timeout. Both layers
  clean up idempotently.

## Testing Strategy

### Frontend tests

Extend the existing static regression suite, and add executable TypeScript-oriented
tests only if the current project already has an appropriate runner. Do not introduce a
new test framework solely for this fix.

Static tests should inspect the specific owner modules rather than relying only on the
concatenated frontend source.

Required assertions:

- exact Ionicon imports and mapping;
- old cloud path data absent;
- serializer allowlist and escaping present;
- same-status fast path precedes changed-status reload;
- loaded marker reset in hide/destroy/reset paths;
- Syncthing active timeout classification;
- `autoSyncStatusTimedOut` limited to Ludusavi running states;
- no `setInterval` in `syncthingMonitor.ts`;
- immediate `pollOnce` call after start;
- 250 ms empty retry, 500 ms normal poll, 120,000 ms wall-clock limit;
- timestamp validation and duplicate suppression;
- timeout cleanup in stop/dispose/replacement.

### Backend tests

Use mocks, `threading.Event`, and deterministic method calls. Avoid arbitrary sleeps
where synchronization primitives can prove ordering.

Required tests:

- baseline sample is assigned before a blocked `get_event_cursor()` completes;
- initial cursor failure assigns `watch_initialization_failed`;
- an event changing activity is reflected by the sample from the same `_tick()` call;
- fresh serialized samples have distinct timestamps under a patched deterministic
  clock;
- manager poll returns a complete latest result;
- existing start, duplicate replacement, stop, and stop-all tests remain green.

### Manual Deck verification

When a Deck/development deployment is available, record:

1. Post-game backup with sustained Syncthing upload:
   - local save completion may appear first;
   - upload appears only after observed activity;
   - upload strip remains continuous without flashing.
2. Pre-game Syncthing download:
   - download icon and text appear;
   - repeated samples do not flash;
   - local restore behavior remains unchanged.
3. Completion:
   - cloud-done appears after three distinct settled samples;
   - it remains for approximately two seconds.
4. Syncthing unavailable:
   - no Syncthing strip appears;
   - Ludusavi flow remains unchanged.
5. Activity direction transition:
   - one legitimate transition is acceptable;
   - no periodic blinking occurs while the state remains unchanged.

If Deck access is unavailable, explicitly report manual verification as pending; do not
claim it passed.

## Validation Gates

Focused validation:

```bash
./run.sh uv run pytest tests/test_syncthing.py tests/test_frontend_static.py tests/test_service.py tests/test_main.py
./run.sh pnpm run typecheck
./run.sh pnpm run build
```

Before every implementation commit, run targeted tests and applicable lint/type checks.

Full validation:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh bash scripts/check_tdd.sh
./run.sh pnpm run typecheck
./run.sh pnpm run build
./run.sh pnpm run verify
git diff --check
```

If `pnpm verify` fails only because `pnpm audit` cannot reach the registry, capture and
report that network gate separately. Do not describe the full verification suite as
green.

## Required Codex Review-Fix Loop

After implementation, documentation, commits, and local validation, run:

```bash
npx @openai/codex review --base main
```

This exact command is required even though the implementation branch is based on the
Syncthing feature branch. The review must see the complete feature-plus-fix delta
against `main`.

For every review:

1. Save the output under `/tmp/sdh_ludusavi/`.
2. Evaluate each finding against repository evidence.
3. Fix every valid finding.
4. Add or update a regression test before behavior-changing fixes.
5. Rerun relevant focused checks.
6. Rerun the full validation gate when changes affect shared behavior.
7. Commit fixes atomically on
   `fix/syncthing-status-strip-flicker-latency`.
8. Repeat `npx @openai/codex review --base main` until there are no valid blocking
   findings.

Do not switch to `main` for fixes or commits. Do not use the implementer skill's generic
`--branch` review command in place of the exact user-required `--base main` command.

## Suggested Atomic Commit Sequence

The implementer may split a phase further when needed, but must not combine unrelated
layers:

1. `docs(syncthing): plan status strip stability correction`
2. `test(syncthing): cover watcher sample timing and failures`
3. `fix(syncthing): publish event-fresh watcher samples`
4. `test(frontend): cover serialized Syncthing monitoring`
5. `fix(frontend): serialize Syncthing activity polling`
6. `test(status-strip): cover stable refresh and Ionicons`
7. `fix(status-strip): prevent unchanged Syncthing reloads`
8. `fix(status-strip): render requested Syncthing Ionicons`
9. `docs(syncthing): record status strip correction`
10. Additional review-fix commits, each scoped to one valid finding.

Tests and implementation may be committed together only when repository hook policy
requires the behavior and its regression test to land atomically, but the RED test must
still be created and run first in the working tree.

## Acceptance Criteria

- Repeated `syncthing_downloading` publications do not call `SetVisible(false)` or
  `LoadURL` after the first successful render.
- Repeated `syncthing_uploading` publications behave the same way.
- An unchanged update arriving during the 100 ms initial reveal does not prevent the
  strip from becoming visible.
- A real status transition still performs one guarded reload/reveal.
- Bounds can refresh without data URL navigation.
- Download and upload remain visible while fresh activity arrives and disappear after
  a ten-second publication lapse.
- Syncthing watchdog expiration cannot suppress a later Ludusavi completion state.
- The first frontend poll begins immediately after watch creation.
- No frontend poll calls overlap.
- Empty startup samples retry after 250 ms; populated polling uses 500 ms.
- Completion requires three distinct settled sample timestamps after observed activity.
- Event-derived activity is included in the same backend tick's published sample.
- Backend initialization failure is surfaced as a failure result rather than an
  indefinitely empty watch.
- The exact `IoMdCloudDownload`, `IoMdCloudUpload`, and `IoMdCloudDone` components are
  the source of the three Syncthing glyphs.
- No new dependency, RPC, status kind, setting, or release change is introduced.
- Ludusavi launch, exit, backup, restore, conflict, and error behavior remains
  non-blocking and unchanged.
- All automated gates pass, except any explicitly documented external network-only
  blocker.
- The final Codex review-fix loop has no unresolved valid blocking findings.

## Explicit Assumptions

- Some delay inside Syncthing between a filesystem write and Syncthing reporting scan
  or transfer activity is unavoidable and outside the plugin's latency guarantee.
- The plugin guarantees removal of its own initial one-second polling delay and
  one-cycle event publication delay; it does not guarantee immediate Syncthing
  detection.
- `react-icons` remains pinned at the existing project version during this fix.
- The selected Ionicons are hook-free and return the standard `IconBase` element shape
  in the pinned version. Tests must fail clearly if that shape changes.
- `timestamp_unix` is the backend sample identity for this change. No new sequence
  field is added.
- Conflict and error status precedence remains unchanged.
- Manual Deck verification is desirable but cannot be claimed without an available
  target environment.
