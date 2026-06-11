# Syncthing Upload Arrow Fill Animation

Status: PLANNED (not implemented)
Date: 2026-06-11

## Problem Definition

While `syncthing_uploading` is active, the status bar surface shows a static
cloud-with-up-arrow icon (`IoMdCloudUpload` from react-icons, serialized to a
plain SVG string). The desired behavior: the arrow inside the cloud should
animate in a loop — visibly "filling up" from bottom to top — to communicate
ongoing upload activity, consistent with the animated treatments that already
exist for `checking` (spinning circle) and `syncthing_pending_upload`
(spinning ring around a cloud).

This change is presentation-only. No state machine, backend, or visibility
logic changes.

## Files Involved

| File | Role |
|---|---|
| `src/surfaces/autoSyncStatusRenderer.tsx` | The ONLY file with implementation changes |
| `src/surfaces/autoSyncStatusSurface.test.ts` | New tests (written FIRST, per TDD) |
| `docs/agent_conversations/` | Session log written at the end |

Do not touch any other file. Do not touch `main.py`, `py_modules/`, or
anything under `tests/` (those are Python backend tests; this feature is
frontend-only).

## Verified Facts (do not re-derive, do not guess)

These were verified against the working tree and
`node_modules/react-icons/io/index.mjs` on 2026-06-11:

1. `iconSvgForAutoSyncStatus(status)` in `src/surfaces/autoSyncStatusRenderer.tsx`
   (currently around line 147) returns a raw SVG markup string per status.
   For `syncthing_downloading | syncthing_uploading | syncthing_complete` it
   delegates to `getSerializedIcon(status)`, which serializes the react-icons
   component into a static string and caches it in `serializedIconsCache`.

2. The serializer (`serializeSvgNode`) only supports `path` and `g` tags and
   a whitelist of attributes. It CANNOT emit `defs`, `clipPath`, `rect`, or
   `class` attributes. **Therefore the animated icon must be a hand-authored
   SVG string**, exactly like the existing `syncthing_pending_upload` branch
   (which hand-authors a spinner-ring SVG with `class="spinner-ring"`).
   Do NOT extend the serializer.

3. The full `IoMdCloudUpload` path data (viewBox `0 0 512 512`) is:

   ```
   M403.002 217.001C388.998 148.002 328.998 96 256 96c-57.998 0-107.998 32.998-132.998 81.001C63.002 183.002 16 233.998 16 296c0 65.996 53.999 120 120 120h260c55 0 100-45 100-100 0-52.998-40.996-96.001-92.998-98.999zM288 276v76h-64v-76h-68l100-100 100 100h-68z
   ```

   The second subpath (`M288 276v76h-64v-76h-68l100-100 100 100h-68z`) is the
   up-arrow, rendered as a **cutout** (negative space) inside the cloud due to
   winding direction. Its bounding box is x: 156–356 (width 200),
   y: 176–352 (height 176). Arrow tip is at (256, 176).

4. `renderAutoSyncStatusHtml(state)` (bottom of the same file) wraps the icon
   in a full HTML document with an inline `<style>` block. That block already
   contains `@keyframes spin` plus `.icon-spin` and `.icon-spin-ring` rules —
   proof that CSS keyframe animations on SVG content work in this surface
   (Steam's embedded Chromium). The icon `<span class="icon...">` only gets an
   extra class for `checking` and `syncthing_pending_upload`.

5. Icon color comes from `color:` on `.icon` (`#1a9fff` for syncthing
   statuses) via `fill="currentColor"`. Bar background is
   `rgba(0, 0, 0, 0.34)`; text color is `#f8fafc`.

6. Frontend tests run with vitest: `pnpm run test:unit`. `pnpm test` also runs
   `tsc --noEmit`. Run both through the wrapper: `./run.sh pnpm test`.

## Architecture Overview

Animation concept: keep the cloud-with-cutout path exactly as it looks today,
then place a `<rect>` over the arrow's bounding box, clipped to the arrow
shape via `<clipPath>`, filled `#f8fafc` (the bar text color, contrasting with
both the blue cloud and the dark cutout). A CSS keyframe animation translates
the rect vertically: it starts fully below the arrow (`translateY(176px)` —
invisible because the clip shows nothing), slides up to `translateY(0)`
(arrow fully filled with white), holds briefly, then loops. Visual result:
the dark arrow cutout fills with white from bottom to top, over and over.

Why this works: CSS `px` units in SVG transforms map to SVG user units, and
the rect height equals the arrow bbox height (176 user units), so
`translateY(176px)` puts the rect exactly one-arrow-height below its clipped
region. Chromium animates transforms on SVG child elements; the same
technique (CSS class on an inner SVG node) is already used by
`.icon-spin-ring .spinner-ring`.

The `clipPath` `id` can be a fixed string (`upload-arrow-clip`) because the
rendered HTML document only ever contains one status icon at a time.

## Core Data Structures

None. Both touched functions return strings.

## Public Interfaces

No signature changes.

- `iconSvgForAutoSyncStatus("syncthing_uploading")` returns the new
  hand-authored animated SVG instead of the serialized icon.
- `renderAutoSyncStatusHtml(...)` output gains two CSS rules (keyframes +
  rect rule) for every status. This is harmless: only the uploading SVG
  contains the `upload-arrow-fill` class.

## Dependency Requirements

None added, none removed at the package level. Within
`autoSyncStatusRenderer.tsx`, `IoMdCloudUpload` becomes unused after the
change — **remove it from the import on line 1 and from the if-chain inside
`getSerializedIcon`** so lint/typecheck stays clean.

## Step-by-Step Implementation (strict order)

### Step 1 — RED: add failing tests

Append this `describe` block to `src/surfaces/autoSyncStatusSurface.test.ts`
(e.g., right before the `"AutoSyncStatusSurface No Connected Peers"` block).
Use it verbatim:

```ts
describe("AutoSyncStatusSurface Uploading Arrow Animation", () => {
  it("renders the uploading cloud with a clipped fill rect over the arrow cutout", () => {
    const uploadIcon = iconSvgForAutoSyncStatus("syncthing_uploading");
    expect(uploadIcon).toContain("<svg");
    // Cloud body with the arrow cutout from IoMdCloudUpload stays intact.
    expect(uploadIcon).toContain("M403.002 217.001");
    expect(uploadIcon).toContain("M288 276v76h-64v-76h-68l100-100 100 100h-68z");
    expect(uploadIcon).toContain("<clipPath");
    expect(uploadIcon).toContain('class="upload-arrow-fill"');
  });

  it("animates the arrow fill upward only for syncthing_uploading", () => {
    const uploadingHtml = renderAutoSyncStatusHtml({
      status: "syncthing_uploading",
      visible: true,
      source: "rpc_result",
    });
    expect(uploadingHtml).toContain("@keyframes arrow-fill-up");
    expect(uploadingHtml).toContain(".upload-arrow-fill");

    const downloadingHtml = renderAutoSyncStatusHtml({
      status: "syncthing_downloading",
      visible: true,
      source: "rpc_result",
    });
    expect(downloadingHtml).not.toContain('class="upload-arrow-fill"');
  });
});
```

Run `./run.sh pnpm run test:unit` and confirm exactly these new tests fail
(everything else must still pass). Do not proceed until you have seen the
failure.

### Step 2 — GREEN: implement in `src/surfaces/autoSyncStatusRenderer.tsx`

**2a.** In `iconSvgForAutoSyncStatus`, add a dedicated branch for
`syncthing_uploading` BEFORE the combined
`syncthing_downloading / syncthing_uploading / syncthing_complete` branch,
and remove `syncthing_uploading` from that combined condition. New branch
(single line, double quotes inside the SVG, single-quoted TS string — same
style as the `syncthing_pending_upload` branch):

```ts
if (status === "syncthing_uploading") {
  return '<svg viewBox="0 0 512 512" width="18" height="18" aria-hidden="true"><defs><clipPath id="upload-arrow-clip"><path d="M288 276v76h-64v-76h-68l100-100 100 100h-68z"/></clipPath></defs><path d="M403.002 217.001C388.998 148.002 328.998 96 256 96c-57.998 0-107.998 32.998-132.998 81.001C63.002 183.002 16 233.998 16 296c0 65.996 53.999 120 120 120h260c55 0 100-45 100-100 0-52.998-40.996-96.001-92.998-98.999zM288 276v76h-64v-76h-68l100-100 100 100h-68z" fill="currentColor"/><rect class="upload-arrow-fill" x="156" y="176" width="200" height="176" fill="#f8fafc" clip-path="url(#upload-arrow-clip)"/></svg>';
}
```

The combined branch becomes:

```ts
if (status === "syncthing_downloading" || status === "syncthing_complete") {
  return getSerializedIcon(status);
}
```

**2b.** In `getSerializedIcon`, delete the
`else if (status === "syncthing_uploading") { icon = IoMdCloudUpload; }`
arm (the `syncthing_uploading` status no longer reaches this function).

**2c.** On line 1, change the import to
`import { IoMdCloudDownload, IoMdCloudDone } from "react-icons/io";`
(drop `IoMdCloudUpload`).

**2d.** In the `<style>` block inside `renderAutoSyncStatusHtml`, immediately
after the `.icon-spin-ring .spinner-ring { ... }` rule, add:

```css
@keyframes arrow-fill-up {
  0% { transform: translateY(176px); }
  75% { transform: translateY(0); }
  100% { transform: translateY(0); }
}
.upload-arrow-fill {
  animation: arrow-fill-up 1.6s ease-out infinite;
}
```

(75%→100% holds the fully-filled arrow ~0.4s before looping so the loop
restart doesn't look like flicker.)

Do NOT add any class to the `<span class="icon...">` wrapper in the body —
unlike the spin treatments, the animated class lives on the rect inside the
SVG itself, so no body-markup change is needed.

### Step 3 — verify GREEN

`./run.sh pnpm run test:unit` — all tests pass, including the pre-existing
assertion that the pending icon differs from the uploading icon
(`autoSyncStatusSurface.test.ts`, "renders a spinner-ring cloud icon..."
test). That assertion stays valid automatically.

### Step 4 — REFACTOR

Nothing expected. Do not reformat unrelated code.

### Step 5 — VALIDATE (full quality gate)

```
./run.sh pnpm test                                  # vitest + tsc --noEmit
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

Python gates must pass untouched (no Python files change). If ruff/format
modifies files outside this feature, stop and report — do not commit them.

### Step 6 — COMMIT

Branch: commit on `dev` (matches the convention of the prior status-bar
animation commits, e.g. `c7b7204`). Single atomic commit containing the
renderer change, the new tests, this plan file, and the session log:

```
feat(status): animate upload arrow filling inside cloud icon
```

Pre-commit hooks must run and pass.

### Step 7 — DOCUMENT

Write a session log to
`docs/agent_conversations/<YYYY-MM-DD>_upload_arrow_fill_animation.json`
following the format of the existing logs in that directory (date, task
objective, files modified, tests added, design decisions, results).

README does not change (no user-facing usage/installation change).

## Pitfalls / Things a Naive Implementer Will Get Wrong

1. **Do not extend `serializeSvgNode`** to support `rect`/`clipPath`/`defs`.
   Hand-author the SVG string. The serializer warning log
   (`Unsupported SVG tag`) must never fire for this icon.
2. **Do not animate the serialized icon's existing path** — the arrow is a
   cutout subpath of one `<path>`; it cannot move independently.
3. **Keep both subpaths in the cloud path.** If you drop the arrow cutout
   subpath from the cloud `<path>`, the white fill rect will paint on top of
   a solid blue cloud and the "empty arrow" resting state disappears.
4. **Rect geometry must match the arrow bbox exactly** (x=156, y=176,
   width=200, height=176) and the keyframe start must be `translateY(176px)`
   (the bbox height). Any mismatch shows a sliver of fill at rest or clips
   the fill early.
5. **Quote style:** the returned TS string is single-quoted; all SVG
   attributes use double quotes. A stray single quote breaks the file.
6. **Don't add `icon-spin` / `icon-spin-ring`** to the uploading status — the
   cloud must stay stationary; only the inner rect animates.
7. **Remove the unused `IoMdCloudUpload` import** or typecheck/lint will flag
   it (and TDD's Step 2c covers it).
8. **`serializedIconsCache`** only caches `syncthing_downloading` and
   `syncthing_complete` after this change; no cache invalidation needed since
   the uploading branch returns a literal.

## Testing Strategy

- Unit (vitest, RED-first as in Step 1): icon markup contains the cloud path,
  the arrow `clipPath`, and the `upload-arrow-fill` rect; rendered HTML
  contains the `arrow-fill-up` keyframes; downloading status does not contain
  the fill rect.
- Regression: full existing vitest suite + `tsc --noEmit` + Python gates.
- Manual (optional, recommended): build with `./run.sh pnpm run build`,
  deploy to the Deck, trigger a backup with Syncthing connected, and watch
  the bar during `SYNCTHING UPLOADING` — the arrow should fill white from
  bottom to top about every 1.6 seconds with a short hold when full. To eyeball
  it quickly without a Deck, paste the `syncthing_uploading` output of
  `renderAutoSyncStatusHtml` into a local .html file and open it in a browser.
