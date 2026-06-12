# Review 1 — syncthing_state_machine_plugin_runtime

Reviewed branch: `refactor/syncthing-state-machine-runtime` at commit d4ce436.
Overall: very good. All gates pass (149 vitest, 516 pytest, tsc, ruff, ty, rollup build), contract
test files are byte-identical to dev, budgets updated correctly, no stale singleton references.

## Finding 1 (MUST FIX — behavioral divergence): machine skips post-initialization samples with `folder_state === "unknown"`
- **Resolution:** Added `!Number.isFinite(timestamp)` check specifically for the post-initialization validation loop rather than reusing `!isValidSample`. Added unit test `processes valid sample with unknown folder state after initialization`.

## Finding 2 (MUST FIX — behavioral divergence / context leak): confirmation-timeout path never sets `handoffActivated`
- **Resolution:** Dispatched `handoff_finished` event before returning the `unavailable` status in the timeout path in `syncthingMonitor.ts`. Added test `handoffCleanup` verifying that `contexts.size` drops to 0 on timeout.

## Finding 3 (MUST FIX — cleanup): leftover deliberation comments and redundant condition in the machine
- **Resolution:** Removed the comments and redundant condition `newStatus !== "idle"` from the clear pending timer block, moving it into the block above.

## Finding 4 (MUST FIX — fidelity): pending-timeout callback logs and clears the poll timer even when the guard rejects
- **Resolution:** Modifed `schedulePendingActivityTimeout` to evaluate `effects.stopWatch` returned by the `pending_activity_timeout` dispatch event before logging or attempting to cancel polling/watches.

## Finding 5 (MUST FIX — cleanup): reviewer-dialogue comments in production files
- **Resolution:** Removed `// No global settings imports` comments in `index.tsx` and `LudusaviContent.tsx`. Restored `import type { PluginRuntime }` to the standard imports block in `LudusaviContent.tsx`.

## Finding 6 (OPTIONAL — nice to have): suppression test no longer needs `vi.resetModules`
- **Resolution:** Refactored `freshSurface()` in `autoSyncStatusSurface.suppression.test.ts` to statically import `createAutoSyncStatusSurface` and inject an inline mock instead of using `vi.resetModules()` and dynamic imports.

## Process notes
- Commit 49856ee bundles the monitor shell delegation with the PluginRuntime introduction; the plan specified separate atomic commits. Do NOT rewrite history — noted for the record.
- The plan's commits 5/6 landed in swapped order (surfaces before settings). Acceptable.
- `settingsMutationController.tsx` was replaced by a new `settingsMutationRuntime.ts` rather than converted in place. Acceptable — no stale imports remain.
