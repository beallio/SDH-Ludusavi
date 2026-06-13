# Backup Browser: Distinct Cards + Open-at-Top + Blue Update Spinner

## Context

Two prior attempts (`docs/plans/backup_browser_ux_followups.md` and
`docs/plans/backup_browser_native_ui.md`, both merged to `dev`) failed to fix the
Backup Browser modal on-device. As of `dev` @ `b9727be` the modal is built from
native `@decky/ui` components (`DialogHeader`/`DialogBody`/`Field`/`DialogButton`),
but **both original problems remain open**, confirmed by the user on the Deck:

1. **It doesn't look the way the user wants.** Native flat `Field` rows are not the
   target. The user wants **distinct cards** (see layout spec below) — the card
   concept they liked originally, done with correct Steam surface colors.
2. **It still opens scrolled to the bottom** instead of the top. The
   imperative-`.focus()`-on-a-mapped-component approach did not work.

A third, unrelated UI fix is added this round:

3. **Update spinners aren't blue.** In `PluginUpdateSection.tsx`, the "Preparing…"
   install spinner is the default (white) color, and the **Check now** button shows
   no activity spinner at all. Both should show a **Steam-blue** spinner indicating
   activity, matching the existing `SpinnerButton` (`#1a9fff`).

This plan redoes the modal and fixes the spinner through the same
**plan → implement → review** loop. **On-device / user testing is explicitly
deferred until the dev release is pushed to GitHub** — the review loop is
code-review + gates only; PASS does not wait for Deck confirmation.

---

## Canonical tokens (use these EXACT strings everywhere)

| Thing | Value |
|---|---|
| `plan_name` | `backup_browser_cards_spinner` |
| Working branch | `fix/backup-browser-cards-spinner` (branched from **`dev`**, NOT `main`) |
| This plan doc | `docs/plans/backup_browser_cards_spinner.md` |
| **Completion marker** (implementer → reviewer) | `/tmp/sdh_ludusavi/backup_browser_cards_spinner_finished` |
| **Review notes** (reviewer → implementer) | `docs/review/backup_browser_cards_spinner_review_<n>.md` (`<n>` = 1, 2, 3…) |
| Approval signal | a review note whose body contains the literal token `PASS` |
| Dev-release base version | `0.3.0` → `./scripts/request_dev_release.sh 0.3.0` |

> **Branch from `dev`, not `main`:** `main` lacks the modal entirely (116 commits
> behind). Override the implementer skill's "branch from main" default.

## How to run this

This plan doc is delivered untracked in the working tree by the reviewer. Hand it to
a **fresh session** and tell it to **use the `implementer` skill**. That session is
"the implementer"; the reviewer session does the code review. They communicate only
through the marker file and the review-note files above.

---

# PART A — Technical work (for the implementer)

Files in scope:
- `src/components/modals/BackupBrowserModal.tsx` (items 1 & 2)
- `src/components/PluginUpdateSection.tsx` (item 3)
- Reuse `src/components/qam/SpinnerButton.tsx` (item 3 — do not duplicate it)

Out of scope: backend, other QAM sections, the Force-Restore removal, version bumps.

## A1. Modal visual — DISTINCT CARDS (user-approved layout)

Target (the user picked this mock):

```
Backups: <game>
----------------------------------
 +------------------------------+
 |  Jun 12, 2026  3:14 PM       |
 |  42 files  -  18.3 MB        |
 |                  [ Restore ] |
 +------------------------------+
 +------------------------------+   <- gap between cards
 |  Jun 10, 2026  9:02 AM       |
 ...
```

Each snapshot is a **visually distinct card**:

- A styled container per snapshot: `borderRadius: 8px`, internal `padding: 12px 14px`,
  and a **subtle raised background that is DISTINCT from the Restore button fill** so
  the button reads as sitting *on* the card (the previous attempt failed because the
  card used the same `#43464c` as the button and they blended). Suggested starting
  values — the user will refine via review:
  - card background: `rgba(255, 255, 255, 0.05)` (subtle elevation over the modal bg),
    optionally a hairline border `1px solid rgba(255, 255, 255, 0.08)` for definition.
  - the **Restore** control stays a native `DialogButton` (keeps Steam's button fill),
    right-aligned within the card.
- Cards stacked in a flex column with `gap: 10px`.
- Card contents: line 1 = bold timestamp (`formatTimestamp(b.when)`) + `(Locked)` when
  `b.locked`; line 2 = `<file_count> files  ·  <size>` (`formatBytes(b.size_bytes)`);
  optional line = `Comment: <b.comment>`; then the right-aligned `DialogButton`.
- Keep `DialogHeader` for the "Backups: {gameName}" title.
- Preserve ALL existing data wiring and behavior: props
  (`BackupBrowserModalProps`), the `listBackupsCall` fetch effect + `mounted` guard,
  the summary line (path / total size / N snapshots), the empty + error states, and
  the `onRestore` → `ConfirmModal` confirm flow. Only markup/styling changes.

Cards are styled `<div>`s by necessity (Steam has no "card" primitive); that is fine
and is what the user wants. Do not reintroduce arbitrary opaque hex like `#212224` /
`#2c2e2f` for large surfaces — prefer the translucent-white-over-dark approach above
so it tracks the Steam theme.

## A2. Open-at-top — use a REAL bounded scroll container (proven pattern)

Root cause of the persistent failure: the modal relied on `DialogBody`'s implicit
scrolling and on `.focus()` against a **mapped Steam component ref** (`DialogButton`),
which does not forward to a focusable DOM node — so focus/scroll never reset.

Use the pattern that already works in this repo — `src/components/LogModal.tsx`
scrolls a long modal body with an explicit bounded `<div>`:

1. Render the scrollable list region as a **real div with a ref and bounded height**:
   ```tsx
   <div
     ref={scrollRef}
     style={{ maxHeight: "60vh", overflowY: "auto", display: "flex",
              flexDirection: "column", gap: "10px", padding: "16px" }}
   >
     {/* summary line + cards */}
   </div>
   ```
   `scrollRef` is `useRef<HTMLDivElement | null>(null)` on a **plain div** (the ref
   is guaranteed to point at the real scroll viewport — unlike `DialogBody`).
2. Once content settles, reset scroll to the top inside a `requestAnimationFrame`:
   ```tsx
   useEffect(() => {
     if (loading) return;
     requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 0 }));
   }, [loading, error, listResult]);
   ```
   Because `scrollRef` is a real div, `scrollTo({ top: 0 })` deterministically shows
   the top (header + newest snapshot).
3. Put `preferredFocus={idx === 0}` on the **first card's `DialogButton`** so gamepad
   focus starts at the top and Steam does not select a lower element and scroll down.
   (`DialogButton` accepts `preferredFocus` via `FooterLegendProps`.)
4. **Do NOT** call `.focus()` on a `DialogButton`/`Field`/`DialogBody` ref — that is
   what failed. Rely on the bounded-div `scrollTo(0)` + `preferredFocus`. If a future
   review round still reports bottom-open, the next escalation (note it, don't do it
   pre-emptively) is to wrap the first card in a real `Focusable` and call `.focus()`
   on *that* (Focusable forwards its ref to a real div).

Keep the built-in close ✕ (`bHideBuiltInClose={false}`); the footer Close stays
removed.

> Reference: `src/utils/steam.ts` has `findScrollableParent` / `resetQuickAccessScroll`
> (both `requestAnimationFrame`-based) if you want a helper, but a direct `scrollRef`
> on the bounded div is simplest — don't add new shared utilities.

## A3. Blue update spinners (`src/components/PluginUpdateSection.tsx`)

The repo's canonical activity spinner is in `src/components/qam/SpinnerButton.tsx`:
`<Spinner style={{ width: "18px", height: "18px", color: "#1a9fff" }} />` — Steam blue
via the SVG `color`. Apply the same `#1a9fff` to the update flows:

1. **"Preparing…" install spinner** (currently `~line 240`, `<Spinner size="small" />`
   with no color): make it blue, e.g. `style={{ color: "#1a9fff" }}` (keep the
   existing `spinnerSlotStyle` wrapper that prevents layout shift). Result: the
   spinner shown beside "Preparing…" / "Waiting for Decky…" is blue.
2. **"Check now" activity spinner** (currently `~lines 266–275`): while `isChecking`,
   the button shows only a static `<IoMdRefresh />` and is disabled — no spinner.
   Show a **blue spinner indicating activity**: when `isChecking`, render
   `<Spinner style={{ width: "16px", height: "16px", color: "#1a9fff" }} />` in place
   of `<IoMdRefresh />` (keep the "Check now" label).
3. Also color the existing **"Checking…" status spinner** (currently `~line 133`,
   `<Spinner size="small" />`) blue for consistency.

Prefer reusing the `SpinnerButton` component if it drops in cleanly; if the install
button's custom "Preparing/Waiting" label logic makes that awkward, the minimal
change above (add `color: "#1a9fff"`, swap the Check-now icon for a blue Spinner while
checking) is acceptable. Either way, the visible spinners must be `#1a9fff`.

## A4. Gates (run via project tooling before EACH commit)

```
pnpm run typecheck      # tsc --noEmit
pnpm run test:unit      # vitest run (no React component rig; proves compile + units)
```
The pre-commit hook also runs the backend suite + `pnpm run verify` + `check_tdd.sh`.
If a commit/merge fails with "requirements are unsatisfiable" (a vendored dep newer
than this machine's global 7-day `uv` cutoff), prefix git with `UV_FROZEN=1`. Do not
edit hook scripts.

**No on-device testing happens during the loop** — see the deferral note in §B6.

---

# PART B — Coordination protocol (for the implementer)

## B1. Setup
1. `git status` — this plan doc (`docs/plans/backup_browser_cards_spinner.md`) is
   delivered untracked by the reviewer; that is expected. Run the implementer skill's
   discovery + emit `AGENT_PROTOCOL_HANDSHAKE`.
2. `git checkout dev && git pull`, then
   `git checkout -b fix/backup-browser-cards-spinner dev`.
3. Commit the plan doc: `docs(plans): add backup browser cards + spinner plan`.

## B2. Implement (atomic conventional commits)
Suggested commits:
- `fix(backup-browser): render snapshots as distinct cards` (A1)
- `fix(backup-browser): open at top via bounded scroll container` (A2)
- `fix(update): show Steam-blue activity spinners` (A3)

Run the A4 gates before each commit.

## B3. Signal completion (how the implementer tells the reviewer it's done)
After the round is committed and gates pass:
```
mkdir -p /tmp/sdh_ludusavi
touch /tmp/sdh_ludusavi/backup_browser_cards_spinner_finished
```
Empty file; existence + fresh mtime is the signal. **Re-`touch` it at the end of
EVERY round** so the reviewer's mtime-based watcher re-fires.

## B4. Wait for review notes (how the implementer knows the review is done)
The reviewer writes findings into the repo at
`docs/review/backup_browser_cards_spinner_review_<n>.md`. **Own the wait loop
yourself** with the `Monitor` tool (never delegate to a background subagent — that
pattern fails). After touching the marker for round `N`, poll ~60s for the
next-numbered note:
```
test -f docs/review/backup_browser_cards_spinner_review_<N>.md
```
(`<N>` = 1, then 2, …). When it appears, read it.

## B5. Process each review round, then loop
1. Address **every** item in the note as atomic commits; run A4 gates each time.
2. Commit the review-note file if it isn't already
   (`docs(review): record backup browser cards + spinner review round <n>`).
3. Re-`touch /tmp/sdh_ludusavi/backup_browser_cards_spinner_finished`.
4. Return to B4 and wait for the next-numbered note.

Repeat until a review note's body contains the literal token **`PASS`** → go to B6.

## B6. Endgame (only after a review note contains `PASS`)
> **On-device / user testing is deferred to AFTER this step.** PASS is granted on
> code review + green gates alone; the implementer must NOT wait for Steam Deck
> confirmation. The user verifies on the Deck only once the dev release is on GitHub.

In order:
1. Ensure the approving review note (and all prior ones) are committed on the branch.
2. Record session log at
   `docs/agent_conversations/<YYYY-MM-DD>_backup_browser_cards_spinner.json`
   (date, objective, files modified, tests added, design decisions, results); commit it.
3. Merge into `dev`:
   ```
   git checkout dev
   git pull --ff-only
   git merge --no-ff fix/backup-browser-cards-spinner
   ```
   (Use `UV_FROZEN=1 git merge …` if hook re-resolution fails.)
4. Clean up:
   ```
   git branch -d fix/backup-browser-cards-spinner
   rm -f /tmp/sdh_ludusavi/backup_browser_cards_spinner_finished
   ```
5. Push: `git push origin dev`.
6. Dev release (workflow dispatch — NOT a stable tag/release):
   `./scripts/request_dev_release.sh 0.3.0` (needs `gh` auth; surface any failure).
7. Report the merge SHA + dev-release dispatch result. Note to the user that the
   `v0.3.0-dev.*` build is the artifact to test the three fixes on the Deck.

---

## Reviewer side (for reference — implementer does not do these)
- Watch `/tmp/sdh_ludusavi/backup_browser_cards_spinner_finished` (`Monitor`, ~60s,
  mtime cutoff). On fire, code-review the branch diff + run gates, then write
  `docs/review/backup_browser_cards_spinner_review_<n>.md`. When satisfied (code +
  gates only — no Deck check), write a note containing `PASS`.

## Definition of Done
- [ ] Snapshots render as distinct cards (button distinct from card surface).
- [ ] Modal opens at top via a bounded `scrollRef` div + `scrollTo(0)` +
      `preferredFocus` on the first card button (no `.focus()` on mapped refs).
- [ ] "Preparing…", "Check now" (while checking), and "Checking…" spinners are
      `#1a9fff` blue.
- [ ] `pnpm run typecheck` + `pnpm run test:unit` pass; backend gates pass via hook.
- [ ] Session log recorded; review notes committed.
- [ ] Branch merged to `dev`, branch deleted, marker removed; `dev` pushed;
      dev release dispatched. On-device testing deferred to the published build.
