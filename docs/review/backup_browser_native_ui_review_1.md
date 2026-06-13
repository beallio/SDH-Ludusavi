# Backup Browser Native UI — Review Round 1

**Branch:** `fix/backup-browser-native-ui` @ `a39510b`
**Reviewer gates run:** `pnpm run typecheck` ✅ · `pnpm run test:unit` ✅ (162 passed)
**Verdict:** CHANGES REQUESTED (do **not** finalize — this note does not contain the approval token)

The native-component rebuild is the right direction and the file is much cleaner.
But the per-row focus structure has a concrete defect that undermines the #1 goal of
this whole effort (open-at-top), plus a contradictory interaction model. Fix the
MUST-FIX items, then re-signal. Items are labeled so you can triage.

---

## MUST-FIX

### 1. Each row has TWO focus stops and an indeterminate focus target

Current structure per snapshot (lines 126–142):

```tsx
<Focusable ref={idx === 0 ? firstRowRef : undefined} preferredFocus={idx === 0}>
  <Field focusable={true} label={title} description={desc} bottomSeparator="standard">
    <DialogButton onClick={() => onRestore(b.id, timestampStr)}>Restore</DialogButton>
  </Field>
</Focusable>
```

This nests three focus-aware elements: an outer `Focusable`, a `Field focusable={true}`,
and a `DialogButton`. In Steam's gamepad nav, a `Focusable` that **contains focusable
descendants becomes a navigation *container*, not a leaf focus stop** — so:

- The row exposes **two** leaf stops (the focusable `Field` *and* the `DialogButton`),
  giving clunky double-stops as you d-pad down the list.
- `firstRowRef` is on the **outer container**. `firstRowRef.current?.focus()`
  (line 52) focuses a *container*, which delegates to an unspecified child rather
  than landing deterministically. That makes the open-at-top behavior unreliable —
  which is the exact bug this branch exists to fix.

**Fix — collapse to ONE focus stop per row, with the ref on the actual control.**
Recommended (keeps the Restore button as the interactive element):

```tsx
{listResult.backups.map((b, idx) => {
  const timestampStr = formatTimestamp(b.when);
  const title = `${timestampStr}${b.locked ? " (Locked)" : ""}`;
  return (
    <Field
      key={b.id}
      label={title}
      description={/* see item 3 */}
      bottomSeparator="standard"
      // NOTE: no `focusable` here — the Field is presentational; the
      // DialogButton below is the single focus stop for the row.
    >
      <DialogButton
        ref={idx === 0 ? firstRowRef : undefined}
        preferredFocus={idx === 0}
        onClick={() => onRestore(b.id, timestampStr)}
      >
        Restore
      </DialogButton>
    </Field>
  );
})}
```

- `DialogButton` accepts both `ref` (`DialogCommonProps` extends
  `RefAttributes<HTMLDivElement>`) and `preferredFocus`/nav props
  (`DialogButtonProps extends FooterLegendProps`), verified in
  `node_modules/@decky/ui/dist/components/Dialog.d.ts` — so this typechecks.
- Drop the outer `<Focusable>` wrapper and its import if it's no longer used
  anywhere in the file.
- Update the focus effect (line 52) to `firstRowRef.current?.focus()` — unchanged
  call, but now it targets the first Restore button directly, so Steam scrolls
  *that* element into view (top) deterministically.

> If you'd rather make the **whole row** activate a restore (also fine, also one
> stop): instead make the `Field focusable` with
> `onActivate={() => onRestore(b.id, timestampStr)}`, **remove** the `DialogButton`,
> and put `ref`/`preferredFocus` on the first `Field`. Do **one** model — not both.

### 2. `Field focusable={true}` + a `DialogButton` child is contradictory

This is the root of #1's duplication: a focusable Field is itself an activatable
row, and the `DialogButton` is a second activatable control inside it. Resolve by
picking a single interaction model per the fix above (presentational Field +
DialogButton, OR activatable Field + no button).

---

## SHOULD-FIX (quality / visual)

### 3. The `Comment:` newline won't render as a line break

Lines 121–124 build `desc` as a plain string with `desc += \`\nComment: ${b.comment}\``.
A `\n` inside a string passed to `Field`'s `description` collapses in HTML, so the
comment runs inline right after the size. Pass a `ReactNode` instead, e.g.:

```tsx
const sizeText =
  `${b.file_count !== null ? `${b.file_count} files ` : ""}` +
  `${b.size_bytes !== null ? formatBytes(b.size_bytes) : ""}`.trim();
const description = (
  <>
    {sizeText}
    {b.comment && (<><br />Comment: {b.comment}</>)}
  </>
);
```

(Also trims the trailing space left by `"... files "`.)

### 4. Trailing whitespace

Line 120 (the blank line after `const title = ...`) carries trailing whitespace.
No frontend lint gate catches it, but clean it up.

---

## VERIFY-ON-DEVICE (please confirm on the Deck after the above; I can't from static review)

These are not blockers for the next round's code changes, but call them out in your
next session log / note so we close them before PASS:

- **A. Open-at-top actually works.** After the fix, the modal should mount showing
  the header + newest snapshot with gamepad focus on the **first** Restore button —
  not scrolled to the footer.
- **B. `DialogBody` scrolls.** The old code used an explicit `overflowY:auto`
  container; `DialogBody` (now holding `ref={scrollRef}`) must actually scroll a
  long backup list, and focusing the first row must scroll the **DialogBody** to top
  (not the whole modal). If `DialogBody` doesn't scroll its overflow, wrap the list
  in a scrollable container (or restore an explicit `overflowY:auto` style on the
  body) and keep `scrollRef` on the element that actually scrolls.
- **C. Two close affordances.** `bHideBuiltInClose={false}` keeps the built-in
  top-right ✕ *and* there's a footer Close button. Pre-existing, but with native
  chrome it's worth deciding: keep both, or drop the footer `DialogButton` Close and
  rely on the built-in ✕. Your call — note the decision.

---

## Not changes — confirmations (good)

- Scope respected: only `BackupBrowserModal.tsx` + the plan doc changed; Force-Restore
  removal and backend untouched.
- All hardcoded hex colors (`#212224`, `#43464c`, `#333`, `rgba(...)`) removed in
  favor of native components. 👍
- Props, fetch effect, `mounted` guard, and the `ConfirmModal` restore flow preserved.

---

## What to do next (per the plan's B5)

1. Apply MUST-FIX #1–#2 and SHOULD-FIX #3–#4 as atomic commits.
2. Re-run `pnpm run typecheck` + `pnpm run test:unit`.
3. Verify A–C on the Deck and record findings.
4. Ensure this review note is committed on the branch.
5. Re-`touch /tmp/sdh_ludusavi/backup_browser_native_ui_finished` and wait for
   `docs/review/backup_browser_native_ui_review_2.md`.
