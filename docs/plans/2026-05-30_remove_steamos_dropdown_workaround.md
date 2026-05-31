# Remove SteamOS Games Dropdown Workaround

## Summary

The temporary SteamOS games dropdown workaround began at commit
`8061dbc2a61d2f7931da5958031f277b9dff2241`
(`fix(qam): force games dropdown to span full width`).

Do not treat later commits, such as `9b3f902`, as the full rollback boundary.
Those later commits only repair or refine the workaround. If the workaround needs to
be removed after SteamOS fixes the upstream UI regression, use a targeted rollback
commit instead of a broad revert chain.

## Rollback Strategy

Create a targeted rollback commit that restores only the games dropdown input UI
surface to pre-`8061dbc` behavior.

Remove workaround-specific UI/code:

- Remove `layout="below"` from the games `DropdownItem`.
- Remove the `sdh-ludusavi-game-dropdown` wrapper.
- Remove `renderButtonValue`.
- Remove `sdh-ludusavi-game-dropdown-value`.
- Remove `dropdownStyleEl` and `{styleElement}` if they are only used for this
  dropdown workaround.

Remove or update tests that only enforce the workaround:

- `test_frontend_dropdown_has_below_layout`
- `test_frontend_dropdown_truncation_styling`
- `test_frontend_dropdown_styling_lifecycle`
- the wildcard assertion in `test_frontend_code_review_refinements`, if it only
  exists for this workaround
- `test_frontend_dropdown_uses_scoped_steamos_truncation_workaround`

Preserve unrelated fixes:

- QAM settings queue behavior
- `activeInitPromise` and `activeMetadataPromise`
- selected-game persistence
- current-game resolver behavior
- notification handling
- backend behavior

## Suggested Commit

```text
revert(qam): remove SteamOS dropdown layout workaround
```

## Suggested Future Prompt

```text
Remove the temporary SteamOS games dropdown workaround introduced beginning with
8061dbc2a61d2f7931da5958031f277b9dff2241. Restore only the games DropdownItem
visual/input structure to its pre-8061dbc behavior. Do not revert unrelated QAM
settings queue, selected-game persistence, initialization promise, current-game
resolver, or backend changes. Update/remove static tests and docs that exist only
to enforce the workaround. Validate with frontend static tests, typecheck, and
build.
```
