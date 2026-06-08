# Implementation Plan: Fix Syncthing UI Getting Stuck on "Uploading"

## 1. Executive Summary
The Syncthing activity monitor gets permanently stuck on "SYNCTHING UPLOADING" because it incorrectly treats Syncthing's `remoteSequence` as a remote-acknowledgment mechanism. Syncthing's `/rest/db/status` contract does not define `remoteSequence` for this purpose; sequence numbers are local database counters and cannot be compared across devices. 

This plan removes the flawed acknowledgment logic, cleans up dead code paths (`shared_device_ids` and `remoteSequence`), and redefines `SYNCTHING COMPLETE` as "locally observed activity settling." As intentional adjacent correctness hardening, it also blocks completion on local error states. Existing distinct-timestamp deduplication remains unchanged, and publication coverage remains owned by the lifecycle controller.

## 2. Core Definitions
**Completion Semantics**: `SYNCTHING COMPLETE` means that upload activity observable from the Steam Deck has locally settled (the backend reports idle, there are no active transfers, and activity signals have expired). **It does not guarantee that every remote device has completely downloaded the save.**

## 3. Proposed Changes

### py_modules/sdh_ludusavi/syncthing/_types.py
1. **ActivityStatus Dataclass**: Remove `pending_remote_ack` and `lagging_remote_devices`.
2. **FolderRuntime Dataclass**: Remove `remote_sequence: dict[str, int]`.
3. **FolderSelection Dataclass**: Remove `shared_device_ids: tuple[str, ...] = ()`.
4. **parse_folder_runtime**: Remove logic parsing `raw_remote_sequence = data.get("remoteSequence")`.

### py_modules/sdh_ludusavi/syncthing/activity.py
1. **has_pending_remote_ack**: Delete this function entirely.
2. **compute_activity_status**: 
   - Remove `shared_device_ids` from the function signature.
   - Remove `pending_remote_ack, lagging_remote_devices = has_pending_remote_ack(runtime, shared_device_ids)`.
   - Update the `settled = (...)` calculation to remove `not pending_remote_ack`.
   - **Adjacent Error-State Hardening**: Define `settled` to explicitly enforce no errors:
     - `normalized_state not in ("error", "unknown")` (or the equivalent `ERROR_STATES` constant).
     - `runtime.pull_errors == 0`
     - `not runtime.watch_error`
   - Remove `pending_remote_ack` and `lagging_remote_devices` from the `ActivityStatus` return block.
3. **process_event**:
   - In the `LocalIndexUpdated` event handling, remove `remote_sequence=runtime.remote_sequence` when reconstructing `FolderRuntime`.

### py_modules/sdh_ludusavi/syncthing/folders.py & __init__.py
1. **folder_shared_device_ids API Break**: Delete this helper function and its export from `__init__.py`. This is an intentional internal API break (a repository-wide consumer search will confirm it is safe to remove).
2. **folder_selection_from_config**: Remove `shared_device_ids=folder_shared_device_ids(folder)`.

### py_modules/sdh_ludusavi/syncthing/watcher.py
1. **_tick_folder_status**: Remove `shared_device_ids=self.folder.shared_device_ids,` from the `compute_activity_status` call.

### Documentation
1. **README.md**: Explicitly disclaim remote delivery. Clarify that "SYNCTHING COMPLETE" reflects locally observable quiescence and does not confirm receipt by every peer.
2. **docs/specs/custom_status_bar_ui.md**: Update to reflect the local quiescence definition.
3. **docs/specs/sdh_ludusavi_sync.md**: Update this core spec to definitively own the completion behavioral semantics, confirming completion reflects local settling, not remote delivery guarantees.

### Dependencies
**No new dependencies** will be added. All fixes utilize the existing standard library and previously installed packages.

## 4. Testing Strategy & Strict TDD

### Python Backend Tests
1. **tests/test_watcher.py Refactor**: Before removing `shared_device_ids` from `FolderSelection`, convert all affected test constructors that use positional arguments to explicit named arguments to prevent fragile parameter binding when the field is removed.
2. **Strict TDD for Sequence Bug (RED)**: Before deleting or rewriting the unequal-sequence fixture, change its assertion for `sequence=12` and `remoteSequence={"peer1": 10}` to expect `settled=True`. Run the focused test and confirm it fails because `pending_remote_ack` still blocks settlement.
3. **Sequence Cleanup (GREEN)**: Remove the faulty acknowledgment implementation, then update all `compute_activity_status` fixtures and calls in `tests/test_syncthing.py` to remove `shared_device_ids` and `remote_sequence`. Run the focused test again and confirm it passes.
4. **Error State TDD**: Write RED tests asserting that `pull_errors > 0` and populated `watch_error` strictly prevent `settled=True`; then implement the explicit error predicates. Keep folder state `error` as regression coverage because the existing `normalized_state == "idle"` requirement already prevents it from settling.
5. **Backend Test Boundary**: Keep these backend tests stateless and limited to individual `compute_activity_status` results. Multi-sample watch recovery belongs to the frontend monitor tests.

### Frontend Monitor Tests
1. **syncthingMonitor.test.ts**: 
   - No behavioral modification to the code is needed. The existing deduplication logic will be preserved.
   - Update the existing "buffered completion returns complete" test to verify that `activatePostGameHandoff` resolves to `{status: "complete"}` and explicitly assert that `mockOnStatus` is NOT called (because `gameLifecycleController` owns publication).
   - Add a stateful error-recovery test: observe upload activity, process an error or otherwise non-settled sample, then process three distinct error-free `settled=True` samples and assert that the same watch completes. Also assert that an error arriving after one or two settled samples resets or blocks completion until three new valid settled samples arrive.
   - Remove obsolete `pending_remote_ack` and `lagging_remote_devices` fields from all frontend test fixtures as metadata cleanup.
2. **gameLifecycleController.test.ts**: Keep this file as the sole location for publication-level assertions of the `syncthing_complete` UI event.

### Cleanup Verification
After implementation and test updates, run a repository-wide search and require zero remaining results for:
- `has_pending_remote_ack`
- `pending_remote_ack`
- `lagging_remote_devices`
- `remote_sequence`
- `shared_device_ids`
- `folder_shared_device_ids`

The search must include backend source, frontend source, tests, and package exports. Historical plans, reviews, and session logs may retain these names as documentation of the removed behavior.

### Validation Pipeline
All checks must pass:
- `./run.sh uv run ruff check .`
- `./run.sh uv run ruff format --check .`
- `./run.sh uv run ty check py_modules/sdh_ludusavi/`
- `./run.sh uv run pytest`
- `./run.sh pnpm run typecheck`
- `./run.sh pnpm run test`
- `./run.sh pnpm run build`

### Required Artifacts
- A comprehensive session log must be written to `docs/agent_conversations/2026-06-08_fix_syncthing_pending_remote_ack.json` tracking the completed work and execution.
