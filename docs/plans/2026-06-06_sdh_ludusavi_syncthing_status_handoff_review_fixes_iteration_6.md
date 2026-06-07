# Plan: Address Codex Review Iteration 6 Findings

## Problem Definition
Codex Review Iteration 6 raised two P2 findings:
1. **Do not map download-only progress to uploading**: In `syncthingMonitor.ts` at `processSample`, for post-game samples, a download-only sample sets `update_in_progress = true`. The current conditional check maps it to `uploading` in post-game because it evaluates `sample.update_in_progress` without excluding downloads, even though the preceding activity check successfully rejects downloads. This causes a false `SYNCTHING UPLOADING` status, or blocks later legitimate uploads.
2. **Remove contexts after pending activity timeout**: In `syncthingMonitor.ts` at `schedulePendingActivityTimeout`, when a post-game watch hits the pending activity timeout, the context is marked as `cancelled = true` but is never passed to `maybeCleanupContext`. This causes the watch context to leak and permanently remain in `contexts` for the lifetime of the plugin.

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

We will run the test suite to verify the test failures (Red), implement the changes, verify success (Green), and rerun the Codex review loop.
