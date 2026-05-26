# Remove Hardcoded Template Migration Paths

## Problem Definition

`Plugin._migration()` in `main.py` still contains Decky template scaffold migration
paths. The method attempts to migrate from `decky-template`, `template.log`,
`template.json`, and a `template` runtime directory even though SDH-ludusavi has no
supported legacy template namespace.

This is confusing for maintainers and potentially unsafe for users who happen to have
unrelated files under those template paths. The Decky lifecycle hook should remain in
place, but it should not read from or migrate any template-owned namespace.

## Architecture Overview

Keep `_migration()` as an async Decky lifecycle method so the public plugin lifecycle
shape does not change. Convert the body to an explicit no-op log statement that states
there are no legacy paths to migrate.

The change is intentionally narrow:

- Do not refactor code outside `Plugin._migration()`.
- Do not change public RPCs, return types, frontend code, or service behavior.
- Do not add dependencies.
- Do not modify vendored or upstream packages.

## Core Data Structures

No data structures are added or changed.

The expected end state is absence of any case-insensitive `template` reference from
`main.py`, including these hardcoded legacy literals:

- `decky-template`
- `template.log`
- `template.json`
- `template`

## Public Interfaces

No public API changes are required.

`Plugin._migration()` remains:

```python
async def _migration(self) -> None:
```

The method should return `None`, perform no file migration, and emit a single
informational log message such as:

```text
SDH-ludusavi migration skipped; no legacy paths to migrate
```

## Dependency Requirements

No dependency changes are required.

Continue using the existing project wrapper and cache layout:

- `./run.sh` for project commands
- `/tmp/sdh_ludusavi` for the cache and virtual environment root
- `ty` for Python type checking

## Testing Strategy

Follow Red-Green-Refactor.

Red phase:

1. Add focused regression coverage in `tests/test_main.py`.
2. Assert calling `Plugin._migration()` does not call `decky.migrate_logs`,
   `decky.migrate_settings`, or `decky.migrate_runtime`.
3. Assert `main.py` no longer contains any case-insensitive `template` reference:

```python
def test_migration_has_no_template_scaffolding_paths() -> None:
    content = Path("main.py").read_text(encoding="utf-8")
    assert "template" not in content.casefold()
```

4. Run:

```bash
./run.sh uv run pytest tests/test_main.py -q -k migration
```

The new test must fail against the current implementation before production code is
changed.

Green phase:

1. Remove the Decky migration helper calls from `Plugin._migration()`.
2. Leave only the explicit no-op informational log.
3. Rerun:

```bash
./run.sh uv run pytest tests/test_main.py -q -k migration
```

Validation phase:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
rg -i "template" main.py
```

The final `rg` command should return no matches.

## Implementation Notes

- Start from a clean working tree and use a branch such as
  `refactor/remove-template-migration`.
- Keep the source edit limited to `main.py`.
- Keep test edits limited to `tests/test_main.py`.
- Record a session log under `docs/agent_conversations/` after implementation.
- Use a Conventional Commit message such as
  `refactor(migration): remove template path migration`.

## Acceptance Criteria

- All case-insensitive `template` references are removed from `main.py`.
- Plugin startup no longer attempts to migrate from Decky template namespaces.
- `_migration()` remains available as the Decky lifecycle hook.
- Focused migration tests pass.
- Full backend validation passes through `./run.sh`.
