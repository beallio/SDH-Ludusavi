# Plan: Fix Update-Check Force-Recheck Feedback Loop (fix-update-check-feedback-loop)

## Context

On-device logs (`2026-06-19 22.26.25.log`) show a runaway update-check loop: **2030
`force=True` update checks in ~47 seconds** (22:57:25 → 22:58:12), each fetching GitHub
releases and re-selecting the same candidate `0.3.3-dev.g834f426`, status `available`. The
loop only triggers once an update is genuinely *available* (running build
`0.3.3-dev.g9ab9fb5` vs the newer published `0.3.3-dev.g834f426`); when the result is
`current` the device stays quiet. Effect on the user: hammering the GitHub API (real risk of
403/429 rate-limiting), wasted battery/CPU, and a 1.6 MB log from one session.

**Root cause (verified):** `src/controllers/pluginUpdateController.tsx` has an effect
(currently ~lines 312–333) that, on any non-first-mount run, issues a **forced** check:

```tsx
} else {
  void checkForUpdates({ force: true, notify: false, source: "automatic" });
}
}, [updateChannel, currentVersion, state.phase, checkForUpdates]);
```

Its dependency array includes **`state.phase`**. The reducer transitions phase on every
check: `CHECK_START → "checking"`, `CHECK_SUCCESS_AVAILABLE → "available"`,
`CHECK_SUCCESS_CURRENT → "idle"`. So a forced check changes `state.phase`, which re-runs the
effect, which fires another forced check — a feedback loop. With an update available the
phase oscillates `checking ↔ available` indefinitely (2030 iterations observed).

**This is a regression from the WU-4 reducer refactor** (commit `8ddcbe0`,
`remaining-review-findings`). That commit changed this exact dependency array:

```diff
- }, [updateChannel, currentVersion, contextHydrated, checkForUpdates]);
+ }, [updateChannel, currentVersion, state.phase, checkForUpdates]);
```

The original `contextHydrated` was a **monotonic one-shot gate** (flips `false→true` once at
hydration and never changes again), so the effect re-ran only on hydration-complete and on
`updateChannel`/`currentVersion` changes — never on check-result phase changes. Replacing it
with the constantly-changing `state.phase` reintroduced the re-trigger. The review approved
WU-4 because no test covered the available→re-check path and no device had an update
available at review time.

**Intended outcome:** the automatic re-check fires exactly when intended — once after
hydration, and again when `updateChannel` or `currentVersion` changes — and **never** as a
consequence of a check result changing `state.phase`. No change to the public hook API or to
the manual-check / install / handoff behavior.

Relevant files (verified):
- `src/controllers/pluginUpdateController.tsx` — the two **effects** with the anti-pattern:
  - ~312–333: the hydration/channel/version re-check effect (issues `force: true` on rerun) — **the runaway**.
  - ~335–347: the `automaticUpdateChecks` toggle effect (issues `force: false`) — same `state.phase` dependency anti-pattern; lower blast radius (cache-friendly) but must be fixed too.
  - The `install` useCallback (~349–463) legitimately depends on `state.phase`; its force-checks are one-shot on install failure. **Do not change it.**
- `src/controllers/pluginUpdateReducer.ts` — phase machine (`hydrating | idle | checking | available | installing | handoff_pending | installed | failed`); `state.phase === "hydrating"` is the only "not yet hydrated" state and phase never returns to `hydrating` after `HYDRATION_COMPLETE`.
- `src/controllers/pluginUpdateController.test.tsx` — existing controller/reducer tests to extend.

**Slug used throughout this plan:** `fix-update-check-feedback-loop`

---

## Orchestration Contract

**Slug:** `fix-update-check-feedback-loop`

**Plan file:**

```text
docs/plans/2026-06-19_fix-update-check-feedback-loop.md
```

**Implementation branch:**

```text
feat/fix-update-check-feedback-loop
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/fix-update-check-feedback-loop_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/fix-update-check-feedback-loop_finalized
```

**Review notes:**

```text
docs/review/fix-update-check-feedback-loop-review-*.md
```

Each review note ends with exactly one status trailer:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

---

## Required Agent Protocol

1. Use the **implementer** skill.
2. Work from the repository root.
3. Branch from `dev`.
4. Commit this plan as the first commit on the implementation branch.
5. Follow TDD where behavior changes are testable.
6. Run quality gates before marking any round complete.
7. Do not write your own review.
8. Do not create files under `docs/review/`.
9. Do not delete files under `docs/review/`.
10. Review notes are durable audit records and must be committed.
11. Resolving a review note means:
    - implement the requested changes;
    - run quality gates;
    - commit the code/docs changes;
    - commit the review note itself if it is not already committed;
    - recreate the round-complete marker.
12. After finalization, stop polling and exit cleanly.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/fix-update-check-feedback-loop
```

Commit this plan first:

```bash
git add docs/plans/2026-06-19_fix-update-check-feedback-loop.md
git commit -m "docs(plan): add fix-update-check-feedback-loop implementation plan"
```

---

## Implementation Tasks

Strict TDD — this is a behavior fix. Write the failing regression test first, watch it loop
(or exceed a call-count bound), then implement the minimal fix, then keep the full suite
green. No public-API change, no new dependencies.

### Task 1 — Red: reproduce the loop in a controller/reducer test

In `src/controllers/pluginUpdateController.test.tsx` add a test that drives the controller
through hydration and then a check that resolves to **`available`**, with `checkForUpdates`
backed by a mock/spy. Assert the controller does **not** re-issue a forced check as a
*result* of the available status — i.e. the number of `checkForUpdates({ force: true })`
invocations is **bounded** (one per legitimate trigger), not unbounded. With the current
code this test must fail (the spy is called repeatedly / exceeds the bound). Prefer a
deterministic bound assertion (e.g. "≤ 1 forced automatic check for a single channel/version
generation") over relying on a timeout.

Also add a test for the legitimate triggers that must still work:
- after hydration, exactly one initial automatic check fires (respecting
  `skipInitialCheck`/`automaticUpdateChecks`);
- changing `updateChannel` (and/or `currentVersion`) fires exactly one re-check;
- a check resolving to `available` then `current` does **not** spawn extra checks.

### Task 2 — Green: decouple the re-check effects from `state.phase`

Fix the two effects in `pluginUpdateController.tsx` so they no longer re-run on check-result
phase oscillation:

- **Do not depend on `state.phase`.** Depend instead on a **monotonic hydration signal** —
  the same shape the pre-WU-4 code used (`contextHydrated`). Recommended: derive a stable
  boolean `const isHydrated = state.phase !== "hydrating";` and use `isHydrated` in the
  dependency arrays. Because phase never returns to `hydrating` after `HYDRATION_COMPLETE`,
  `isHydrated` flips `false→true` exactly once and then never changes, so the effect runs at
  hydration-complete and on `updateChannel`/`currentVersion` changes only — never on
  `checking`/`available`/`idle` transitions.
- Keep the early-return guard for the not-yet-hydrated case, but read it from `isHydrated`
  (or keep `state.phase === "hydrating"` as a runtime guard inside the effect body — reading
  it is fine; the fix is removing it from the **dependency array**).
- Apply the same change to **both** effects (~312–333 force=true, and ~335–347 force=false).
- Preserve `hasChecked`/first-mount semantics, `skipInitialCheck`, the timeout/cancellation
  refs, and the `usePluginUpdateController(...)` return shape. **Do not** touch the `install`
  callback's `state.phase` dependency (it is correct).
- If any genuine "re-check when a phase milestone is reached" behavior is needed (e.g. after
  an install handoff), express it through a dedicated effect keyed on that *specific*
  terminal phase guarded against re-entry — not by depending on the full `state.phase` in an
  effect that issues a forced check.

### Task 3 — Guard against regression / verify quietness

- Confirm via the Task 1 tests that an `available` result produces a bounded number of
  forced checks.
- Sanity-check the other `checkForUpdates` call sites are unaffected: manual check
  (`force:true, source:"manual"`), automatic first-mount (`force:false`), toggle effect,
  and install-failure recovery checks.

### Out of scope

- Do not redesign the update workflow or the reducer. This is a targeted dependency-array
  correctness fix.
- Do not change network/cooldown (rate-limit) behavior, the manual-check button, or install
  flow.
- No on-device build/version bump or release as part of this work (finalize handles the dev
  release).

---

## Quality Gates

Run before marking any round complete:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

The round is not complete unless:

1. all requested implementation work is done;
2. all relevant tests pass;
3. build/typecheck gates pass;
4. review notes have not been deleted;
5. the working tree is clean;
6. all code/docs changes are committed.

---

## Verification

- New regression test fails on the unpatched controller (demonstrates the unbounded forced
  checks on `available`) and passes after the fix.
- Existing `pluginUpdateController.test.tsx` and reducer tests pass unchanged (no weakened
  assertions).
- Full quality gates green: `./run.sh bash scripts/quality_gates.sh check` (ruff, ty,
  pytest, `pnpm run verify` incl. vitest + tsc).
- Manual reasoning check: in the patched effect, the dependency array contains no value that
  changes as a result of a check (`isHydrated` is monotonic; `updateChannel`/`currentVersion`
  are external inputs).

Deferred (on-device, after the dev push from finalize): install the resulting dev build on
the Steam Deck with an update genuinely available, open the QAM, and confirm the log shows a
**single** `check_start`/`check_success: status=available` per legitimate trigger — no
repeated `force=True` loop. Capture a fresh log to confirm the 2030×/47s pattern is gone.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished fix-update-check-feedback-loop
```

This writes:

```text
/tmp/sdh_ludusavi/fix-update-check-feedback-loop_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer fix-update-check-feedback-loop`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/fix-update-check-feedback-loop-review-*.md
```

When a review note exists or a new review note appears:

1. Read the full review note.
2. If the note ends with:

   ```text
   STATUS: CHANGES_REQUESTED
   ```

   then resume work.

3. Clear the round-complete marker:

   ```bash
   scripts/orchestration/clear-finished fix-update-check-feedback-loop
   ```

4. Address every requested change.
5. Run quality gates:

   ```bash
   scripts/orchestration/run-quality-gates
   scripts/orchestration/check-review-notes-not-deleted
   ```

6. Commit code/docs fixes.
7. Commit the review-note file itself if it is not already committed:

   ```bash
   git add docs/review/fix-update-check-feedback-loop-review-*.md
   git commit -m "docs(review): record fix-update-check-feedback-loop review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished fix-update-check-feedback-loop
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer fix-update-check-feedback-loop` after the next review note is created.

---

## Approval Handling

If the latest review note ends with:

```text
STATUS: APPROVED
```

then:

1. Confirm every previous review item has been addressed.
2. Confirm all review notes are committed:

   ```bash
   scripts/orchestration/check-review-notes-committed fix-update-check-feedback-loop
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize fix-update-check-feedback-loop
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/fix-update-check-feedback-loop_finalized
   ```

6. Stop polling and exit cleanly.

---

## Review Rules

Do not write your own review.

Do not create files under:

```text
docs/review/
```

Do not delete files under:

```text
docs/review/
```

Only the orchestrator writes review notes. Your job is to read them, resolve them, commit them as audit records, and continue the loop.

---

## Finalization Rules

Only finalize after a review note with:

```text
STATUS: APPROVED
```

Finalization is performed with:

```bash
scripts/orchestration/finalize fix-update-check-feedback-loop
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/fix-update-check-feedback-loop_finished
/tmp/sdh_ludusavi/fix-update-check-feedback-loop_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
