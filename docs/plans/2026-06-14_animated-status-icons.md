# Plan: Auto-Sync Status Icon Updates (animated-status-icons)

## Context

The bottom-of-screen auto-sync status strip shows an icon + label for each save-sync
state. Six refinements are wanted so the states read more clearly:

1. After a local backup, the strip jumps straight from **Backing Up Local Save** to
   **Syncthing Preparing**. It should briefly show **Game Save Up To Date** in between
   (backing_up → has_backup → syncthing_pending_upload).
2. **Syncthing Downloading** is a static cloud-down icon. It should animate like
   **Syncthing Uploading** (a cloud whose arrow "fills", but downward).
3. **Local Backup Saved — Syncthing Unavailable** currently shows the generic
   circle-with-up-arrow fallback. It should keep its amber color but use the same cloud
   shape the other Syncthing states use, marked with an "X" (the visual idea of
   `faCloudXmark`).
4. **Save Conflict** is blue. It should be amber, matching the "Local Backup Saved —
   Syncthing Unavailable" warning color.
5. **Local Backup Saved — Path Not Shared** and **Local Backup Saved — No Syncthing
   Peers Online** should use the same cloud-with-X icon as Syncthing Unavailable.
6. `docs/animated-status-icons-reference.html` (the visual catalog of these icons) must
   be updated to match all of the above.

Intended outcome: clearer, more consistent status iconography and a correct
post-backup status sequence, reflected both in the running plugin and in the reference
HTML.

This is a **frontend-only** change (TypeScript/React under `src/`, plus one HTML doc).
No Python (`py_modules/`) changes.

**Slug used throughout this plan:** `animated-status-icons`

---

## Working setup (do this first)

1. Use the **implementer** skill for this work.
2. Output the `AGENT_PROTOCOL_HANDSHAKE` (CLAUDE.md §1) after verifying filesystem and
   dependency state. Caches/venv stay under `/tmp/sdh_ludusavi/` (see `run.sh`).
3. Branch off `dev`:
   ```
   git checkout dev
   git pull --ff-only        # if a remote dev exists
   git checkout -b feat/animated-status-icons
   ```
4. This plan already lives at `docs/plans/2026-06-14_animated-status-icons.md`; commit it
   as the first commit on the branch.
5. Follow strict TDD (RED → GREEN → REFACTOR). Tests live in
   `src/surfaces/autoSyncStatusSurface.test.ts` and
   `src/controllers/gameLifecycleController.test.ts` (both vitest).

All icon rendering lives in one file: `src/surfaces/autoSyncStatusRenderer.tsx`. The
status string identifiers are the `AutoSyncStatusKind` union in `src/types/index.ts`.

---

## Change 1 — Post-backup sequence: backing_up → has_backup → syncthing_pending_upload

**File:** `src/controllers/gameLifecycleController.tsx` (backup-on-exit branch, ~line 430).

Currently, inside `if (result.status === "backed_up") {` the code activates the Syncthing
handoff and then publishes `syncthing_pending_upload` / `syncthing_uploading` / etc.
There is no `has_backup` step. Add a `has_backup` publish as the **first statement** of
that branch, before `const handoff = ...`:

```ts
if (result.status === "backed_up") {
  publishAutoSyncStatus("has_backup", {
    source: "lifecycle_exit",
    gameName: name,
    appID,
    tracked,
  });
  const handoff = postGameWatch === null
    ? { status: "unavailable" as const, reason: "watch_not_started" }
    : await postGameWatch.activatePostGameHandoff(750);
  // ...unchanged...
}
```

This shows **Game Save Up To Date** while the ≤750ms handoff-confirmation window runs,
then the existing switch replaces it with **Syncthing Preparing** (or uploading /
complete / a warning). Match the option object shape of the sibling
`syncthing_pending_upload` publish exactly (no `resultStatus`).

**TDD (RED first):** in `src/controllers/gameLifecycleController.test.ts`, add a test in
the existing "publishes pending" area asserting the order. Use the recorded call list:

```ts
const kinds = mockStatusSurface.publish.mock.calls.map((c: any) => c[0]);
expect(kinds.indexOf("has_backup")).toBeGreaterThanOrEqual(0);
expect(kinds.indexOf("has_backup")).toBeLessThan(kinds.indexOf("syncthing_pending_upload"));
```

The existing `toHaveBeenCalledWith("syncthing_pending_upload", ...)` assertions stay
valid (adding an earlier call does not break them). After implementing, run the whole
lifecycle suite and fix any count-sensitive assertion that the extra publish disturbs.

---

## Change 2 — Animate the Syncthing Downloading icon

**File:** `src/surfaces/autoSyncStatusRenderer.tsx`.

Today downloading goes through `getSerializedIcon` (static `IoMdCloudDownload`). Replace
it with a custom inline SVG that mirrors the uploading icon: the same cloud body, a
**down**-arrow cutout, and a clipped fill `<rect>` that animates downward.

1. Replace the combined downloading/complete branch:
   ```ts
   if (
     status === "syncthing_downloading" ||
     status === "syncthing_complete"
   ) {
     return getSerializedIcon(status);
   }
   ```
   with separate branches (downloading first, complete kept on `getSerializedIcon`):
   ```ts
   if (status === "syncthing_downloading") {
     return '<svg viewBox="0 0 512 512" width="18" height="18" aria-hidden="true"><defs><clipPath id="download-arrow-clip"><path d="M224 268v-76h64v76h68L256 368 156 268h68z"/></clipPath></defs><path d="M403.002 217.001C388.998 148.002 328.998 96 256 96c-57.998 0-107.998 32.998-132.998 81.001C63.002 183.002 16 233.998 16 296c0 65.996 53.999 120 120 120h260c55 0 100-45 100-100 0-52.998-40.996-96.001-92.998-98.999zM224 268v-76h64v76h68L256 368 156 268h68z" fill="currentColor"/><rect class="download-arrow-fill" x="156" y="192" width="200" height="176" fill="#f8fafc" clip-path="url(#download-arrow-clip)"/></svg>';
   }
   if (status === "syncthing_complete") {
     return getSerializedIcon(status);
   }
   ```
2. In `getSerializedIcon`, remove the `syncthing_downloading` branch so it only handles
   `syncthing_complete` (keep the cache and `IoMdCloudDone`).
3. Change the import at the top to drop the now-unused download icon:
   ```ts
   import { IoMdCloudDone } from "react-icons/io";
   ```
4. Add the keyframes + class to the `<style>` block in `renderAutoSyncStatusHtml`,
   right after the `backup-arrow-fill` block:
   ```css
   @keyframes arrow-fill-down {
     0% { transform: translateY(-176px); }
     75% { transform: translateY(0); }
     100% { transform: translateY(0); }
   }
   .download-arrow-fill {
     animation: arrow-fill-down 1.6s ease-out infinite;
   }
   ```

The arrow's bounding box is x156–356, y192–368 (width 200, height 176). The fill rect
starts translated up out of the clip region and descends to fill the arrow top-to-bottom
(the download counterpart to the upload "fill ↑"). No span-level animation class is
needed (the animation rides on the inner `.download-arrow-fill` rect, exactly like
`.upload-arrow-fill`).

**TDD (RED first):** extend the "animates the arrow fill upward only for
syncthing_uploading" test in `autoSyncStatusSurface.test.ts` (currently lines ~91–106).
Keep the existing assertion that downloading does **not** contain `upload-arrow-fill`,
and add:
```ts
expect(downloadingHtml).toContain('class="download-arrow-fill"');
expect(downloadingHtml).toContain("@keyframes arrow-fill-down");
```

---

## Change 3 + 5 — Cloud-with-X icon for the three "saved locally, Syncthing not done" warnings

**File:** `src/surfaces/autoSyncStatusRenderer.tsx`.

`syncthing_unavailable`, `syncthing_folder_not_found`, and `syncthing_no_peers`
currently fall through to the generic fallback icon. Give all three the same new
cloud-with-X icon (cloud body = the same shape used by the other Syncthing icons; X in
dark ink `#0b151f` over the `currentColor` cloud, matching the checkmark/exclamation
treatment of `has_backup`/`error`). They keep their amber color (driven by the `.icon`
color logic — no change needed there for these three).

Add this branch (place it after the `syncthing_complete` branch, before the fallback):
```ts
if (
  status === "syncthing_unavailable" ||
  status === "syncthing_folder_not_found" ||
  status === "syncthing_no_peers"
) {
  return '<svg viewBox="0 0 512 512" width="18" height="18" aria-hidden="true"><path d="M403.002 217.001C388.998 148.002 328.998 96 256 96c-57.998 0-107.998 32.998-132.998 81.001C63.002 183.002 16 233.998 16 296c0 65.996 53.999 120 120 120h260c55 0 100-45 100-100 0-52.998-40.996-96.001-92.998-98.999z" fill="currentColor"/><path d="M214 250 298 334M298 250 214 334" fill="none" stroke="#0b151f" stroke-width="34" stroke-linecap="round"/></svg>';
}
```

All three return the identical string, so the existing equality assertion
(`iconSvgForAutoSyncStatus("syncthing_no_peers") === iconSvgForAutoSyncStatus("syncthing_unavailable")`)
stays green. (Visual note: a centered X is used because at 18px a `faCloudXmark`-style
corner badge would be too small to read. Placement/size are easy to tweak in a later
review round if desired.)

**TDD (RED first):** update the existing "uses the amber warning style and fallback icon
treatment" test (currently lines ~121–132) so it asserts the new icon:
```ts
const icon = iconSvgForAutoSyncStatus("syncthing_unavailable");
expect(icon).toContain("M403.002 217.001");          // cloud body
expect(icon).toContain("M214 250 298 334");          // the X strokes
expect(icon).not.toContain('r="8.8"');               // not the old circle fallback
expect(iconSvgForAutoSyncStatus("syncthing_no_peers")).toBe(icon);
expect(iconSvgForAutoSyncStatus("syncthing_folder_not_found")).toBe(icon);
```
Keep the existing `#f59e0b` (amber) assertion. Rename the test description if "fallback"
no longer fits.

---

## Change 4 — Save Conflict turns amber

**File:** `src/surfaces/autoSyncStatusRenderer.tsx`, the `.icon { ... color: ... }`
ternary inside `renderAutoSyncStatusHtml`.

Add `conflict` to the amber group:
```ts
color: ${state.status === "error" ? "#ef4444" : state.status === "unknown" || state.status === "conflict" || state.status === "syncthing_unavailable" || state.status === "syncthing_folder_not_found" || state.status === "syncthing_no_peers" ? "#f59e0b" : "#1a9fff"};
```

The conflict **icon** is unchanged (it keeps the generic circle-with-up-arrow); only its
color changes.

**TDD (RED first):** add a test in `autoSyncStatusSurface.test.ts`:
```ts
it("renders the save-conflict status in amber", () => {
  const html = renderAutoSyncStatusHtml({ status: "conflict", visible: true, source: "rpc_result" });
  expect(html).toContain("#f59e0b");
});
```

---

## Change 6 — Update the reference HTML

**File:** `docs/animated-status-icons-reference.html`. Keep it faithful to the renderer.

1. **Keyframes block** (the `<style>` comment says "copied verbatim from
   autoSyncStatusRenderer.tsx"): add, after the `backup-arrow-fill` lines:
   ```css
   @keyframes arrow-fill-down { 0% { transform: translateY(-176px); } 75% { transform: translateY(0); } 100% { transform: translateY(0); } }
   .download-arrow-fill { animation: arrow-fill-down 1.6s ease-out infinite; }
   ```
2. **Syncthing Downloading card:** move it out of the "Terminal / passive states (static
   icons)" section and into the "Animated states (operation in progress)" grid (after the
   `syncthing_uploading` card). Replace its SVG with the animated download SVG from
   Change 2. Update tags to `<span class="tag anim">fill ↓</span><span class="tag persist">stays until next status</span>` and change the "when" wording from "Static
   cloud-down icon (no fill animation)" to "Cloud arrow fills downward."
3. **syncthing_unavailable, syncthing_folder_not_found, syncthing_no_peers cards:**
   replace each circle-with-up-arrow SVG with the cloud-with-X SVG from Change 3/5. Keep
   `class="icon color-amber"`.
4. **conflict card:** change `class="icon color-blue"` to `class="icon color-amber"`
   (icon SVG unchanged).
5. **syncthing_pending_upload card** (and/or the has_backup card): update the "when" text
   to reflect the new order — after a successful backup-on-exit the strip briefly shows
   **Game Save Up To Date**, then **Syncthing Preparing** while the hand-off confirms.

---

## Quality gates (run before each commit)

Frontend (substantive for this change), from repo root:
```
pnpm install --frozen-lockfile     # only if node_modules is stale
pnpm test                          # vitest run + tsc --noEmit
pnpm run build                     # rollup bundle must compile
```
Protocol compliance (CLAUDE.md §12 — unaffected here but required):
```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```
The pre-commit hook runs the core checks plus `scripts/check_tdd.sh`; the vitest test
additions satisfy TDD. Commit with Conventional Commits, preferring small atomic commits
(e.g., one per change area). Record a session log under
`docs/agent_conversations/` (CLAUDE.md §15).

---

## Verification

- `pnpm test` green (all existing + new assertions).
- `pnpm run build` succeeds.
- Open `docs/animated-status-icons-reference.html` in a browser and confirm: Downloading
  animates (arrow fills downward) and sits in the Animated section; the three "Local
  Backup Saved — …" warnings show the amber cloud-with-X; Save Conflict is amber.
- Do **not** attempt on-device (Steam Deck) verification. Hardware/user testing is
  deferred until after the dev release is pushed (see Finalize).

---

## Hand-off and review loop

Signal files and their exact locations (this is how completion and review state are
communicated):

- **Completion / round-done marker (you create):**
  `/tmp/sdh_ludusavi/animated-status-icons_finished` — an empty file.
- **Review notes (appear in the repo; you read and resolve):**
  `docs/review/animated-status-icons-review-*.md` (e.g. `-review-01.md`, `-review-02.md`).
  Each note lists items to address and ends with a trailer line of either
  `STATUS: CHANGES_REQUESTED` or `STATUS: APPROVED`.

Loop:

1. When implementation is complete and all quality gates pass, the session log is
   written, and your work is committed, create the empty marker
   `/tmp/sdh_ludusavi/animated-status-icons_finished`.
2. Then poll `docs/review/animated-status-icons-review-*.md` every ~30s.
3. When a review note you have not yet resolved appears:
   - Delete the `_finished` marker (work is resuming).
   - Address every item in the note (TDD where behavior changes; run all quality gates).
   - Commit your fixes, and commit the review-note file itself if it is not already
     committed (Conventional Commits, e.g. `docs(review): ...` and `fix(...)`).
   - Re-create the `/tmp/sdh_ludusavi/animated-status-icons_finished` marker.
   - Continue polling.
4. When a review note carrying `STATUS: APPROVED` is present and every item across all
   review notes is resolved, stop polling and proceed to Finalize.

Do **not** write a review of your own work, and do not create any files under
`docs/review/`. Only read the review notes placed there and resolve them.

---

## Finalize (only after an APPROVED review note, all items resolved)

1. Ensure all review-note files are committed.
2. Merge the feature branch into `dev` and delete the feature branch:
   ```
   git checkout dev
   git merge --no-ff feat/animated-status-icons
   git branch -d feat/animated-status-icons
   ```
3. Push `dev` to GitHub:
   ```
   git push origin dev
   ```
4. Request a dev release (base version `0.3.0` from `package.json`; GitHub Actions is the
   only publisher — do not tag or upload anything yourself):
   ```
   ./scripts/request_dev_release.sh 0.3.0
   ```
   This requires `gh` auth. If not authenticated, ask the user to run
   `! gh auth login` in the session. (cacheBuster bumping is for stable tagged releases,
   not dev prereleases, so it is not needed here.)
5. Leave the `_finished` marker in place as the final state.
