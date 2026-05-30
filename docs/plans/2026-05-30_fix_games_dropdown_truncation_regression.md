# SteamOS Games Dropdown Workaround With Backout Plan

## Summary

Implement a narrow frontend workaround for the SteamOS dropdown-width regression while
preserving the review intent that removed the broad wildcard CSS selector. This is a
temporary SteamOS compatibility shim, so it must be isolated in one commit and easy to
remove later.

The known-good behavior is commit `6ce165b7e41c5083b095d3a90d9aa6e67d7e37f0`.
The requested visual backout reference is commit
`7fea9f8beffe0dbbea337a524013cd6bacafcae0`, but do not reset the repo or
`src/index.tsx` wholesale to that commit because many unrelated QAM/settings fixes
landed after it.

## Implementation Steps

1. Start with protocol compliance:
   - Run read-only verification: `pwd`, `ls`, `git status --short --branch`,
     inspect `.protocol`, `pyproject.toml`, `package.json`, and `run.sh`.
   - Confirm Project Mode, cache root `/tmp/sdh_ludusavi`, wrapper `./run.sh`,
     and type checker `ty`.
   - Check for uncommitted user work and avoid formatting or staging unrelated
     files.

2. Preserve this plan artifact:
   - Keep this file updated if implementation details change.
   - Include root cause, SteamOS workaround rationale, why not to simply revert,
     test strategy, runtime proof gate, and rollback instructions.
   - State that the primary backout is `git revert <single workaround commit>`.

3. Add red tests before runtime code:
   - Update `tests/test_frontend_static.py`.
   - Add `test_frontend_dropdown_uses_scoped_steamos_truncation_workaround`.
   - Assert:
     - no `.sdh-ludusavi-game-dropdown *` selector
     - `DropdownItem` remains `layout="below"`
     - the dropdown retains `className="sdh-ludusavi-game-dropdown"`
     - `DropdownItem` uses `renderButtonValue`
     - selected text is wrapped in `sdh-ludusavi-game-dropdown-value`
     - CSS gives explicit `min-width: 0` and `max-width: 100%` to scoped
       dropdown wrapper/control/flex-chain selectors
     - CSS applies ellipsis to `sdh-ludusavi-game-dropdown-value`
     - CSS protects `svg`, `[class*="icon" i]`, `[class*="chevron" i]`, and
       `[class*="arrow" i]` with non-collapsing sizing
   - Run targeted tests and confirm the new test fails before implementation.

4. Implement the frontend fix in `src/index.tsx`:
   - Keep the existing `PanelSection title="GAME"` and `DropdownItem`.
   - Keep `layout="below"`, `highlightOnFocus`, `focusable`, `disabled={isBusy}`,
     `rgOptions={gamesDropdownOptions}`, `selectedOption={selectedGame}`, and
     `onChange={onGameChange}`.
   - Keep QAM-local `{styleElement}` rendering.
   - Add:

     ```tsx
     renderButtonValue={(value) => (
       <span className="sdh-ludusavi-game-dropdown-value">{value}</span>
     )}
     ```

   - Replace the current too-narrow CSS with scoped rules that:
     - keep `.sdh-ludusavi-game-dropdown` at `width: 100%`
     - apply shrink constraints to explicit dropdown control containers and
       nested flex `div` wrappers under this dropdown only
     - apply ellipsis to `.sdh-ludusavi-game-dropdown-value` and safe text
       containers
     - preserve icon/chevron intrinsic width
     - never reintroduce the broad descendant wildcard
   - Add one short code comment above the dropdown CSS:
     - It exists for a SteamOS QAM dropdown long-name regression.
     - It is scoped to avoid broad wildcard side effects on Decky icons.
     - It should be removed by reverting the single workaround commit when
       SteamOS no longer needs it.

5. Do not create a rollback patch by default:
   - The required rollback mechanism is the isolated commit.
   - After committing, document the exact backout command:
     - `git revert 9b3f9022319c8f628c2a78927f464bbb8d7bfb56`
   - Create `docs/patches/...` only if explicitly requested later.

6. Add the session log:
   - Add
     `docs/agent_conversations/2026-05-30_fix_games_dropdown_truncation_regression.json`.
   - Include objective, files modified, tests added, design decisions, validation
     results, runtime validation status, and rollback command.

## Validation Plan

### Red Check

Run the targeted frontend static tests before implementation and confirm the new
test fails.

### Targeted Validation After Implementation

```bash
./run.sh uv run pytest tests/test_frontend_static.py::test_frontend_dropdown_has_below_layout tests/test_frontend_static.py::test_frontend_dropdown_truncation_styling tests/test_frontend_static.py::test_frontend_dropdown_uses_scoped_steamos_truncation_workaround tests/test_frontend_static.py::test_frontend_code_review_refinements -q
```

### Full Required Validation

```bash
./run.sh uv run ruff check .
./run.sh uv run ruff format --check .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run typecheck
./run.sh pnpm run build
```

## Runtime Proof Gate

Static tests are not enough. The implementation is visually confirmed only after Deck
runtime validation confirms:

- A very long selected game name does not expand the dropdown or QAM panel.
- The selected text ellipsizes inside the input.
- The dropdown chevron/icon remains visible and non-collapsed.
- The dropdown remains aligned with the other GAME panel controls.
- Controller focus/highlight behavior is unchanged.
- In DevTools or equivalent inspection, the selected text has
  `scrollWidth > clientWidth` and computed styles include hidden overflow,
  ellipsis, and nowrap.
- Ancestors between the selected-value wrapper and dropdown wrapper do not force
  horizontal overflow.

If the implementing agent cannot access Deck runtime validation, it must mark runtime
status as `PENDING MANUAL DECK VALIDATION` in the session log and final response. Do
not claim the visual regression is fully fixed until this proof gate passes.

## Commit Plan

- Commit the implementation as one isolated commit:
  - `fix(qam): restore game dropdown truncation workaround`
- The single-purpose commit is the required future backout mechanism:
  - `git revert 9b3f9022319c8f628c2a78927f464bbb8d7bfb56`
- Do not mix unrelated refactors into this commit.

## Assumptions

- "Back to `7fea9f8`" means the dropdown input's pre-workaround visual behavior,
  not a full repository reset.
- This is a temporary SteamOS compatibility workaround.
- The review concern about broad wildcard selectors remains valid.
- The fix is frontend-only unless runtime validation reveals a Decky API limitation.
