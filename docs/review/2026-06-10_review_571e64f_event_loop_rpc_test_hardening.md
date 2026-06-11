# Review: test-hardening fixes (commit `571e64f`) vs. review findings F1–F4

**Date:** 2026-06-10
**Reviewed commit:** `571e64f` (second commit on `fix/event-loop-blocking-rpcs`, on top of `ba24b94`)
**Reviewed against:** `docs/review/2026-06-10_review_ba24b94_event_loop_blocking_rpcs.md` (findings F1–F4 and its §4 definition of done)
**Verdict:** ✅ **All four findings are correctly implemented — the code and tests need no further changes.** There is **one finding**, and it is purely git-history hygiene: the commit message of `571e64f` describes a completely different change. Fix is a one-command amend (§3).

---

## 1. What was verified (all pass — no action needed)

Each item below was re-verified by running the code on 2026-06-10, not by reading the session log.

### F1 (required) — `test_log_rpc_before_service_construction` rewrite ✅

`tests/test_main_rpc.py:242-257` now matches the prescribed replacement exactly: real `module.Plugin()` (no `FakePlugin`/`MockService`), `_service` monkeypatched to raise `AssertionError("log must never construct the service")`, and both required assertions present (`plugin._backend is None` and the exact fallback string `"[frontend:info] frontend: test message"` in `logger.infos`).

**Regression spot-check performed (the review doc's F1 verification step):** I temporarily reverted `Plugin.log`'s body in `main.py` to the old buggy `self._service().log(level, message, operation, game_name)`, ran the single test, and it **failed with the expected `AssertionError`** in 0.38 s. `main.py` was then restored via `git checkout -- main.py`; `git status` confirmed a clean tree afterward. The test now detects the exact regression it guards, which the previous version could not.

### F2 (required) — bounded `event.wait` in the loop-responsiveness test ✅

`tests/test_main.py:709-715`: `event.wait(timeout=5.0)` with the prescribed explanatory comment. Every other line of the test is unchanged. The test passes in well under 1 s (it ran inside the 12.83 s full suite with no slow-test warning), confirming the green path still releases via `event.set()` immediately.

### F3 (optional) — strengthened `test_main_offloads_service_initialization` ✅

`tests/test_main.py:757-758`: both prescribed assertions appended (`calls.index("startup_init") < calls.index("reconcile_pending_update_install")` and `"reconcile_call" in calls`); nothing else in the test changed.

### F4 (optional) — integration variant through the real `_call` ✅

`tests/test_main.py:783-799`: new test `test_main_logs_initialization_failure_via_real_call` added verbatim below the existing fake-`_call` test, which was left unchanged as instructed. It drives the real chain: raising `_service` → real `_call` converts to the failed dict on the worker thread → `_main` logs via `decky.logger.error`.

### Definition-of-done items from the prior review's §4 ✅

| Item | Status |
|---|---|
| Full gate via wrapper: `ruff check`, `ruff format` (no diff), `ty check` | ✅ all pass |
| `./run.sh uv run pytest` | ✅ **486 passed** — exactly the predicted count (485 + 1 new F4 test) |
| `pnpm run verify` | ✅ exit 0 |
| Commit contains only `tests/test_main_rpc.py`, `tests/test_main.py`, the session log, and the review file | ✅ exactly those 4 files |
| No changes to `main.py`, `py_modules/`, or `src/` | ✅ verified via `git show 571e64f --stat` |
| Session log at `docs/agent_conversations/2026-06-10_event_loop_rpc_test_hardening.json` with required fields and design decisions (a) F1 rationale, (b) 5 s bound rationale | ✅ present and accurate |
| Conventional Commit message describing the test hardening | ❌ **see Finding G1** |

---

## 2. Finding

### G1 — Commit message of `571e64f` describes the wrong change

**Severity:** Low (history hygiene only; the tree content is fully correct)
**Where:** commit `571e64f` on branch `fix/event-loop-blocking-rpcs`

**Current message (verbatim):**

```
docs(plans): add implementation plan for fixing `compare_recency` direction safety
```

**Why this is wrong, explicitly:**

1. The commit adds **no file under `docs/plans/`** and has nothing to do with `compare_recency` (that was finding B1, fixed in earlier commits `7b5aa08`/`ab7214d`/`1b77c83` already on `main`'s history side). The message appears to have been copied from an unrelated change.
2. What the commit *actually* contains: the F1–F4 test-hardening changes (`tests/test_main.py`, `tests/test_main_rpc.py`), the session log `docs/agent_conversations/2026-06-10_event_loop_rpc_test_hardening.json`, and the review document `docs/review/2026-06-10_review_ba24b94_event_loop_blocking_rpcs.md`.
3. The repo mandates Conventional Commits (CLAUDE.md §10). The message is *format*-valid but factually false, which defeats the purpose: anyone running `git log` to find where the test hardening landed will be misled, and anyone looking for a `compare_recency` plan will find tests instead.

**Required fix (safe — verified the branch is NOT pushed: it has no upstream and `git ls-remote --heads origin fix/event-loop-blocking-rpcs` returns nothing, so amending rewrites nothing shared):**

```bash
# Must be run with 571e64f as HEAD of fix/event-loop-blocking-rpcs (it is, as of this review).
# --amend rewrites only the message; the tree/content of the commit is untouched.
git commit --amend -m "test(main): strengthen log-fallback and loop-responsiveness regression tests

Implements review findings F1-F4 from
docs/review/2026-06-10_review_ba24b94_event_loop_blocking_rpcs.md:
rewrite the log pre-construction test so it detects the regression it
guards, bound event.wait to 5s so a regression fails instead of hanging
pytest, assert startup_init ordering in the _main offload test, and add
an integration variant driving the real _call failure path."
```

**Constraints for the agent doing this:**
- Do **not** use `git rebase -i` (interactive flags are unsupported in this environment and unnecessary — the commit is HEAD).
- Do not stage anything before amending; `git status --short` must be empty first. If it is not empty, stop and report (CLAUDE.md §18).
- After amending, verify with `git log --oneline -2` (expect the new message on top, `ba24b94` below) and `git diff main..HEAD --stat` (must be byte-identical to before the amend — amending the message must not change any file content).
- The pre-commit hook will re-run on amend; all gates already pass on this tree, so it should be clean. If a hook fails, capture the output and report — do not bypass with `--no-verify`.
- This is a metadata-only change: no session log update is required, but if you write one anyway, note that only the commit message changed.

---

## 3. Explicit non-findings (checked and fine — do not "fix" these)

- **Bundling the review doc + fixes + session log in one commit:** the atomic-commit policy (CLAUDE.md §10) prefers one coherent change per commit; these four files are all artifacts of the same review-fix cycle, so the bundling is acceptable. Only the *message* is wrong, not the grouping.
- **`tests_added` in the session log lists only `test_main_logs_initialization_failure_via_real_call`:** correct — F1 was a rewrite and F2/F3 were edits to existing tests, not additions.
- **TDD:** these are test-only changes; strict red-green does not apply (CLAUDE.md §9). No violation.
- **Coverage total unchanged at 84%:** expected — only tests changed.
