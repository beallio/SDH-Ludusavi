# Backup Browser Native UI — Review Round 2

**Branch:** `fix/backup-browser-native-ui` @ `dc022bd` (modal fix `c387ef3`)
**Reviewer gates run:** `pnpm run typecheck` ✅ · `pnpm run test:unit` ✅ (162 passed)

## Verdict: PASS

All round-1 findings are resolved correctly and the code review is clean.
Approved to finalize (proceed to plan §B6 endgame).

### Round-1 items — confirmed resolved

- **MUST-FIX #1/#2 (focus stops):** Each row is now a single focus stop — a
  presentational `Field` containing a `DialogButton` as the only interactive
  control. `ref={idx===0 ? firstRowRef : undefined}` and `preferredFocus={idx===0}`
  are on the **first DialogButton**, so `firstRowRef.current?.focus()` targets a
  real leaf control deterministically. The redundant outer `Focusable` (and the
  now-unused `Focusable` import) were removed.
- **SHOULD-FIX #3 (comment line-break):** `description` is now a `ReactNode` with an
  explicit `<br/>` before the comment.
- **SHOULD-FIX #4 (trailing whitespace):** cleared.
- **Item C (duplicate close):** footer `DialogButton` Close and `DialogFooter`
  import removed; the modal relies on the built-in top-right ✕.

### Confirmations

- Scope respected: only `BackupBrowserModal.tsx` + plan/review docs changed; the
  Force-Restore removal and backend are untouched.
- No hardcoded hex colors remain; the modal is fully native `@decky/ui`.
- Typecheck + 162 unit tests pass.

### Residual risk — NOT verified on-device (user elected to PASS on code review)

Record these in the session log and watch for them on the next Deck install of the
`v0.3.0-dev.*` build; open a fresh follow-up plan if either misbehaves:

- **A. Open-at-top:** confirm the modal mounts with focus on the **first** snapshot's
  Restore button (header + newest snapshot visible), not scrolled to the bottom.
- **B. `DialogBody` scroll:** `DialogBody` is a Steam-mapped div; confirm a **long**
  backup list scrolls and that focusing the first row scrolls the body to the top
  (not the whole modal). If it clips/doesn't scroll, wrap the list in an explicit
  `overflowY:auto` container and move `scrollRef` onto that element.
- **Trivial:** in `sizeText`, `.trim()` binds only to the second template literal, so
  a snapshot with `file_count` but null `size_bytes` keeps a trailing space
  (`"5 files "`). Cosmetic only (HTML collapses it); fix opportunistically if you
  touch the line again.

## Endgame (plan §B6) — go

1. Ensure this note (`backup_browser_native_ui_review_2.md`) and round-1 are committed.
2. Record session log at
   `docs/agent_conversations/2026-06-13_backup_browser_native_ui.json`.
3. Merge `fix/backup-browser-native-ui` into `dev` (`--no-ff`; use `UV_FROZEN=1
   git merge …` if the hook re-resolution fails).
4. Delete the branch and `rm -f /tmp/sdh_ludusavi/backup_browser_native_ui_finished`.
5. `git push origin dev`.
6. `./scripts/request_dev_release.sh 0.3.0` (needs `gh` auth; surface any failure).
7. Report the merge SHA and the dev-release dispatch result.
