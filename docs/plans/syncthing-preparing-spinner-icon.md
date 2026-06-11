# Spinning Cloud-Circle Icon for "SYNCTHING PREPARING" Status

Status: planned (not yet implemented)
Date: 2026-06-11
Branch: implement on `dev` (or a `feat/` branch off `dev` per repo convention)

---

## Problem Definition

The auto-sync status bar shows **"SYNCTHING PREPARING"** (status kind
`syncthing_pending_upload`) with a **static** cloud icon (`IoMdCloudUpload` from
`react-icons/io`). A static cloud reads as finished/idle, but this state means work is
in progress (Syncthing is preparing to upload the save).

Desired behavior: replace the icon with the **`IoCloudCircleOutline`** look from
`react-icons/io5` — a cloud inside a circular outline — where **the circle ring spins**
with the exact same motion (1s linear infinite rotation) as the existing `checking`
("VERIFYING GAME SAVE") spinner, while **the cloud in the center stays static and
upright**.

Constraints:

- Only the `syncthing_pending_upload` status changes. `syncthing_uploading`,
  `syncthing_downloading`, and `syncthing_complete` keep their current static cloud
  icons. `checking` keeps its current spinner exactly as-is.
- Status text ("SYNCTHING PREPARING"), icon color (#1a9fff blue), and
  visibility/auto-hide behavior must not change.

## Architecture Overview

There is exactly **one** render path for the status bar icon:

```
src/controllers/gameLifecycleController.tsx:444
  publishAutoSyncStatus("syncthing_pending_upload", ...)
        │
        ▼
src/surfaces/autoSyncStatusSurface.tsx        (state management, no icon rendering)
        │
        ▼
src/surfaces/autoSyncStatusBrowserView.ts:207 (calls renderAutoSyncStatusHtml(state))
        │
        ▼
src/surfaces/autoSyncStatusRenderer.tsx       (ALL changes happen in this file)
```

Inside `src/surfaces/autoSyncStatusRenderer.tsx` (line numbers as of commit `4a1c9d7`):

- `iconSvgForAutoSyncStatus(status)` (line 147) returns an SVG markup **string** per
  status. Hand-crafted inline SVG strings are used for `has_backup`, `unknown`,
  `error`, and `checking`. For `syncthing_*` statuses it currently delegates to
  `getSerializedIcon()` (line 126), which serializes react-icons components
  (`syncthing_pending_upload` → `IoMdCloudUpload` at line 134).
- `renderAutoSyncStatusHtml(state)` (line 173) produces a full HTML document. Its
  `<style>` block defines `@keyframes spin` and the `.icon-spin svg` rule (lines
  201–208). The `icon-spin` class is applied at line 213 only when
  `state.status === "checking"`.

The new icon will be a **hand-crafted inline SVG string** (matching the existing
pattern for `checking` etc.), NOT a serialized react-icons component. Do **not** add
an import of `IoCloudCircleOutline`; its path data is embedded directly below. Reason:
`serializeIcon()` flattens icon children and cannot wrap only the circle in an
animated group, and hand-crafted strings are the established pattern in this file.

## Core Data Structures

No new types. `AutoSyncStatusKind` (defined in `src/types/index.ts`, includes
`"syncthing_pending_upload"`) and `AutoSyncStatusState` are unchanged.

SVG path data (extracted verbatim from `react-icons@5.3.0` `io5/index.js`,
`IoCloudCircleOutline`, viewBox `0 0 512 512`):

- **Circle ring** (stroked, will spin):
  `M448 256c0-106-86-192-192-192S64 150 64 256s86 192 192 192 192-86 192-192z`
- **Cloud** (filled, stays static):
  `M333.88 240.59a8 8 0 0 1-6.66-6.66C320.68 192.78 290.82 168 256 168c-32.37 0-53.93 21.22-62.48 43.58a7.92 7.92 0 0 1-6.16 5c-27.67 4.35-50.82 22.56-51.35 54.3-.52 31.53 25.51 57.11 57 57.11H326c27.5 0 50-13.72 50-44 0-27.22-22-40.41-42.12-43.4z`
- **Quarter-arc gap overlay** (new, hand-derived): a perfectly symmetric ring shows no
  visible rotation, so overlay the same dark (#0b151f) quarter arc the `checking`
  spinner uses, scaled to this viewBox: `M256 64a192 192 0 0 1 192 192`
  (top of circle → right of circle, radius 192, centered at 256,256).

## Public Interfaces

No public interface signatures change. Behavior changes:

1. `iconSvgForAutoSyncStatus("syncthing_pending_upload")` returns the new
   spinner-cloud SVG string (previously: serialized `IoMdCloudUpload`, identical to
   the `syncthing_uploading` icon).
2. `renderAutoSyncStatusHtml(state)` output for `syncthing_pending_upload` contains a
   new CSS class `icon-spin-ring` on the icon `<span>` and a new CSS rule animating
   `.spinner-ring`.

## Dependency Requirements

None. No new packages, no new imports. `react-icons@5.3.0` is already a dependency
(only used as the source of the embedded path data; the io5 module is not imported).

---

## Implementation Steps (exact edits)

All edits are in `src/surfaces/autoSyncStatusRenderer.tsx` and
`src/surfaces/autoSyncStatusSurface.test.ts`. Follow strict TDD: do Step 1, run the
tests, confirm the new tests FAIL, then do Steps 2–5.

### Step 1 — Tests first (RED)

In `src/surfaces/autoSyncStatusSurface.test.ts`, **replace** this existing test
(currently lines 30–35):

```ts
  it("should render correct icon for syncthing_pending_upload matching syncthing_uploading", () => {
    const pendingIcon = iconSvgForAutoSyncStatus("syncthing_pending_upload");
    const uploadingIcon = iconSvgForAutoSyncStatus("syncthing_uploading");
    expect(pendingIcon).toBe(uploadingIcon);
    expect(pendingIcon).toContain("<svg");
  });
```

with:

```ts
  it("renders a spinner-ring cloud icon for syncthing_pending_upload", () => {
    const pendingIcon = iconSvgForAutoSyncStatus("syncthing_pending_upload");
    expect(pendingIcon).toContain("<svg");
    expect(pendingIcon).toContain('class="spinner-ring"');
    // Static cloud path from IoCloudCircleOutline stays outside the spinning group.
    expect(pendingIcon).toContain("M333.88 240.59");
    expect(pendingIcon).not.toBe(iconSvgForAutoSyncStatus("syncthing_uploading"));
  });

  it("applies the ring-spin animation class only to syncthing_pending_upload", () => {
    const pendingHtml = renderAutoSyncStatusHtml({
      status: "syncthing_pending_upload",
      visible: true,
      source: "rpc_result",
    });
    expect(pendingHtml).toContain("icon-spin-ring");
    expect(pendingHtml).toContain(".icon-spin-ring .spinner-ring");

    const completeHtml = renderAutoSyncStatusHtml({
      status: "syncthing_complete",
      visible: true,
      source: "rpc_result",
    });
    expect(completeHtml).not.toContain('class="icon icon-spin-ring"');
  });
```

Notes:
- `renderAutoSyncStatusHtml` is already imported in this test file (line 8). The
  `AutoSyncStatusState` literal shape `{ status, visible, source }` matches the
  existing usage at lines 67–71 of the test file.
- Run: `pnpm run test:unit` — the two new tests MUST fail (old icon has no
  `spinner-ring`, HTML has no `icon-spin-ring`). All other tests must still pass.

### Step 2 — Remove pending_upload from the serialized react-icons path

In `src/surfaces/autoSyncStatusRenderer.tsx`, in `getSerializedIcon()` change
(currently line 134):

```ts
  } else if (status === "syncthing_uploading" || status === "syncthing_pending_upload") {
```

to:

```ts
  } else if (status === "syncthing_uploading") {
```

### Step 3 — Return the new SVG from `iconSvgForAutoSyncStatus`

In the same file, inside `iconSvgForAutoSyncStatus()`, **insert a new branch
immediately after the `checking` branch** (after current line 159) :

```ts
  if (status === "syncthing_pending_upload") {
    return '<svg viewBox="0 0 512 512" width="18" height="18" aria-hidden="true"><g class="spinner-ring"><path d="M448 256c0-106-86-192-192-192S64 150 64 256s86 192 192 192 192-86 192-192z" fill="none" stroke="currentColor" stroke-miterlimit="10" stroke-width="32" opacity="0.8"/><path d="M256 64a192 192 0 0 1 192 192" fill="none" stroke="#0b151f" stroke-width="32" stroke-linecap="round"/></g><path d="M333.88 240.59a8 8 0 0 1-6.66-6.66C320.68 192.78 290.82 168 256 168c-32.37 0-53.93 21.22-62.48 43.58a7.92 7.92 0 0 1-6.16 5c-27.67 4.35-50.82 22.56-51.35 54.3-.52 31.53 25.51 57.11 57 57.11H326c27.5 0 50-13.72 50-44 0-27.22-22-40.41-42.12-43.4z" fill="currentColor"/></svg>';
  }
```

Then **remove** `status === "syncthing_pending_upload" ||` from the serialized-icon
condition (currently lines 160–165), leaving:

```ts
  if (
    status === "syncthing_downloading" ||
    status === "syncthing_uploading" ||
    status === "syncthing_complete"
  ) {
    return getSerializedIcon(status);
  }
```

### Step 4 — Add the CSS rule for the spinning ring

In `renderAutoSyncStatusHtml()`, in the `<style>` block, directly after the existing
`.icon-spin svg { ... }` rule (currently lines 205–208), add:

```css
.icon-spin-ring .spinner-ring {
  animation: spin 1s linear infinite;
  transform-origin: 256px 256px;
}
```

Details that matter:
- Reuses the existing `@keyframes spin` — do not duplicate the keyframes.
- `transform-origin: 256px 256px` is the viewBox center (`0 0 512 512`). Do NOT use
  `50% 50%` here: percentage transform-origin on an SVG **child element** (the `<g>`)
  resolves against the element's bounding box only with `transform-box: fill-box`,
  and against the view-box otherwise depending on browser; explicit user units are
  unambiguous. (The existing `.icon-spin svg` rule uses `50% 50%` safely because it
  transforms the outer `<svg>` element itself — leave it untouched.)

### Step 5 — Apply the class in the rendered HTML

Change the icon span at the bottom of `renderAutoSyncStatusHtml()` (currently
line 213) from:

```ts
  <div class="text"><span class="icon${state.status === "checking" ? " icon-spin" : ""}">${iconSvgForAutoSyncStatus(state.status)}</span>${autoSyncStatusText[state.status]}</div>
```

to:

```ts
  <div class="text"><span class="icon${state.status === "checking" ? " icon-spin" : state.status === "syncthing_pending_upload" ? " icon-spin-ring" : ""}">${iconSvgForAutoSyncStatus(state.status)}</span>${autoSyncStatusText[state.status]}</div>
```

### Explicitly out of scope / do NOT touch

- `autoSyncStatusText` map, `isLudusaviRunningStatus`, `isSyncthingActiveStatus`,
  `shouldAutoHideStatus` — unchanged.
- The `.icon` color expression (line 200) — `syncthing_pending_upload` already falls
  through to `#1a9fff` blue; `currentColor` in the new SVG picks that up.
- `src/surfaces/autoSyncStatusSurface.tsx`, `autoSyncStatusBrowserView.ts`,
  `gameLifecycleController.tsx` — no changes needed.
- Do not import anything from `react-icons/io5`.
- Python backend — completely untouched.

---

## Testing Strategy

1. **Unit (vitest)** — Step 1 tests above. Run via:
   ```
   pnpm run test:unit
   ```
   Red before Steps 2–5, green after. The full suite must pass (the replaced test was
   the only one asserting pending == uploading icon; `grep -rn "pending_upload" src/`
   to confirm no other test depends on the old icon).
2. **Typecheck** — `pnpm run test` (runs vitest + `pnpm run typecheck`).
3. **Visual smoke test** — render the HTML to a file and inspect:
   ```bash
   node -e '
     const { renderAutoSyncStatusHtml } = require("./src/surfaces/autoSyncStatusRenderer");
   ' 2>/dev/null || true
   ```
   The renderer is TypeScript, so instead add a throwaway vitest `it.only` locally or
   simply write the expected HTML by calling the function inside a test and dumping it
   with `console.log`, save to `/tmp/SDH-ludusavi/status_preview.html`, open in a
   browser: the ring (blue with dark quarter-gap) must rotate once per second; the
   cloud must remain stationary and upright. Delete any throwaway test before commit.
4. **Project quality gates** (required by CLAUDE.md before commit, even though the
   backend is untouched):
   ```
   ./run.sh uv run ruff check . --fix
   ./run.sh uv run ruff format .
   ./run.sh uv run ty check py_modules/sdh_ludusavi/
   ./run.sh uv run pytest
   ```
5. **On-device (optional)** — package the plugin and confirm that exiting a tracked
   game shows "SYNCTHING PREPARING" with the spinning ring + static cloud.

## Commit

Single atomic commit (tests + implementation), Conventional Commits:

```
feat(status): spin cloud-circle icon while Syncthing prepares upload
```

Record a session log in `docs/agent_conversations/` per protocol section 15.
