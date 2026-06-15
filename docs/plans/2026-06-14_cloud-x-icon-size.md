# Plan: Enlarge the "X" in the cloud-with-X status icon (cloud-x-icon-size)

## Context

The three "saved locally, Syncthing didn't finish" warning statuses —
`syncthing_unavailable` ("Local Backup Saved — Syncthing Unavailable"),
`syncthing_folder_not_found` ("Local Backup Saved — Path Not Shared"), and
`syncthing_no_peers` ("Local Backup Saved — No Syncthing Peers Online") — render an amber
cloud icon overlaid with a dark "X". The X currently reads as too small on the 18px icon.

Goal: make the X noticeably larger (and proportionally bolder) so it's clearly legible,
keeping it centered within the cloud, then update the visual reference HTML to match.
Everything else about the icon (amber color, cloud body shape, the three statuses sharing
one identical icon string) stays the same.

This is a **frontend-only** change (one SVG string in one TS file, plus its test
assertion, plus three identical copies in one HTML doc). No Python (`py_modules/`) changes.

**Slug used throughout this plan:** `cloud-x-icon-size`

The base branch `dev` already contains the cloud-with-X icon (merged in `0b15b33`), so it
is the correct starting point.

---

## Working setup (do this first)

1. Use the **implementer** skill for this work.
2. Output the `AGENT_PROTOCOL_HANDSHAKE` (CLAUDE.md §1) after verifying filesystem and
   dependency state. Caches/venv stay under `/tmp/sdh_ludusavi/` (see `run.sh`).
3. Branch off `dev`:
   ```
   git checkout dev
   git pull --ff-only
   git checkout -b feat/cloud-x-icon-size
   ```
4. This plan already lives at `docs/plans/2026-06-14_cloud-x-icon-size.md`; commit it as
   the first commit on the branch.
5. Follow strict TDD (RED → GREEN). The behavior change is a constant in one SVG string;
   the test that pins it is in `src/surfaces/autoSyncStatusSurface.test.ts`.

---

## The change

The icon is a single string returned for all three warning statuses from one branch in
`iconSvgForAutoSyncStatus(...)`. The cloud body path stays unchanged; only the second
`<path>` (the X) changes.

Current X: two diagonal strokes spanning an 84×84 box centered at (256, 292),
`stroke-width="34"`. New X: a 120×120 box centered at the same point (≈1.43× larger),
`stroke-width="40"` (bumped so the thicker, larger X stays proportional). The X stays
well inside the cloud body (cloud spans roughly x16–496, y96–416; the new X spans
x196–316, y232–352).

### Edit 1 — renderer

**File:** `src/surfaces/autoSyncStatusRenderer.tsx` (the cloud-with-X branch, ~line 176).

Replace exactly this substring:
```
<path d="M214 250 298 334M298 250 214 334" fill="none" stroke="#0b151f" stroke-width="34" stroke-linecap="round"/>
```
with:
```
<path d="M196 232 316 352M316 232 196 352" fill="none" stroke="#0b151f" stroke-width="40" stroke-linecap="round"/>
```
Leave the rest of the SVG (cloud body path, `viewBox`, `fill="currentColor"`) untouched.
All three statuses share this one returned string, so this single edit covers all three.

### Edit 2 — test (do this first, RED)

**File:** `src/surfaces/autoSyncStatusSurface.test.ts` (~line 134, in the "uses the amber
warning style and cloud-with-X icon treatment" test).

Change:
```ts
expect(icon).toContain("M214 250 298 334");
```
to:
```ts
expect(icon).toContain("M196 232 316 352");
```
Update this assertion before Edit 1 and confirm it fails against the current code (RED),
then apply Edit 1 to make it pass (GREEN). The sibling assertions in the same test
(`toContain("M403.002 217.001")`, `not.toContain('r="8.8"')`, and the equality checks that
all three statuses return the same icon) are unaffected and must stay green.

### Edit 3 — reference HTML

**File:** `docs/animated-status-icons-reference.html`.

There are **three identical** occurrences of the X path (in the `syncthing_unavailable`,
`syncthing_folder_not_found`, and `syncthing_no_peers` cards). Replace every occurrence of:
```
<path d="M214 250 298 334M298 250 214 334" fill="none" stroke="#0b151f" stroke-width="34" stroke-linecap="round"/>
```
with:
```
<path d="M196 232 316 352M316 232 196 352" fill="none" stroke="#0b151f" stroke-width="40" stroke-linecap="round"/>
```
(A global replace of that exact substring updates all three cards.) Make no other changes
to the HTML.

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
Commit with Conventional Commits (e.g. `fix(ui): enlarge the X in the cloud-unavailable
status icon`), preferring small atomic commits. Record a session log under
`docs/agent_conversations/` (CLAUDE.md §15).

---

## Verification

- `pnpm test` green (the updated X-path assertion plus all existing assertions).
- `pnpm run build` succeeds.
- Open `docs/animated-status-icons-reference.html` in a browser and confirm the X in the
  three "Local Backup Saved — …" warning cards is visibly larger and well-centered in the
  amber cloud.
- Do **not** attempt on-device (Steam Deck) verification. Hardware/user testing is
  deferred until after the dev release is pushed (see Finalize).

---

## Hand-off and review loop

Signal files and their exact locations:

- **Completion / round-done marker (you create):**
  `/tmp/sdh_ludusavi/cloud-x-icon-size_finished` — an empty file.
- **Review notes (appear in the repo; you read and resolve):**
  `docs/review/cloud-x-icon-size-review-*.md` (e.g. `-review-01.md`, `-review-02.md`).
  Each note lists items to address and ends with a trailer line of either
  `STATUS: CHANGES_REQUESTED` or `STATUS: APPROVED`.

Loop:

1. When implementation is complete and all quality gates pass, the session log is
   written, and your work is committed, create the empty marker
   `/tmp/sdh_ludusavi/cloud-x-icon-size_finished`.
2. Then poll `docs/review/cloud-x-icon-size-review-*.md` every ~30s.
3. When a review note you have not yet resolved appears:
   - Delete the `_finished` marker (work is resuming).
   - Address every item in the note (TDD where behavior changes; run all quality gates).
   - Commit your fixes, and commit the review-note file itself if it is not already
     committed (Conventional Commits, e.g. `docs(review): ...` and `fix(...)`).
   - Re-create the `/tmp/sdh_ludusavi/cloud-x-icon-size_finished` marker.
   - Continue polling.
4. When a review note carrying `STATUS: APPROVED` is present and every item across all
   review notes is resolved, stop polling and proceed to Finalize.

Review notes are a permanent record: **commit them, never delete them.** "Resolving" a
review note means addressing its items in code and committing the note as-is — not
removing it. Do **not** write a review of your own work, and do not create any files under
`docs/review/`; only read the review notes placed there and resolve them.

---

## Finalize (only after an APPROVED review note, all items resolved)

1. Ensure all `cloud-x-icon-size-review-*.md` files are committed.
2. Merge the feature branch into `dev` and delete the feature branch:
   ```
   git checkout dev
   git merge --no-ff feat/cloud-x-icon-size
   git branch -d feat/cloud-x-icon-size
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
