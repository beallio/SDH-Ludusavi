# Backup Browser: Native Steam UI + Open-at-Top (Redo)

## Context

The first follow-up effort (`docs/plans/backup_browser_ux_followups.md`, commits
`de7381b` and `996128b`, merged to `dev`) tried to fix three Backup Browser modal
issues. Two are **still broken** as verified on-device:

1. **Open-at-bottom is NOT fixed.** The modal still mounts scrolled to the footer.
2. **"The UI" is NOT fixed.** The card-color tweak (`#43464c`) didn't make the
   modal look right. The decision (confirmed with the user) is to **rebuild the
   modal with native Steam / `@decky/ui` components** instead of hand-rolled
   `<div>`s with hardcoded colors, so it matches the rest of the QAM.

The Force-Restore removal (`996128b`) is fine and is **out of scope** — do not revert it.

This plan redoes the work and runs it through a **plan → implement → review** loop.
An implementer agent (separate session) does the work, signals completion via a
marker file, then waits for review notes the reviewer writes into the repo, fixing
each round until the reviewer approves. Best-effort visual fix first pass; specifics
get refined through review rounds (the only true test surface is the Steam Deck).

---

## Canonical tokens (use these EXACT strings everywhere)

| Thing | Value |
|---|---|
| `plan_name` | `backup_browser_native_ui` |
| Working branch | `fix/backup-browser-native-ui` (branched from **`dev`**, NOT `main`) |
| This plan doc | `docs/plans/backup_browser_native_ui.md` |
| **Completion marker** (implementer → reviewer) | `/tmp/sdh_ludusavi/backup_browser_native_ui_finished` |
| **Review notes** (reviewer → implementer) | `docs/review/backup_browser_native_ui_review_<n>.md` (`<n>` = 1, 2, 3…) |
| Approval signal | a review note whose body contains the literal token `PASS` |
| Dev-release base version | `0.3.0` → `./scripts/request_dev_release.sh 0.3.0` |

> **Why branch from `dev`, not `main`:** `main` is 116 commits behind `dev` and does
> **not** contain `BackupBrowserModal.tsx` at all. The implementer skill's default
> ("branch from main") is wrong for this repo; this repo's convention is feature
> branch → merge into `dev`. Override the skill default and branch from `dev`.

---

## How to run this

This plan doc is delivered in the working tree by the reviewer. Hand it to a **fresh
session** and tell it to **use the `implementer` skill**. That session is "the
implementer." The reviewer session does the on-device review. The two communicate
only through the marker file and the review-note files above.

---

# PART A — Technical work (for the implementer)

## A0. Root-cause of the open-at-bottom bug (read before coding)

In Steam's gamepad UI, **focus drives scroll**: whatever element the gamepad
focus engine selects gets `scrollIntoView`'d. When the modal first mounts,
`loading === true`, so the body shows only "Loading backups…" and the **only**
focusable elements are the footer **Close** button (bottom) and the built-in
close icon. The focus engine commits initial focus to the footer Close button and
scrolls it into view → the modal opens at the bottom.

The previous fix's `preferredFocus={idx === 0}` lives on a `Focusable` that only
renders **after** `loading` flips to `false`. `preferredFocus` is a mount-time hint
for the navigation tree; re-renders don't re-trigger it, so it's too late. The
one-shot `scrollRef.scrollTo({top:0})` runs but focus still sits on the off-screen
footer, so the next d-pad input scrolls back / Steam re-snaps.

**Fix principle:** once content settles, **imperatively move gamepad focus to the
top** (the first snapshot row). Do not rely on `preferredFocus` alone or on
`scrollTo` alone.

## A1. Rebuild `src/components/modals/BackupBrowserModal.tsx` with native components

This is the only frontend file that changes (plus the session log + review notes).
Keep the component's props (`BackupBrowserModalProps`), the `listBackupsCall` fetch
effect, the `mounted` guard, and the `onRestore` confirm flow exactly as they are.
Replace only the **rendered markup and styling**.

Reference patterns already in the repo / `@decky/ui` (do NOT invent new APIs):

- **In-repo reference modal:** `src/components/modals/ConflictResolutionModal.tsx`
  shows the native pattern — a Steam modal wrapper with `@decky/ui` children and
  `ButtonItem layout="below"`, no hardcoded colors.
- **In-repo native section pattern:** `src/components/qam/GameSettingsSection.tsx`
  uses `PanelSection`, `PanelSectionRow`, `Field`, `ButtonItem`.
- **`@decky/ui` Dialog primitives** (verified in
  `node_modules/@decky/ui/dist/components/Dialog.d.ts`): `DialogHeader`,
  `DialogBody`, `DialogBodyText`, `DialogFooter`, `DialogControlsSection`,
  `DialogButton`, `DialogButtonPrimary`/`Secondary`. All accept `style`/`className`
  and provide native Steam theming and focus rings.
- **`Field`** (`Field.d.ts`): props `label`, `description`, `bottomSeparator`
  (`'standard'|'thick'|'none'`), `padding`, `highlightOnFocus`, `focusable`,
  `childrenLayout`, plus `RefAttributes<HTMLDivElement>` (so it accepts a `ref`).
- **`Focusable`** (`Focusable.d.ts`): accepts a `ref` (`RefAttributes<HTMLDivElement>`),
  `preferredFocus`, `noFocusRing`, `onActivate`.

**Target structure** (use native components; remove all hardcoded hex colors like
`#212224`, `#43464c`, `#333`, `rgba(...)`):

- Keep the outer `ModalRoot onCancel={closeModal}`.
- Header → `DialogHeader` ("Backups: {gameName}").
- Body (scrollable region) → `DialogBody`.
  - Loading state → existing "Loading backups…" text, or `@decky/ui` `Spinner`
    if it reads cleanly (optional, best-effort).
  - Error state → keep the error text (a `DialogBodyText` is fine).
  - Summary line (path / total size / snapshot count) → `DialogBodyText` or a
    `Field` with `label`/`description`.
  - Snapshot list → one **`Field`** per snapshot (this replaces the raw card div):
    - `label` = formatted timestamp (+ "(Locked)" when `b.locked`).
    - `description` = file count + size (+ comment when present).
    - child = `DialogButton` "Restore" wired to the existing `onRestore(b.id, …)`.
    - `Field` gives native row chrome, separators, and focus highlighting — no
      manual background colors needed.
- Footer → `DialogFooter` with the existing Close `ButtonItem`/`DialogButton`.

Preserve all existing data wiring: `formatTimestamp(b.when)`, `formatBytes(...)`,
`b.file_count`, `b.size_bytes`, `b.comment`, `b.locked`, `listResult.backup_path`,
`listResult.total_size_bytes`, `listResult.backups`.

## A2. Open-at-top: imperative focus once content settles

- Attach a `ref` to the **first** snapshot row (`Field` or a wrapping `Focusable`),
  e.g. `const firstRowRef = useRef<HTMLDivElement | null>(null)` and
  `ref={idx === 0 ? firstRowRef : undefined}`.
- Replace the existing `[loading]` scroll effect with one that, once
  `!loading && !error && (listResult?.backups.length ?? 0) > 0`, schedules an
  imperative focus on the next frame(s):
  ```ts
  useEffect(() => {
    if (loading || error) return;
    if (!listResult?.backups.length) return;
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => firstRowRef.current?.focus())
    );
    return () => cancelAnimationFrame(id);
  }, [loading, error, listResult]);
  ```
  The double `requestAnimationFrame` lets Steam register the newly-rendered
  focusable nodes before we focus; `.focus()` moves gamepad focus to the top row,
  and Steam scrolls it into view (top).
- Keep `preferredFocus={idx === 0}` on the first row as a harmless secondary hint.
- **Fallback for empty/error states** (no row to focus): keep a `scrollRef` on the
  `DialogBody` scroll container and call `scrollRef.current?.scrollTo({ top: 0 })`
  in that case so those short states still render from the top. The repo already
  has a scroll-reset reference pattern in `src/utils/steam.ts`
  (`findScrollableParent` / `resetQuickAccessScroll`, both using
  `requestAnimationFrame`) — mirror that style; reuse `findScrollableParent` if it
  helps, but do not add new shared utilities unless necessary.

> If `.focus()` on the `Field`/`Focusable` ref proves unreliable on-device, the
> documented next step (for a later review round) is to wrap the first row in an
> explicit `Focusable` and focus that, or to focus via the scroll container's first
> focusable child. Note this as a known follow-up rather than guessing further now.

## A3. Out of scope (do NOT touch)

- `src/components/qam/GameSettingsSection.tsx`, `LudusaviContent.tsx`,
  `NotificationSettingsSection.tsx` — the Force-Restore removal is already correct.
- Backend (`py_modules/`), the `force_restore` / `restore_backup_version` RPCs.
- Version bumps in `package.json` / `plugin.json` (this is a dev release, not a
  stable release — see endgame).

## A4. Gates (run via `./run.sh`; all must pass before each commit)

Frontend (the changed surface):
```
pnpm run test:unit      # vitest run
pnpm run typecheck      # tsc --noEmit
```
The pre-commit hook (`scripts/pre_commit.sh`) additionally runs the full backend
suite (`ruff`, `ty`, `pytest`), `pnpm run verify`, and `check_tdd.sh` on every
commit, so a clean commit proves the whole gate set.

**Testing reality:** this is gamepad-focus + visual behavior with **no React
component test rig** in the repo (consistent with the original feature). `vitest` +
`tsc` only prove it compiles and existing units still pass. The real verification is
**on the Steam Deck** — which is exactly what the review loop is for. The post-commit
hook (`scripts/post_commit.sh`) auto-packages the plugin and `scp`s it to the
`steamdeck` host when reachable, so each commit delivers a fresh local build for the
reviewer to inspect between rounds.

**Contingency — `uv` resolution failures on commit:** if a commit/merge fails with
"requirements are unsatisfiable" (a vendored dep newer than this machine's global
7-day `uv` cutoff), prefix git with `UV_FROZEN=1` (e.g. `UV_FROZEN=1 git commit …`,
`UV_FROZEN=1 git merge …`). Do **not** edit the hook scripts.

---

# PART B — Coordination protocol (for the implementer)

## B1. Setup

1. Confirm the tree state (`git status`). This plan doc
   (`docs/plans/backup_browser_native_ui.md`) is delivered untracked in the working
   tree by the reviewer — that is expected; it is not unrelated user work.
   Run the `implementer` skill's environment discovery and emit the
   `AGENT_PROTOCOL_HANDSHAKE` (CLAUDE.md §1).
2. `git checkout dev && git pull` (be current), then
   `git checkout -b fix/backup-browser-native-ui dev`. The untracked plan doc
   carries over to the new branch.
3. Commit the plan doc on the branch:
   `docs(plans): add backup browser native UI redo plan`.

## B2. Implement (atomic conventional commits)

Implement Part A in small commits, e.g.:
- `fix(backup-browser): rebuild modal with native @decky/ui components` (A1)
- `fix(backup-browser): focus first snapshot row so modal opens at top` (A2)

Run the A4 gates before each commit.

## B3. Signal completion (THIS is how the implementer tells the reviewer it's done)

After the implementation round is committed and gates pass, create the **empty
marker file** (this is the completion signal):
```
mkdir -p /tmp/sdh_ludusavi
touch /tmp/sdh_ludusavi/backup_browser_native_ui_finished
```
The file is **empty**; its existence + fresh mtime is the signal. Re-`touch` it
(updating its mtime) at the end of **every** round so the reviewer's mtime-based
watcher fires again on subsequent rounds.

## B4. Wait for review notes (THIS is how the implementer knows the review is done)

The reviewer writes findings into the **repo** at
`docs/review/backup_browser_native_ui_review_<n>.md` (round 1 = `_review_1.md`, etc.).
A review note appearing in the project dir is the trigger to resume work.

The implementer **owns the wait loop itself** — use the `Monitor` tool with an
until-condition; do **not** delegate waiting to a background subagent (that pattern
failed repeatedly: subagents arm the watcher then end their turn and the signal
never propagates). After touching the marker for round `N`, watch for the
**next-numbered** review note:
```
test -f docs/review/backup_browser_native_ui_review_<N>.md
```
(`<N>` = 1 on the first wait, 2 on the second, …) Poll ~60s. When the file appears,
read it.

## B5. Process each review round, then loop

For each new review note:
1. Address **every** item in it, as atomic conventional commits, running A4 gates
   on each.
2. Ensure the review-note file itself is **committed** to the branch if it isn't
   already (`docs(review): record backup browser native UI review round <n>`).
3. Re-`touch /tmp/sdh_ludusavi/backup_browser_native_ui_finished` (refresh mtime).
4. Return to B4 and wait for the next-numbered review note.

Repeat until a review note's body contains the literal token **`PASS`** (the
reviewer's approval). A note containing `PASS` means no outstanding items → go to B6.

## B6. Endgame (only after a review note contains `PASS`)

Run these steps in order:

1. **Commit the review note if not already committed** — ensure the approving
   `docs/review/backup_browser_native_ui_review_<n>.md` (and any prior ones) are
   committed on the branch.
2. **Record the session log** at
   `docs/agent_conversations/<YYYY-MM-DD>_backup_browser_native_ui.json`
   (date, objective, files modified, tests added, design decisions, results) and
   commit it (`docs(agent): record backup browser native UI session`).
3. **Merge the working branch into `dev`:**
   ```
   git checkout dev
   git pull --ff-only        # be current with origin/dev
   git merge --no-ff fix/backup-browser-native-ui
   ```
   (Use `UV_FROZEN=1 git merge …` if the hook re-resolution fails — see A4.)
4. **Clean up:**
   ```
   git branch -d fix/backup-browser-native-ui
   rm -f /tmp/sdh_ludusavi/backup_browser_native_ui_finished
   ```
5. **Push `dev` to GitHub:** `git push origin dev`.
6. **Request a new dev release** (workflow dispatch — NOT a stable tag/release):
   ```
   ./scripts/request_dev_release.sh 0.3.0
   ```
   This dispatches `dev-release.yml`, producing a `v0.3.0-dev.<shortsha>` prerelease.
   Do **not** push tags or run the stable `release.yml` (CLAUDE.md §14).
7. Report completion to the user with the merge SHA and the dev-release dispatch
   confirmation.

---

## Reviewer side (for reference — the implementer does not do these)

- Watch `/tmp/sdh_ludusavi/backup_browser_native_ui_finished` (`Monitor`, ~60s,
  mtime cutoff so stale markers don't trigger). When it fires, review the branch
  diff and the on-device build, then write
  `docs/review/backup_browser_native_ui_review_<n>.md` in the repo.
- When satisfied, write a review note whose body contains `PASS`.

---

## Definition of Done (CLAUDE.md §16)

- [ ] Modal rebuilt with native `@decky/ui` components; no hardcoded hex colors.
- [ ] Modal opens focused at the top (first snapshot row), verified on the Deck.
- [ ] All review rounds cleared; approving note (`PASS`) committed.
- [ ] `pnpm run test:unit` + `pnpm run typecheck` pass; backend gates pass via hook.
- [ ] Session log recorded in `docs/agent_conversations/`.
- [ ] Branch merged into `dev`, branch deleted, marker removed.
- [ ] `dev` pushed to `origin`; dev release dispatched (`request_dev_release.sh 0.3.0`).
