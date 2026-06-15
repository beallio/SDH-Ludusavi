# Review — animated-status-icons (round 01)

Branch: `feat/animated-status-icons` (commit `64ebebf`)
Reviewed against: `docs/plans/2026-06-14_animated-status-icons.md`

## Verdict

One required change. Items 2–6 are correct and complete. Item 1 is implemented but
bypasses the lifecycle epoch guard, which is a correctness regression. Fix the item below,
then re-run the gates and re-create the finished marker.

## Gate status (verified during review)

- `pnpm test` → 187 passed (vitest + tsc). ✅
- `pnpm run build` → rollup bundle created. ✅
- Session log present (`docs/agent_conversations/2026-06-15_animated-status-icons.json`). ✅

## Required change

### 1. `has_backup` publish bypasses the epoch guard (item 1)

**File:** `src/controllers/gameLifecycleController.tsx`, line 431 (inside
`if (result.status === "backed_up") {`).

You wrote:
```ts
statusSurface.publish("has_backup", {
  source: "lifecycle_exit",
  gameName: name,
  appID,
  tracked,
});
```

`statusSurface.publish` is the **raw, unguarded** surface. Every other status publish in
this exit handler goes through `publishAutoSyncStatus`, which is the epoch-guarded wrapper
returned by `createEpochGuardedSurface(...)` at line 377 (see the guard at lines 97–112:
it drops the status when `epoch !== getCurrentEpoch()`). Because the `has_backup` call is
unguarded and runs *before* the `if (epoch !== lifecycleEpoch) return;` check (line 443),
a post-game lifecycle that has already been superseded (e.g. the user relaunches or exits
another game during the `backup_game_on_exit` await) will still flash "GAME SAVE UP TO
DATE" on screen for the stale lifecycle. This is exactly the stale-status class the guard
exists to prevent, and the plan specified `publishAutoSyncStatus("has_backup", ...)`.

**Fix:** change `statusSurface.publish` to `publishAutoSyncStatus` (keep the options
object exactly as is):
```ts
publishAutoSyncStatus("has_backup", {
  source: "lifecycle_exit",
  gameName: name,
  appID,
  tracked,
});
```

The existing ordering test in `gameLifecycleController.test.ts` still passes after this
change (the test does not advance the epoch, so the guarded publish fires normally). No
test change is required, but confirm the lifecycle suite stays green.

## Confirmed correct (no action needed)

- Item 2 — Syncthing Downloading now a custom inline SVG with `download-arrow-clip` +
  `.download-arrow-fill` rect; `@keyframes arrow-fill-down` added; `getSerializedIcon`
  reduced to `syncthing_complete`; unused `IoMdCloudDownload` import removed.
- Items 3 & 5 — `syncthing_unavailable`, `syncthing_folder_not_found`, `syncthing_no_peers`
  all return the identical cloud-with-X SVG; amber color preserved.
- Item 4 — `conflict` added to the amber color group; icon unchanged.
- Item 6 — `docs/animated-status-icons-reference.html`: downloading moved into the
  Animated section with "fill ↓", keyframes added, three warnings show the amber
  cloud-with-X, conflict card is `color-amber`, pending-upload "when" text documents the
  backing_up → has_backup → preparing sequence.

STATUS: CHANGES_REQUESTED
