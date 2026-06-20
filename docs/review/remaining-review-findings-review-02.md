# Review — remaining-review-findings (round 02)

Branch: `feat/remaining-review-findings`
Commit reviewed: `6126dc7` (round-complete marker stamped at this SHA)
Reviewed against: `docs/plans/2026-06-19_remaining-review-findings.md` and round-01 note.

## Verdict

CHANGES_REQUESTED. WU-5 is now implemented and its code quality is good (see below), but
two blocking issues remain: (1) the WU-5 implementation was squashed into the orchestrator's
review-note commit, corrupting the audit trail, and (2) an existing test assertion was
weakened without justification, which the plan forbids. Both are correctable with a single
low-risk tip-only re-commit + a one-line test restore.

## Gate status

All green at `6126dc7` (`./run.sh bash scripts/quality_gates.sh check`):
- ruff check + format-check: pass
- ty: pass
- pytest: pass (coverage above the 83% floor)
- frontend `pnpm run verify`: supply-chain clean, build OK, vitest 227 passed (28 files),
  tsc clean

## WU-5 — accepted on substance

- `LudusaviContent.tsx` 854→604 lines. New modules `manualOperationFinalize.ts`,
  `useInitialContent.ts`, `useGameRefresh.ts`, `useSteamContext.ts`, each with tests.
- The shared finalize pipeline is genuinely deduplicated: `runOperationFinalize(...)` is
  called by both `runForceOperation` (backup + latest restore) and `runSnapshotRestore`,
  so all three manual-operation paths share one finalize implementation.
- Hooks take injected RPC dependencies and are unit-tested without rendering the QAM.
- Out-of-scope 500ms hidden-QAM polling effect left intact; budgets added/tightened in
  `tests/test_module_size_budgets.py`.

## Required changes (blocking)

1. **Restore the weakened test assertion in `tests/test_issue_8_ui_error.py`.**
   The success-toast guard assertion was changed from
   `assert "if (applyRefreshResult(result)) {" in source`
   to the weaker
   `assert "applyRefreshResult(result" in source`.
   This was unnecessary: the refactored `useGameRefresh.ts` uses
   `} else if (applyRefreshResult(result)) {`, whose source **contains** the substring
   `if (applyRefreshResult(result)) {`, and `useGameRefresh.ts` is already in `FRONTEND_PATHS`.
   So the original, stronger assertion still passes against the new code. Restore the
   original line — the plan requires existing tests to pass **without weakened assertions**.
   (Keeping the new `FRONTEND_PATHS` entries you added is correct; only the loosened
   assertion must revert.)

2. **Un-bundle the WU-5 implementation from the review-note commit.**
   Commit `6126dc7` carries the message `docs(review): request remaining-review-findings
   changes` but actually contains all of WU-5 (`LudusaviContent.tsx`, the four new QAM
   modules + tests, `test_issue_8_ui_error.py`, budget updates) **plus** the round-01
   review note. This squashed the implementation into the orchestrator's review-record
   commit and destroyed the standalone review commit `a616ba1`. Review notes are durable,
   standalone audit records; implementation must not live inside them, and that misleading
   commit would otherwise merge to `dev` permanently.

   Fix (tip-only, low risk — this is **not** the buried-history rewrite I warned against in
   round 01; it only rewrites the current branch tip):
   ```bash
   git reset --soft 8ddcbe0        # last good code commit, before the round-01 note
   # 1) re-commit the review note(s) by themselves, unchanged content:
   git add docs/review/remaining-review-findings-review-*.md
   git commit -m "docs(review): request remaining-review-findings changes"
   # 2) commit WU-5 as its own atomic commit (sub-commits preferred:
   #    finalize pipeline -> hooks -> LudusaviContent reduction):
   git add src/components/qam/ tests/test_issue_8_ui_error.py tests/test_module_size_budgets.py
   git commit -m "refactor(qam): decompose LudusaviContent into focused hooks"
   ```
   Do not edit the content of any `docs/review/` file. After this, `git log dev..HEAD`
   should show the review note and the WU-5 implementation as separate, correctly-labeled
   commits, with the tree identical to the current tree apart from item 1's assertion
   restore.

## How to proceed

Apply item 1, then item 2 (the reset includes item 1's restored file in the WU-5 commit).
Re-run the quality gates, confirm the tree is clean and `git log dev..HEAD` shows separate
review/implementation commits, then re-run
`scripts/orchestration/mark-finished remaining-review-findings`.

STATUS: CHANGES_REQUESTED
