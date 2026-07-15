# Plan: Recognize Steam Launcher Pre-Scope Handoff (recognize-steam-launcher-prescope-handoff)

## Context

### Problem Definition

The installed development build `0.3.7-dev.ga3a8be3` still fails to hold a tracked game at
startup when Ludusavi detects a legitimate save conflict. Fresh plugin logs copied from
`steamdeck` to
`/tmp/sdh_ludusavi/steamdeck/logs/2026-07-14-persistent-conflict-startup` show the current
failure twice:

- At `19:27:35.986`, Steam reported X-Men Origins Wolverine with launch PID `5627`; two
  milliseconds later the launch gate failed with `Launch PID is not in an exact Steam app
  scope`.
- At `19:45:57.346`, Steam reported the same game with PID `4099`; the gate failed at
  `19:45:57.349`, and the user journal recorded creation of
  `app-steam-app3156562597-4099.scope` at `19:45:57.356`, only about seven milliseconds
  later.

The second incident then spent about eight seconds checking the save, correctly returned
`status=conflict` for the expected difference between the local save and backup, and sent
the toast `Launch gate unavailable; conflict resolution skipped while game is loading.`
The game was not frozen during those checks and continued advancing. The conflict-recency
decision and the frontend's fail-closed toast are not the defect.

The backend retry introduced by the previous launch-gate repair recognizes only the bare
user `app.slice` path as a typed, retryable pre-scope state. Live Deck inspection confirms
that Steam's process is in:

```text
/user.slice/user-1000.slice/user@1000.service/app.slice/steam-launcher.service
```

New launch children inherit that exact cgroup before user systemd moves them into the
transient `app-steam-appNNN-NNN.scope`. In `launch_gate.py`, that safe transitional path is
currently classified as a generic `ScopeDiscoveryError`. `LaunchScopeAcquirer` retries only
`ScopeNotReadyError`, so it sends `SIGSTOP`, rejects the inherited service path immediately,
and sends `SIGCONT` during cleanup instead of waiting the bounded handoff window.

Raw Deck logs and journal output are investigation evidence only. Do not copy them into the
repository or commit paths under `/tmp`.

### Intended Outcome

- A validated launch PID temporarily inherited from the exact Deck user
  `steam-launcher.service` cgroup is treated as "scope not ready" and polled for the existing
  bounded acquisition window.
- The bootstrap PID remains `SIGSTOP`-held from before the first cgroup inspection until it
  has moved into a strictly validated Steam app scope, that complete scope is frozen and
  verified, and releasing the bootstrap stop cannot advance it.
- Neither `steam-launcher.service` nor any other parent/non-app cgroup is ever frozen or
  accepted as a successful launch gate.
- Similar-looking service paths, nested paths, other units, malformed paths, wrong-user
  paths, and path traversal remain immediate hard failures.
- A legitimate save conflict opens the existing modal while the full app scope remains
  frozen. The selected restore/keep action or dismissal completes before the existing
  single verified thaw.
- Genuine acquisition failures continue to resume a same-identity bootstrap PID, make no
  save changes, and surface the existing failure toast.

### Architecture Overview

Keep the repair inside the existing strict discovery/acquisition boundary:

1. `LaunchScopeAcquirer.acquire()` captures PID owner/start-time identity and sends
   `SIGSTOP` before asking the scope controller to discover membership. Preserve that
   ordering and its current cleanup rules.
2. `SystemdScopeController.discover()` continues to parse the one unified cgroup entry and
   accepts only a fully validated `app-steam-appNNN-NNN.scope` as a `SteamAppScope`.
3. Refine the internal path classifier so two exact pre-scope states are typed as
   `ScopeNotReadyError`: the already-supported bare `app.slice`, and the field-confirmed
   `app.slice/steam-launcher.service`. The latter must match the full expected user-slice
   prefix and the literal terminal unit; no suffix, child, alternate service, or inferred
   app ID is allowed.
4. The acquirer catches that typed state, revalidates PID identity on every iteration, and
   retries until strict discovery observes the exact Steam app scope or the existing
   monotonic deadline expires.
5. Preserve the verified scope freeze, bootstrap `SIGCONT` handoff, post-handoff freezer
   verification, lease creation, watchdog renewal, and thaw behavior without adding another
   success path.

This is not permission to broaden accepted cgroup grammar, discover a scope by scanning
systemd, derive a unit from a frontend app ID, freeze `steam-launcher.service`, or increase
the timeout to conceal classification errors.

### Core Data Structures

- Keep `SteamAppScope` as the only successful discovery result and durable scope identity.
- Keep `LaunchProcessIdentity` as the PID/owner/start-ticks guard across stop, polling,
  freeze, release, and cleanup.
- Keep `ScopeNotReadyError` as the typed internal signal for a narrowly validated handoff
  state; update its documentation so it covers the two exact allowed pre-scope paths rather
  than describing only bare `app.slice`.
- Prefer one private constant or helper for the literal `steam-launcher.service` handoff
  path so validation remains auditable and is not duplicated across discovery and tests.
- Do not add a public result status, frontend state, settings value, or persisted schema.

### Public Interfaces

Preserve all Decky RPC names, arguments, and response shapes:

```text
pause_game_process(pid) -> {status, pid, lease_id, lease_ttl_seconds}
renew_game_process_pause(pid, lease_id) -> {status, pid, lease_ttl_seconds}
resume_game_process(pid, lease_id?) -> {status, pid, ...}
```

Do not add an app ID, cgroup path, or scope unit to the frontend API. Preserve
`createPauseLease`, `evaluateStartCheck`, the conflict modal, and the failure toast. No
production TypeScript change is expected; frontend tests are a regression fence for the
existing fail-closed behavior.

### Dependency Requirements

Add no Python, JavaScript, system package, privilege helper, or upstream dependency. Use the
current standard-library path handling and the existing cgroup v2/systemd integration. Tests
must use synthetic proc/cgroup roots and injected clocks, waits, signals, and command runners;
they must never signal real processes or invoke real `systemctl`.

### Testing Strategy

Follow strict Red-Green-Refactor. First add focused tests that reproduce the exact
`steam-launcher.service` inheritance observed on the Deck and prove those tests fail against
the current classifier. Implement the smallest path-classification repair, then run the
focused launch-gate suites and the complete orchestration quality gate. Keep the existing
frontend conflict behavior and analyzer rules green. Actual Steam/systemd timing and modal
behavior remain deferred on-device acceptance after an approved implementation build is
installed.

### Scope Boundaries

- Do not change save-recency classification; the local/backup difference is expected.
- Do not hide, rename, or weaken the launch-gate failure toast.
- Do not change BrowserUI status rendering or conflict-modal production code unless a new
  regression test proves the backend result violates an existing frontend contract.
- Do not revisit scope-freeze environment cleanup, lease rotation, watchdog ceilings, or
  multi-scope recovery unless a focused regression fails because this change breaks one of
  those invariants.
- The `Task was destroyed but it is pending!` messages occur during Decky reload and remain
  outside this startup handoff plan.
- Preserve the separately stashed `docs/plans/2026-07-14_thermo-review-quick-fixes.md` work;
  do not apply, edit, stage, or absorb it into this branch.

**Slug used throughout this plan:** `recognize-steam-launcher-prescope-handoff`

---

## Orchestration Contract

**Slug:** `recognize-steam-launcher-prescope-handoff`

**Plan file:**

```text
docs/plans/2026-07-14_recognize-steam-launcher-prescope-handoff.md
```

**Implementation branch:**

```text
feat/recognize-steam-launcher-prescope-handoff
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/recognize-steam-launcher-prescope-handoff_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/recognize-steam-launcher-prescope-handoff_finalized
```

**Review notes:**

```text
docs/review/recognize-steam-launcher-prescope-handoff-review-*.md
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

## Scope discipline

- Implement only the units the plan lists. Do not modify files outside the plan's scope.
- Do not change runtime behavior beyond what the plan specifies. A `refactor` or
  `cleanup` commit must preserve observable behavior.
- Never edit a test's expected value to make a behavior change pass. If a test
  legitimately must change, that change must be required by the plan or a review
  note, and you must record the rationale in the session log.
- If you spot an unrelated improvement, do not make it here — note it in the
  session log for a separate plan.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/recognize-steam-launcher-prescope-handoff
```

Commit this plan first:

```bash
git add docs/plans/2026-07-14_recognize-steam-launcher-prescope-handoff.md
git commit -m "docs(plan): add recognize-steam-launcher-prescope-handoff implementation plan"
```

---

## Implementation Tasks

### 1. Commit the plan and establish RED coverage

Start from `dev`, create the implementation branch defined above, and commit this plan as the
first branch commit. Confirm `git status --short` contains no unrelated work before tests.

In `tests/test_launch_gate_scope.py`, add behavior-first regressions before changing
production code:

- Build the exact synthetic unified cgroup entry
  `/user.slice/user-1000.slice/user@1000.service/app.slice/steam-launcher.service` and assert
  that discovery raises `ScopeNotReadyError`, never returns a `SteamAppScope`, and never
  invokes a systemd transition.
- Begin acquisition in that exact path, change the synthetic proc cgroup entry to the exact
  `app-steam-app3156562597-<pid>.scope` from the injected wait callback, and assert the event
  order is `SIGSTOP` -> bounded wait -> exact-scope freeze -> `SIGCONT`. At `SIGCONT`, assert
  both `cgroup.freeze=1` and `cgroup.events` containing `frozen 1`; assert the returned scope
  is the app scope, not the launcher service.
- Prove the exact launcher-service state times out through the bounded retry path and resumes
  the unchanged bootstrap PID once, matching existing failure cleanup.
- Parameterize near misses that must stay non-retryable: another `.service`,
  `steam-launcher.service` under a wrong prefix/UID, a child below that service, a suffix or
  alternate spelling, and malformed/traversal-like membership. Assert no wait occurs and the
  launcher service is never frozen.
- Retain the existing bare-`app.slice` delayed handoff test. Do not replace it with the new
  field case; both exact pre-scope states need coverage.

Run a focused command such as:

```bash
./run.sh uv run pytest tests/test_launch_gate_scope.py -k 'launcher or scope_not_ready or delayed_scope'
```

Record the expected RED failures in the session log before production edits.

### 2. Classify the exact Steam launcher handoff without weakening discovery

In `py_modules/sdh_ludusavi/launch_gate.py`:

- Update the private cgroup-path classifier (or add one small private helper) so the literal
  `steam-launcher.service` path under the already-required
  `user.slice/user-UID.slice/user@UID.service/app.slice` prefix raises
  `ScopeNotReadyError`.
- Require exact tuple length and normalized full-path equality for this transitional state.
  Keep the current unit regex and strict `SteamAppScope` construction unchanged for successful
  discovery.
- Update the `ScopeNotReadyError` description to reflect an exact, safe pre-app-scope handoff
  instead of only bare `app.slice`.
- Keep all other invalid membership as `ScopeDiscoveryError`; do not make generic services or
  arbitrary descendants retryable.

In `py_modules/sdh_ludusavi/launch_gate_acquire.py`, change code only if the new RED tests
expose a missing invariant. The current typed retry loop, PID identity checks, bounded
deadline, stop/release ordering, freeze verification, and cleanup should remain the owner of
the handoff. Do not add a fallback search, sleep before `SIGSTOP`, or successful PID-only
pause.

Run the complete focused backend regression set:

```bash
./run.sh uv run pytest tests/test_launch_gate.py tests/test_launch_gate_scope.py tests/test_watchdog.py tests/test_service.py
```

### 3. Preserve diagnostics, frontend behavior, and documentation

- Run `tests/test_analyze_plugin_logs.py` and retain its existing
  `launch_gate.scope_acquisition_failed` and `launch_gate.conflict_skipped` detection. Only
  change analyzer code/fixtures if production log grammar necessarily changes; do not weaken
  strict-mode findings to make field logs pass.
- Run `src/controllers/gameLifecycleDecision.test.ts` through the frontend suite and preserve
  the rule that a conflict without a verified pause is skipped with the existing toast.
- Update the README only if the user-visible launch-gate contract wording becomes inaccurate;
  no README change is expected for this corrective implementation.
- Add the required JSON session summary under `docs/agent_conversations/` with the field
  evidence summarized without raw save paths or committed device logs. Include the RED test,
  files changed, design decision to allow only the literal launcher-service transition, and
  validation results.
- Commit coherent changes with Conventional Commit messages. Keep unrelated plans, stashes,
  logs, caches, generated archives, and release metadata out of the commits.

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

### Automated verification

Before marking the round complete:

1. Confirm the exact launcher-service fixture becomes retryable while every near miss remains
   an immediate failure.
2. Confirm a successful synthetic handoff never freezes `steam-launcher.service`, returns only
   a verified `SteamAppScope`, and preserves the required signal/freeze ordering.
3. Confirm timeout and hard-failure cleanup release only the unchanged bootstrap PID and
   create no watchdog lease.
4. Run the focused backend commands from the tasks.
5. Run `./run.sh uv run pytest tests/test_analyze_plugin_logs.py`.
6. Run the repository quality gates from the Quality Gates section, which cover Ruff, Ruff
   formatting, `ty`, the complete Python suite, frontend tests/typecheck/build/supply-chain
   checks, TDD enforcement, and repository hygiene.
7. Confirm the working tree is clean and all plan, test, code, and session-log changes are
   committed before writing the round-complete marker.

### Deferred on-device acceptance

Automated tests cannot reproduce Steam's transient systemd migration. After orchestrator
approval and installation of an implementation build, manually launch the same tracked game
with an intentional local/backup save difference and confirm:

1. Plugin logs identify the installed implementation version and show `Froze Steam app scope
   app-steam-app3156562597-<pid>.scope` before the start check completes.
2. The conflict modal appears, no launch-gate-unavailable toast appears, and the game does not
   advance before a choice.
3. Restore backup, keep local, and dismiss each preserve their existing semantics; each path
   produces exactly one verified thaw after the choice/cleanup.
4. `scripts/analyze_plugin_logs.py --strict` reports no launch-gate finding for the successful
   incident.
5. A controlled acquisition failure, if separately exercised, still resumes the bootstrap
   PID and retains the existing error toast rather than leaving the game stopped.

This on-device check is explicitly deferred; plan authoring does not install a build, modify
the Deck, publish a release, or claim SteamOS acceptance.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished recognize-steam-launcher-prescope-handoff
```

This writes:

```text
/tmp/sdh_ludusavi/recognize-steam-launcher-prescope-handoff_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer recognize-steam-launcher-prescope-handoff`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/recognize-steam-launcher-prescope-handoff-review-*.md
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
   scripts/orchestration/clear-finished recognize-steam-launcher-prescope-handoff
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
   git add docs/review/recognize-steam-launcher-prescope-handoff-review-*.md
   git commit -m "docs(review): record recognize-steam-launcher-prescope-handoff review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished recognize-steam-launcher-prescope-handoff
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer recognize-steam-launcher-prescope-handoff` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed recognize-steam-launcher-prescope-handoff
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize recognize-steam-launcher-prescope-handoff
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/recognize-steam-launcher-prescope-handoff_finalized
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
scripts/orchestration/finalize recognize-steam-launcher-prescope-handoff
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/recognize-steam-launcher-prescope-handoff_finished
/tmp/sdh_ludusavi/recognize-steam-launcher-prescope-handoff_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
