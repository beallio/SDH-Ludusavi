# Fix: "Last Operation" Timestamp Shows UTC Instead of Local Time

## Context

"Last Operation" now correctly says "Restore complete" (prior round). But the
**timestamp is displayed in UTC, not the user's local timezone**. Screenshot: the
Steam status bar reads **1:34 PM** while Last Operation shows
**"Restore complete (06/13/2026 8:32 PM)"** — a ~7-hour offset = the user's UTC-7
(PDT) zone shown as raw UTC.

### Root cause (confirmed by code read)

History timestamps are stored as UTC ISO strings — `record_history` uses
`datetime.now(timezone.utc).isoformat(timespec="microseconds")`
(`py_modules/sdh_ludusavi/history.py:72`), e.g. `2026-06-13T20:32:00.123456+00:00`.

The Last Operation row renders that string by **manual string-splitting with no
timezone conversion** (`src/components/qam/GameSettingsSection.tsx:128-146`):
```tsx
const parts = selectedHistory.timestamp.split(/[T ]/);
const timePart = parts[1]?.split(".")[0];          // "20:32:00"  <- raw UTC
... ({formatDateMDY(selectedHistory.timestamp)} {formatTime12h(timePart)})
```
`formatDateMDY` (`src/formatting/dateTime.ts:12`) and `formatTime12h`
(`dateTime.ts:1`) just reformat the raw UTC substrings — so 20:32 UTC is shown as
"8:32 PM" instead of the local 1:32 PM.

**Every other timestamp in the app is already correct** because it uses
`new Date(value).toLocaleString(...)`, which converts UTC→local:
- `dateTime.ts` `formatConflictTime`/`formatTimestamp` (used by the Backup Browser and
  conflict modal).
- `src/components/PluginUpdateSection.tsx:161` ("Last checked").

The Last Operation row is the **only** buggy site. `formatTime12h`/`formatDateMDY`
have **no other callers** (verified) — they exist only for this row.

### The fix (frontend-only)

Add a `formatHistoryTimestamp` helper to `dateTime.ts` that parses the UTC ISO string
with `new Date(...)` and formats it in **local** time (preserving the current
`MM/DD/YYYY h:mm AM/PM` look), and use it in the Last Operation row. Delete the now-dead
`formatTime12h`/`formatDateMDY`.

This is frontend-only and unit-testable → strict TDD applies. Runs through the same
**plan → implement → review** loop. **On-device / user testing is deferred until the
dev release is pushed to GitHub.**

---

## Canonical tokens (use these EXACT strings everywhere)

| Thing | Value |
|---|---|
| `plan_name` | `last_operation_timezone` |
| Working branch | `fix/last-operation-timezone` (branched from **`dev`**, NOT `main`) |
| This plan doc | `docs/plans/last_operation_timezone.md` |
| **Completion marker** (implementer → reviewer) | `/tmp/sdh_ludusavi/last_operation_timezone_finished` |
| **Review notes** (reviewer → implementer) | `docs/review/last_operation_timezone_review_<n>.md` (`<n>` = 1, 2, 3…) |
| Approval signal | a review note whose body contains the literal token `PASS` |
| Dev-release base version | `0.3.0` → `./scripts/request_dev_release.sh 0.3.0` |

> **Branch from `dev`, not `main`** (`main` lacks this code). Override the implementer
> skill's "branch from main" default.

## How to run this

This plan doc is delivered untracked in the working tree by the reviewer. Hand it to a
**fresh session** and tell it to **use the `implementer` skill**. That session is "the
implementer"; the reviewer does the code review. They communicate only through the
marker file and the review-note files above.

---

# PART A — Technical work (for the implementer)

**FRONTEND change, but the formatter is extractable → strict TDD (CLAUDE.md §9):
write the failing test first.**

Files in scope:
- `src/formatting/dateTime.ts` (add `formatHistoryTimestamp`; remove dead
  `formatTime12h` / `formatDateMDY`)
- `src/formatting/dateTime.test.ts` (NEW — vitest unit test, colocated like
  `src/formatting/bytes.test.ts`)
- `src/components/qam/GameSettingsSection.tsx` (use the new formatter; update import;
  simplify the Last Operation timestamp block)

Out of scope: backend (the UTC storage is correct — display is the bug), other
timestamp sites (already correct), version bumps.

## A1. RED — add `src/formatting/dateTime.test.ts` (run `pnpm run test:unit`, confirm FAIL)

```ts
import { describe, it, expect } from "vitest";
import { formatHistoryTimestamp } from "./dateTime";

describe("formatHistoryTimestamp", () => {
  // 2026-06-13T20:32:00Z -> 4:32 PM EDT (UTC-4)
  it("converts a UTC ISO timestamp to the given local timezone", () => {
    expect(
      formatHistoryTimestamp("2026-06-13T20:32:00.000000+00:00", {
        timeZone: "America/New_York",
      })
    ).toBe("06/13/2026 4:32 PM");
  });

  // Regression for the report: user (UTC-7 PDT) saw raw UTC 8:32 PM; correct = 1:32 PM
  it("converts to a US west-coast zone (UTC-7)", () => {
    expect(
      formatHistoryTimestamp("2026-06-13T20:32:00.000000+00:00", {
        timeZone: "America/Los_Angeles",
      })
    ).toBe("06/13/2026 1:32 PM");
  });

  it("returns the raw value when unparseable", () => {
    expect(formatHistoryTimestamp("not-a-date")).toBe("not-a-date");
  });

  it("returns empty string for null/undefined", () => {
    expect(formatHistoryTimestamp(null)).toBe("");
  });
});
```

The explicit `timeZone` option makes the test deterministic (no dependence on the test
runner's TZ; requires full-ICU Node, which is standard). This FAILS now because
`formatHistoryTimestamp` does not exist.

## A2. GREEN — add `formatHistoryTimestamp` to `src/formatting/dateTime.ts`

```ts
export function formatHistoryTimestamp(
  value?: string | null,
  opts?: { timeZone?: string }
): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const timeZone = opts?.timeZone;
  const datePart = date.toLocaleDateString("en-US", {
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    timeZone,
  });
  const timePart = date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone,
  });
  return `${datePart} ${timePart}`;
}
```

Notes:
- Production calls pass no `opts` → `timeZone` is `undefined` → renders in the device's
  **local** zone (the fix). The `timeZone` param exists only so the test is
  deterministic.
- `"en-US"` is intentional to preserve the existing `MM/DD/YYYY` + `h:mm AM/PM` look;
  only the timezone behavior changes.
- History timestamps always carry a `+00:00` offset (see Context), so `new Date()`
  parses them as UTC and converts correctly.

Then **delete** `formatTime12h` and `formatDateMDY` from `dateTime.ts` (no remaining
callers after A3).

## A3. Use it in `src/components/qam/GameSettingsSection.tsx`

- Change the import on line ~12 from
  `import { formatDateMDY, formatTime12h } from "../../formatting/dateTime";`
  to `import { formatHistoryTimestamp } from "../../formatting/dateTime";`.
- Replace the IIFE block at lines ~128-146 with:

```tsx
{selectedHistory.timestamp && (
  <div
    style={{
      fontSize: "12px",
      opacity: 0.65,
      marginTop: "2px",
      fontVariantNumeric: "tabular-nums",
    }}
  >
    ({formatHistoryTimestamp(selectedHistory.timestamp)})
  </div>
)}
```

(Keeps the same styling; drops the manual `parts`/`timePart` splitting.)

## A4. Gates (frontend round — run before EACH commit)

```
pnpm run typecheck      # tsc --noEmit
pnpm run test:unit      # vitest run (includes the new dateTime.test.ts)
```
The pre-commit hook also runs the backend suite + `pnpm run verify` + `check_tdd.sh`.
If a commit/merge fails with "requirements are unsatisfiable" (vendored dep newer than
the machine's global 7-day `uv` cutoff), prefix git with `UV_FROZEN=1`. Do not edit
hook scripts. **No on-device testing during the loop** (see §B6).

---

# PART B — Coordination protocol (for the implementer)

## B1. Setup
1. `git status` — this plan doc (`docs/plans/last_operation_timezone.md`) is delivered
   untracked by the reviewer; expected. Run the implementer skill's discovery + emit
   `AGENT_PROTOCOL_HANDSHAKE`.
2. `git checkout dev && git pull`, then
   `git checkout -b fix/last-operation-timezone dev`.
3. Commit the plan doc: `docs(plans): add last operation timezone fix plan`.

## B2. Implement (atomic conventional commits, TDD order)
- `test(datetime): add failing local-timezone history timestamp test` (A1, RED)
- `fix(qam): show Last Operation time in local timezone` (A2 + A3, GREEN)

Run the A4 gates before each commit. **Commit ALL work before signaling** (ensure
`git status` is clean except the marker before B3).

## B3. Signal completion (how the implementer tells the reviewer it's done)
After the round is committed and gates pass:
```
mkdir -p /tmp/sdh_ludusavi
touch /tmp/sdh_ludusavi/last_operation_timezone_finished
```
Empty file; existence + fresh mtime is the signal. **Re-`touch` it at the end of EVERY
round** so the reviewer's mtime-based watcher re-fires.

## B4. Wait for review notes (how the implementer knows the review is done)
Reviewer writes findings to `docs/review/last_operation_timezone_review_<n>.md`. **Own
the wait loop yourself** with the `Monitor` tool (never delegate to a background
subagent). After touching the marker for round `N`, poll ~60s for the next-numbered
note:
```
test -f docs/review/last_operation_timezone_review_<N>.md
```
(`<N>` = 1, then 2, …). When it appears, read it.

## B5. Process each review round, then loop
1. Address EVERY item in the note as atomic commits; run A4 gates each time.
2. Commit the review-note file if not already
   (`docs(review): record last operation timezone review round <n>`).
3. Re-`touch /tmp/sdh_ludusavi/last_operation_timezone_finished`.
4. Return to B4 and wait for the next-numbered note.

Repeat until a review note's body contains the literal token **`PASS`** → go to B6.

## B6. Endgame (only after a review note contains `PASS`)
> **On-device / user testing is deferred to AFTER this step.** PASS is granted on code
> review + green gates alone; do NOT wait for Steam Deck confirmation.

In order:
1. Ensure the approving review note (and all prior) are committed on the branch.
2. Record session log at
   `docs/agent_conversations/<YYYY-MM-DD>_last_operation_timezone.json`; commit it.
3. Merge into `dev`:
   ```
   git checkout dev
   git pull --ff-only
   git merge --no-ff fix/last-operation-timezone
   ```
   (`UV_FROZEN=1 git merge …` if hook re-resolution fails.)
4. Clean up:
   ```
   git branch -d fix/last-operation-timezone
   rm -f /tmp/sdh_ludusavi/last_operation_timezone_finished
   ```
5. Push: `git push origin dev`.
6. Dev release (workflow dispatch — NOT a stable tag/release):
   `./scripts/request_dev_release.sh 0.3.0` (needs `gh` auth; surface failures).
7. Report the merge SHA + dev-release dispatch. On the `v0.3.0-dev.*` build, do an
   operation and confirm Last Operation time matches the Deck clock.

---

## Reviewer side (for reference — implementer does not do these)
- Watch `/tmp/sdh_ludusavi/last_operation_timezone_finished` (`Monitor`, ~60s, mtime
  cutoff). On fire, code-review the branch diff + run frontend gates, then write
  `docs/review/last_operation_timezone_review_<n>.md`. When satisfied (code + gates
  only — no Deck check), write a note containing `PASS`.

## Definition of Done
- [ ] RED first: `dateTime.test.ts` asserts a UTC ISO timestamp renders in a given
      local zone (e.g. UTC-7 → 1:32 PM, not 8:32 PM).
- [ ] `formatHistoryTimestamp` added; Last Operation row uses it; manual UTC
      string-splitting and the dead `formatTime12h`/`formatDateMDY` removed.
- [ ] `pnpm run typecheck` + `pnpm run test:unit` pass; backend gates pass via hook.
- [ ] Session log recorded; review notes committed.
- [ ] Branch merged to `dev`, branch deleted, marker removed; `dev` pushed; dev release
      dispatched. On-device testing deferred to the published build.
