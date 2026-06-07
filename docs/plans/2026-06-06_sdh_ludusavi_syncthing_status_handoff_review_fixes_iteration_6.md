# Plan: Address Codex Review Iteration 6, 7 & 8 Findings

## Problem Definition
Codex Review Iteration 6, 7 & 8 raised four P2 findings:
1. **Do not map download-only progress to uploading**: In `syncthingMonitor.ts` at `processSample`, for post-game samples, a download-only sample sets `update_in_progress = true`. The current conditional check maps it to `uploading` in post-game because it evaluates `sample.update_in_progress` without excluding downloads, even though the preceding activity check successfully rejects downloads. This causes a false `SYNCTHING UPLOADING` status, or blocks later legitimate uploads.
2. **Remove contexts after pending activity timeout**: In `syncthingMonitor.ts` at `schedulePendingActivityTimeout`, when a post-game watch hits the pending activity timeout, the context is marked as `cancelled = true` but is never passed to `maybeCleanupContext`. This causes the watch context to leak and permanently remain in `contexts` for the lifetime of the plugin.
3. **Require a valid folder-state baseline before readiness**: When the initial `/rest/db/status` fails but event cursor initialization succeeds, the backend returns `"unknown"` as the `folder_state` while still publishing a finite-timestamp baseline. The monitor currently considers any finite timestamp as ready and initializes the watch, showing `SYNCTHING PREPARING` instead of falling back to local-backup success. We must verify that `sample.folder_state !== "unknown"` before resolving readiness.
4. **Preserve uploads when download is also active**: In `syncthingMonitor.ts`'s `processSample` function, the post-game activity check currently rejects the sample if `sample.downloading` is true, even if `sample.uploading` is also true. This incorrectly hides actual upload activity when a concurrent download is active, leading to incorrect timeout fallbacks.

## Architecture Overview
1. In `src/controllers/syncthingMonitor.ts`'s `processSample` function, refine the `sample.update_in_progress` mapping so it only maps to `uploading` when it is not a post-game download:
   ```typescript
   } else if (sample.update_in_progress && (!sample.downloading || context.phase !== "post_game")) {
     newStatus = context.phase === "pre_game" ? "downloading" : "uploading";
     context.settledCount = 0;
   }
   ```
2. In `src/controllers/syncthingMonitor.ts`'s `schedulePendingActivityTimeout` function, invoke `this.maybeCleanupContext(context)` after marking the context cancelled:
   ```typescript
   log("info", `Syncthing pending activity timed out: generation=${context.generation}`);
   context.cancelled = true;
   context.publicationEnabled = false;
   this.clearPollTimeout();

   const wID = context.watchID;
   context.watchID = null;
   if (wID !== null) {
     void this.stopWatchSafe(wID);
   }

   this.onStatus("has_backup", {
     source: "timeout",
     gameName: context.gameName,
     appID: context.appID,
   });

   this.maybeCleanupContext(context);
   ```
3. In `src/controllers/syncthingMonitor.ts`'s `pollOnce` function, refine the `isValidSample` check to reject `"unknown"` folder state on initialization:
   ```typescript
   if (!context.initialized) {
     const isValidSample = Number.isFinite(sample.timestamp_unix) && sample.folder_state !== "unknown";
     if (isValidSample) {
       context.initialized = true;
       log("info", `Syncthing watch initialized: generation=${context.generation} elapsed_ms=${Date.now() - context.startedAt}`);
       context.resolveReadiness("ready");
     } else {
       this.schedulePoll(EMPTY_SAMPLE_RETRY_MS, context);
       return;
     }
   }
   ```
4. In `src/controllers/syncthingMonitor.ts`'s `processSample` function, update the post-game `hasActivity` check so that `sample.uploading === true` is preserved even if `sample.downloading === true`:
   ```typescript
   const hasActivity = context.phase === "post_game"
     ? sample.uploading ||
       ((sample.update_in_progress ||
         sample.status === "ACTIVE_TRANSFER" ||
         sample.status === "SCANNING" ||
         sample.status === "UPDATE_NEEDED" ||
         sample.status === "PREPARING" ||
         sample.status === "INDEXING_OR_SEQUENCE_UPDATE") && !sample.downloading)
     : ...
   ```

## Core Data Structures
No new data structures.

## Public Interfaces
No public interface signatures change.

## Dependency Requirements
No new dependencies are required.

## Testing Strategy
We will implement unit tests in `src/controllers/syncthingMonitor.test.ts` to enforce Red-Green-Refactor:
1. **Download-only Update In Progress Check**:
   Add a test verifying that when a post-game watch processes a sample with `update_in_progress: true`, `downloading: true`, and `uploading: false`, it does NOT set the status to `uploading` (remains `idle`).
2. **Pending Timeout Context Cleanup**:
   Add a test verifying that when the pending activity timeout fires, the context is deleted from the `contexts` map.
3. **Valid Baseline Initialization Check**:
   Add a test verifying that a first sample with `folder_state: "unknown"` does not resolve readiness and remains pending, but resolves when a subsequent sample provides a valid `folder_state`.
4. **Concurrent Upload/Download Activity Preservation**:
   Add a test verifying that when a sample has both `uploading: true` and `downloading: true`, it still confirms `activityObserved` and sets the status to `uploading` in post-game watch.

We will run the test suite to verify the test failures (Red), implement the changes, verify success (Green), and rerun the Codex review loop.
