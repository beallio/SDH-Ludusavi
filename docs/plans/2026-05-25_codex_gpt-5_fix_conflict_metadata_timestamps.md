# Emit Timezone-Aware Conflict Metadata Timestamps

Date: 2026-05-25
Planner Model: codex_gpt-5
Review Source: `docs/review/2026-05-24_gemini_3_5_flash.md`

## Execution Skill

Execute this plan with the `implementer` skill. The implementation must follow that
skill's discovery, branch isolation, strict TDD, atomic commit, validation, and
review-gate workflow, while also honoring this repository's `AGENTS.md` protocol.

## Problem Definition

`PyludusaviAdapter.get_conflict_metadata()` reports the newest local save file
modification time with:

```python
metadata["localModifiedAt"] = datetime.fromtimestamp(max(mtimes)).isoformat()
```

This produces a naive local datetime string. Ludusavi backup metadata commonly uses
timezone-aware values such as `2026-05-10T00:00:00Z`. Current frontend code displays
these strings directly rather than comparing them. The conflict payload should use
unambiguous timestamps, and the conflict modal should format both local and backup
timestamps into the user's local timezone so the two choices are easy to compare.

The change should keep the payload keys unchanged:

- `localModifiedAt`
- `backupModifiedAt`
- `backupPath`

## Architecture Overview

Convert local file mtimes into timezone-aware UTC ISO strings at the adapter boundary.
The service continues to pass the string without schema changes. The frontend parses
both `localModifiedAt` and `backupModifiedAt` and displays them with the browser's
local timezone formatting.

```mermaid
graph LR
    A[Ludusavi backup preview] --> B[File paths]
    B --> C[Path.stat().st_mtime]
    C --> D[datetime.fromtimestamp(ts, tz=timezone.utc)]
    D --> E[ISO string with offset]
    E --> F[localModifiedAt conflict metadata]

    G[backups_list latest backup] --> H[backupModifiedAt]
    F --> I[Service conflict payload]
    H --> I
    I --> J[Frontend formatConflictTime]
    J --> K[Local timezone display]
```

Prefer UTC rather than local `.astimezone()` because UTC is stable across Decky,
SteamOS, logs, and remote debugging. Prefer local-time display in the UI because the
conflict dialog is a user decision point, not a machine log.

## Core Data Structures

No new data structures.

Existing payload:

```python
{
    "localModifiedAt": str | None,
    "backupModifiedAt": object,
    "backupPath": object,
}
```

The expected `localModifiedAt` format becomes timezone-aware ISO 8601:

```text
2026-05-19T09:00:00+00:00
```

## Public Interfaces

No interface shape changes.

Behavioral detail:

- `localModifiedAt` remains a string when present.
- The string now includes timezone offset information.
- `backupModifiedAt` remains the upstream Ludusavi string.
- `formatConflictTime()` parses both timestamp strings and renders them in local
  time.
- If parsing fails, `formatConflictTime()` falls back to the original string.

## Implementation Steps

1. Update the import in `py_modules/sdh_ludusavi/ludusavi.py`:
   - from `from datetime import datetime`
   - to `from datetime import datetime, timezone`
2. Replace `datetime.fromtimestamp(max(mtimes)).isoformat()` with
   `datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat()`.
3. Keep exception handling unchanged.
4. Do not parse or rewrite `backupModifiedAt`; preserve Ludusavi's upstream value.
5. Update `src/index.tsx::formatConflictTime()` to parse ISO-like timestamp strings
   and format valid dates into local time.
6. Add tests for aware UTC local timestamps.
7. Add frontend static coverage for local-time formatting behavior.

## Example Code

```python
from datetime import datetime, timezone

...

if mtimes:
    latest_mtime = max(mtimes)
    metadata["localModifiedAt"] = datetime.fromtimestamp(
        latest_mtime,
        tz=timezone.utc,
    ).isoformat()
```

Frontend local-time display:

```typescript
function formatConflictTime(value?: string | null) {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}
```

If tests need stable output independent of the runner's locale, assert directly on
the parsing and `toLocaleString` call shape in static tests instead of snapshotting a
localized string.

## Testing Strategy

Strict TDD applies because this changes payload content and frontend display behavior.

Add coverage to `tests/test_ludusavi.py`.

The current `FakeLudusaviClient` only has `backups_list()` and `restore()`. Extend it
or add a dedicated fake with `backup(..., preview=True, force=True)` returning file
metadata.

Example test shape:

```python
def test_conflict_metadata_local_modified_at_is_timezone_aware_utc(tmp_path: Path) -> None:
    save_file = tmp_path / "save.dat"
    save_file.write_text("save", encoding="utf-8")
    os.utime(save_file, (1_800_000_000, 1_800_000_000))

    class FakeClient:
        def backups_list(self, games: list[str] | None = None) -> FakeResponse:
            return FakeResponse({
                "games": {
                    "Hades": {
                        "backups": [{"when": "2026-05-10T00:00:00Z"}],
                        "backupPath": "/backup/Hades",
                    }
                }
            })

        def backup(self, games: list[str] | None = None, preview: bool = False, force: bool = False) -> FakeResponse:
            return FakeResponse({
                "games": {
                    "Hades": {
                        "files": {
                            "save": {"originalPath": str(save_file)}
                        }
                    }
                }
            })

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = FakeClient()

    metadata = adapter.get_conflict_metadata("Hades")

    assert metadata["localModifiedAt"].endswith("+00:00")
    assert datetime.fromisoformat(metadata["localModifiedAt"]).tzinfo is not None
```

Also add or update an assertion that `backupModifiedAt` is preserved exactly from
Ludusavi.

Add coverage to `tests/test_frontend_static.py`:

- `formatConflictTime()` constructs `new Date(value)`.
- it guards invalid dates with `Number.isNaN(date.getTime())`.
- it formats valid dates with `date.toLocaleString()`.
- it keeps the existing `"Unknown time"` fallback for missing values.

Example static assertions:

```python
def test_frontend_conflict_time_formats_valid_dates_locally() -> None:
    source = FRONTEND.read_text()

    assert "function formatConflictTime" in source
    assert "new Date(value)" in source
    assert "Number.isNaN(date.getTime())" in source
    assert "return date.toLocaleString();" in source
    assert 'return "Unknown time";' in source
```

## Validation

Targeted validation:

```bash
./run.sh uv run pytest tests/test_ludusavi.py
./run.sh uv run pytest tests/test_frontend_static.py
./run.sh pnpm run typecheck
```

Full validation before commit:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run typecheck
```

## Acceptance Criteria

- `localModifiedAt` includes timezone offset information.
- `backupModifiedAt` remains unchanged from Ludusavi output.
- The conflict modal displays both local and backup timestamps in the user's local
  timezone when parsing succeeds.
- Invalid timestamp strings remain visible as their original raw value.
- Missing or inaccessible save paths still degrade silently as before.
- Conflict payload keys and frontend type definitions do not change.
- Existing conflict modal labels remain unchanged.
