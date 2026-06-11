# Animate the "BACKING UP LOCAL SAVE" status bar icon (arrow fill)

Date: 2026-06-11
Status: Approved, ready for implementation
Branch: `dev` (commit directly to `dev`, matching prior status-animation work `cfb722d`)

## Execution instructions for the implementing agent

- **Use the `implementer` skill to execute this plan.** Invoke it before making any
  changes and follow its guardrails.
- **The first commit of this work MUST be committing this plan file itself**, before
  any code or test changes:
  `docs(plans): add plan for backup status arrow fill animation`
- Follow strict TDD (Red → Green → Refactor) exactly as laid out in the
  "Step-by-step implementation" section below. Tests are written and observed to
  FAIL before any implementation code changes.
- Run every project command through the wrapper: `./run.sh <command>`.
- Do not modify any file other than the ones listed in "Files to modify" (plus the
  session log and the finished marker).
- **When the entire plan is completely finished** (all commits made, all quality
  gates green, session log written), create an empty marker file:

  ```
  touch /tmp/SDH-ludusavi/2026-06-11_animate_backup_status_arrow_fill_finished
  ```

  Do not create this file earlier. It signals completion to the supervising session.

---

## Problem Definition

The auto-sync status bar (rendered into a Steam BrowserView as a static HTML string)
shows animated icons for several states:

- `checking` → spinning ring (`.icon-spin`, `@keyframes spin`)
- `syncthing_pending_upload` → spinning ring inside cloud (`.icon-spin-ring`)
- `syncthing_uploading` → a light rect clipped to the cloud's arrow cutout that
  repeatedly slides upward (`.upload-arrow-fill`, `@keyframes arrow-fill-up`)

But the **`backing_up`** ("BACKING UP LOCAL SAVE") and **`restoring`**
("RESTORING BACKUP SAVE") states show a completely **static** icon: a blue filled
circle with a stroked arrow. Ludusavi provides no progress percentage, so the state
is indeterminate; the fix is a looping animation like the existing ones.

User decision (already made — do not re-ask): use the **arrow-fill** style matching
the Syncthing upload cloud animation, applied to **both** `backing_up` and
`restoring`. `restoring` reuses the same SVG rotated 180°, so the fill naturally
reads as moving downward.

## Architecture Overview

Everything lives in one renderer module that produces a self-contained HTML string
(no React at render time, no external CSS):

- `src/surfaces/autoSyncStatusRenderer.tsx`
  - `iconSvgForAutoSyncStatus(status)` returns a raw `<svg>` string per status.
    The **fallback** return at the bottom (currently lines 171–172) is the circle +
    stroked-arrow icon shared by `backing_up`, `restoring`, `conflict`,
    `syncthing_unavailable`, `syncthing_folder_not_found`, and
    `syncthing_no_peers`. For `restoring` it adds
    `style="transform: rotate(180deg); transform-origin: 50% 50%;"`.
  - `renderAutoSyncStatusHtml(state)` embeds the icon plus a `<style>` block that
    already contains `@keyframes spin` and `@keyframes arrow-fill-up`.
- `src/surfaces/autoSyncStatusSurface.ts(x)` re-exports the renderer symbols used
  by tests (tests import `iconSvgForAutoSyncStatus` from `./autoSyncStatusSurface`
  and `renderAutoSyncStatusHtml` from `./autoSyncStatusRenderer`).
- Tests: `src/surfaces/autoSyncStatusSurface.test.ts` (vitest).

**Critical constraint:** the warning/terminal statuses (`conflict`,
`syncthing_unavailable`, `syncthing_folder_not_found`, `syncthing_no_peers`) share
the fallback icon and MUST remain static. Existing test (around line 122) asserts
`iconSvgForAutoSyncStatus("syncthing_no_peers")` is identical to
`iconSvgForAutoSyncStatus("syncthing_unavailable")`. Therefore: **do NOT change the
fallback return.** Instead add a new explicit branch for `backing_up` / `restoring`
ABOVE the fallback.

## Core Data Structures

No type changes. `AutoSyncStatusKind` and `AutoSyncStatusState`
(`src/types/index.ts`) already contain everything needed. There is no progress
percentage anywhere in the pipeline — the animation is indeterminate/looping by
design.

## Public Interfaces

No signature changes. Only the string output of two existing functions changes:

1. `iconSvgForAutoSyncStatus("backing_up" | "restoring")` returns a new SVG.
2. `renderAutoSyncStatusHtml(...)` gains one keyframes block + one CSS class in its
   embedded `<style>`.

## Dependency Requirements

None. No new packages, no Python changes. Pure CSS keyframes (GPU-driven), same
technique as the existing `arrow-fill-up` animation.

---

## Step-by-step implementation

### Step 0 — Commit this plan file

```
git add docs/plans/2026-06-11_animate_backup_status_arrow_fill.md
git commit -m "docs(plans): add plan for backup status arrow fill animation"
```

(Plain `git commit` is fine; pre-commit hooks must pass. This is a docs-only commit.)

### Step 1 — RED: add failing tests

Append a new `describe` block to `src/surfaces/autoSyncStatusSurface.test.ts`,
mirroring the existing "Uploading Arrow Animation" block (lines 73–100):

```ts
describe("AutoSyncStatusSurface Local Backup Arrow Animation", () => {
  it("renders the backing_up circle with an arrow cutout and clipped fill rect", () => {
    const backupIcon = iconSvgForAutoSyncStatus("backing_up");
    expect(backupIcon).toContain("<svg");
    expect(backupIcon).toContain("<clipPath");
    expect(backupIcon).toContain('id="backup-arrow-clip"');
    expect(backupIcon).toContain('class="backup-arrow-fill"');
    expect(backupIcon).toContain('fill-rule="evenodd"');
  });

  it("shares the animated icon with restoring, rotated 180 degrees", () => {
    const restoreIcon = iconSvgForAutoSyncStatus("restoring");
    expect(restoreIcon).toContain('class="backup-arrow-fill"');
    expect(restoreIcon).toContain("rotate(180deg)");
    expect(iconSvgForAutoSyncStatus("backing_up")).not.toContain("rotate(180deg)");
  });

  it("keeps the static fallback icon for warning statuses", () => {
    expect(iconSvgForAutoSyncStatus("backing_up")).not.toBe(
      iconSvgForAutoSyncStatus("syncthing_unavailable"),
    );
    expect(iconSvgForAutoSyncStatus("syncthing_no_peers")).not.toContain(
      "backup-arrow-fill",
    );
    expect(iconSvgForAutoSyncStatus("conflict")).not.toContain("backup-arrow-fill");
  });

  it("defines the backup arrow fill keyframes in the rendered html", () => {
    const backingUpHtml = renderAutoSyncStatusHtml({
      status: "backing_up",
      visible: true,
      source: "rpc_result",
    });
    expect(backingUpHtml).toContain("@keyframes backup-arrow-fill-up");
    expect(backingUpHtml).toContain(".backup-arrow-fill");
  });
});
```

Run and confirm these tests FAIL (existing tests must still pass):

```
./run.sh pnpm run test:unit
```

If `pnpm` is unavailable through the wrapper, use the project's documented frontend
test command from `package.json` (`test:unit` = `vitest run`). Do not proceed until
you have observed the new tests failing.

### Step 2 — GREEN: implement the icon and CSS

All edits in `src/surfaces/autoSyncStatusRenderer.tsx`.

**2a.** In `iconSvgForAutoSyncStatus`, insert a new branch immediately BEFORE the
final fallback `const rotation = ...` / `return` (currently lines 171–172). Leave
the fallback itself untouched:

```ts
if (status === "backing_up" || status === "restoring") {
  const rotation =
    status === "restoring"
      ? ' style="transform: rotate(180deg); transform-origin: 50% 50%;"'
      : "";
  return `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"${rotation}><defs><clipPath id="backup-arrow-clip"><path d="M11.6 15.2h-3.2v-4.8H5.9L10 4.8l4.1 5.6h-2.5z"/></clipPath></defs><path d="M10 1.2a8.8 8.8 0 1 0 0 17.6 8.8 8.8 0 0 0 0-17.6zM11.6 15.2h-3.2v-4.8H5.9L10 4.8l4.1 5.6h-2.5z" fill="currentColor" fill-rule="evenodd"/><rect class="backup-arrow-fill" x="5.5" y="4.8" width="9" height="10.4" fill="#f8fafc" clip-path="url(#backup-arrow-clip)"/></svg>`;
}
```

Geometry notes (20×20 user units, do not "fix" these):
- Outer subpath = the same r=8.8 circle as before, drawn with arcs.
- Inner subpath = an upward arrow polygon: tip (10, 4.8), head spanning
  x 5.9–14.1 at y 10.4, shaft x 8.4–11.6 down to y 15.2. With
  `fill-rule="evenodd"` the arrow becomes a transparent cutout in the circle —
  same construction as the Syncthing upload cloud
  (`M288 276v76h-64v-76h-68l100-100 100 100h-68z`).
- The `<rect>` covers the arrow bounding box; the clipPath restricts it to the
  arrow shape; CSS slides it up by the arrow height (10.4px).

**2b.** In `renderAutoSyncStatusHtml`, add to the `<style>` block, directly after
the existing `.upload-arrow-fill` rule (currently lines 215–222):

```css
@keyframes backup-arrow-fill-up {
  0% { transform: translateY(10.4px); }
  75% { transform: translateY(0); }
  100% { transform: translateY(0); }
}
.backup-arrow-fill {
  animation: backup-arrow-fill-up 1.6s ease-out infinite;
}
```

Same 1.6s / ease-out / 75%-hold cadence as `arrow-fill-up` for visual consistency.

**2c.** Re-run `./run.sh pnpm run test:unit` — all tests (new and existing) must
pass. Also run the typecheck: `./run.sh pnpm run typecheck` (or
`./run.sh pnpm run test`, which runs both).

### Step 3 — REFACTOR

No structural refactor expected. Verify the new branch and keyframes sit adjacent
to their upload-cloud counterparts and read consistently. Do not extract shared
helpers unless tests stay green and the change is trivially safe.

### Step 4 — Quality gates (all must pass)

```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run test
```

No Python files change in this task, but the gates are mandatory before commit.
Caches must stay under `/tmp/SDH-ludusavi/` (the wrapper handles this).

### Step 5 — Commit the feature

Single atomic commit containing the test file + renderer change:

```
git add src/surfaces/autoSyncStatusSurface.test.ts src/surfaces/autoSyncStatusRenderer.tsx
git commit -m "feat(status): animate backup arrow fill inside circle icon"
```

### Step 6 — Session log + final commit

Write `docs/agent_conversations/2026-06-11_animate_backup_status_arrow_fill.md`
containing: date, task objective, files modified, tests added, design decisions
(new branch instead of touching the shared fallback icon; evenodd cutout + clipped
rect matching `cfb722d`), and results (test/gate output summary). Commit:

```
git commit -m "docs: agent session log for backup arrow fill animation"
```

### Step 7 — Completion marker

Only after Steps 0–6 are fully done:

```
touch /tmp/SDH-ludusavi/2026-06-11_animate_backup_status_arrow_fill_finished
```

---

## Testing Strategy

- Unit tests (vitest) assert the rendered SVG/HTML strings, exactly like the
  existing animation tests — no DOM or visual testing infrastructure exists, and
  string assertions are the established pattern in
  `src/surfaces/autoSyncStatusSurface.test.ts`.
- Regression safety: the explicit "warning statuses stay static" test pins the
  fallback icon behavior, and the pre-existing test asserting
  `syncthing_no_peers` ≡ `syncthing_unavailable` must continue to pass unchanged.
- README does not document per-status icons; no README change required.

## Definition of Done checklist

```
[ ] Plan file committed first (Step 0)
[ ] New tests written and observed failing before implementation (Step 1)
[ ] All vitest tests + tsc typecheck pass (Step 2c)
[ ] ruff check / ruff format / ty check / pytest pass via ./run.sh (Step 4)
[ ] feat commit + session log commit made on dev (Steps 5–6)
[ ] /tmp/SDH-ludusavi/2026-06-11_animate_backup_status_arrow_fill_finished created (Step 7)
```
