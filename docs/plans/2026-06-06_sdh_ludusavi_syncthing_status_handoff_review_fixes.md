# Plan: Address Codex Review Iteration 3 Findings

## Problem Definition
Codex Review Iteration 3 raised two P2 findings:
1. **Exclude downloads from post-game upload confirmation**: When inbound (download) traffic happens after a game exit, the monitor incorrectly flags it as upload activity, bypasses the timeout, and starts the upload cycle.
2. **Notify failure only for failed backup results**: In `handleAppExit`, when the exit backup check or operation returns a status of `skipped` (rather than `failed`), `notifyFailure` is incorrectly called because of an over-broad check.

## Architecture Overview
- In `syncthingMonitor.ts`, modify `processSample`'s activity check: for `post_game` phase, download events (where `sample.downloading === true`) must not count as post-game activity, meaning they should not toggle `activityObserved`.
- In `gameLifecycleController.tsx`, refine the conditional block in `handleAppExit` so that `notifyFailure` is only invoked when `result.status === "failed"`.

## Core Data Structures
No new data structures are required.

## Public Interfaces
No public interface signatures change.

## Dependency Requirements
No new dependencies are required.

## Testing Strategy
1. **Unit Test for Download Exclusion**:
   In `src/controllers/syncthingMonitor.test.ts`, add a test verifying that when a post-game watch processes a sample with `downloading: true` but `uploading: false`, it does not set `activityObserved` and does not confirm activity.
2. **Unit Test for Exit Backup Skip Notification**:
   In `src/controllers/gameLifecycleController.test.ts`, add a test verifying that when `backupGameOnExitCall` returns a skipped status (e.g., status is `"skipped"`), the controller does not invoke `notifyFailure` (while it does invoke `completeAutoSyncStatus` with the skipped result).

We will run these tests to verify failure (Red), apply the changes, verify success (Green), and rerun the Codex review loop.
