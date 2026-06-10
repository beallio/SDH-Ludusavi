# Review: Commit f5f7bbc — `compare_recency` Direction Safety

**Commit:** `f5f7bbc0ca74f6865f1ea2806019d4c3ddaf2917`
**Plan reviewed against:** `docs/plans/2026-06-09_fix_compare_recency_direction.md`
**Reviewer verification performed:** full diff read; `./run.sh uv run pytest` (461 passed); `./run.sh uv run ruff check .` (clean); `./run.sh uv run ruff format --check .` (clean); `./run.sh uv run ty check py_modules/sdh_ludusavi/` (clean); `pnpm run verify` (79 tests passed, tsc clean); grep sweep confirmed the old `("New", "Different")` tuple is gone from `py_modules/sdh_ludusavi/`.

## Verdict

**The core safety objective is met, but the commit is an incomplete implementation of the plan.** The dangerous `"Different"` → auto-restore path is closed: `compare_recency` now returns `backup_differs`, and `check_game_start` only auto-restores when the backup timestamp beats the local timestamp by more than 120 seconds, otherwise routing to the existing conflict modal with the unchanged `ambiguous_recency` payload. Response shapes, frontend, and forbidden files are untouched. All quality gates pass.

However, **plan Step 3c/3d was skipped entirely** (Finding 1, the only finding that changes runtime behavior), the timestamp parser lacks the timezone normalization the plan required (Finding 2), and several plan-specified tests and log lines were dropped (Findings 3–5). Fix instructions below are written to be followed literally, in order, using strict TDD (RED test first, then implementation).

---

## Plan compliance matrix

| Plan item | Status |
|---|---|
| Step 1: margin constant in `constants.py` | ✅ Done (named `RECENCY_DIFFERS_TIMEDELTA` instead of planned `RECENCY_TIMESTAMP_MARGIN_SECONDS` — see Finding 6) |
| Step 2a: retarget existing adapter test to `New` | ✅ Done (`test_compare_recency_returns_backup_newer_when_restore_preview_shows_new`) |
| Step 2b test 1: `Different` → `backup_differs` adapter test | ✅ Done |
| Step 2b test 2: `test_get_conflict_metadata_uses_newest_backup_timestamp` | ❌ **Missing** (Finding 1) |
| Step 3a: `compare_recency` mapping split | ✅ Done |
| Step 3b: `compare_recency` docstring listing all five return values | ⚠️ Partial — docstring still only describes the preview mechanism (Finding 7) |
| Step 3c: `get_conflict_metadata` newest-timestamp selection | ❌ **Missing** (Finding 1) |
| Step 3d: `_newest_backup_when` helper | ❌ **Missing** (Finding 1) |
| Step 3e: `types.py` protocol docstring | ✅ Done |
| Step 4: lifecycle direction tests | ⚠️ 9 tests added covering edge cases 1, 3, 4, 5, 6, 7, 8; built as `GameLifecycleManager` unit tests with MagicMock deps instead of the planned `SDHLudusaviService`-level tests (acceptable), but history-recording test and `Z`-suffix coverage are missing (Findings 4, 5) |
| Step 4: pure-function `_timestamp_direction` tests | ❌ Missing — helper was never created (Finding 3) |
| Step 5a/5b: `_parse_iso_utc` + `_timestamp_direction` module helpers | ⚠️ Replaced by `GameLifecycleManager._parse_iso_timestamp` static method + inlined comparison; **no naive→UTC normalization** (Findings 2, 3) |
| Step 5c: `_conflict_response` helper | ✅ Done (history recording kept at call site instead of inside the helper — fine, single call site) |
| Step 5d: rework recency branch; fetch metadata once; `backup_newer` short-circuits before metadata fetch | ✅ Done (`lifecycle.py:100-126`) |
| Step 5d: two `self.dependencies.log(...)` info lines on the `backup_differs` decision | ❌ **Missing** (Finding 4) |
| Step 6a: grep sweep | ✅ Verified clean (only remaining `"New", "Different"` hit is the upstream `pyludusavi/models.py` Literal type, which is correct and must not be edited) |
| Step 6b: all gates | ✅ All pass (re-verified during this review) |
| Step 7a: README sentence | ✅ Done, matches plan text |
| Step 7b: plan committed + session log | ✅ Done (plan was committed in 27f8901; session log in this commit) |
| §5 acceptance criterion 5 (payload byte-compat) | ✅ `test_check_game_start_reports_conflict_for_ambiguous_recency` in `tests/test_service.py` passes unmodified |
| §4 edge case #10 (differential child backup is newest) | ❌ **Not handled, not tested** (Finding 1) |
| §6 out-of-scope restrictions | ✅ Respected — no `src/`, no `pyludusavi`, no unrelated edits |

---

## Findings and exact fixes

> **Process requirements for the fixing agent:** Work on branch `fix/compare-recency-direction`. Follow strict TDD: for each finding, write the RED test first, run it, watch it fail for the stated reason, then implement, then watch it pass. Run every command through `./run.sh`. Do not modify anything under `src/` or `py_modules/pyludusavi/`. Do not change the conflict payload keys or the `"ambiguous_recency"` reason string. Commit each finding's fix atomically with Conventional Commits. After all fixes: run the full gate set from §Quality-gates at the bottom of this file.

---

### Finding 1 (MAJOR — planned functional change missing): `get_conflict_metadata` still uses `backups[0]`, not the newest backup timestamp

**Where:** `py_modules/sdh_ludusavi/ludusavi.py:195-199`

**Current code:**
```python
            backups = game_backups.get("backups") or []
            if backups:
                latest_backup = backups[0]
                if isinstance(latest_backup, dict):
                    metadata["backupModifiedAt"] = latest_backup.get("when")
```

**Why this matters:** The new direction check in `check_game_start` computes `backup_dt - local_dt` from `metadata["backupModifiedAt"]`. If `backups[0]` is not the newest artifact (multiple retained full backups, or a differential child backup that is newer than its parent full backup), the comparison uses a stale timestamp. Consequence: a backup that is legitimately newer (synced from another device) computes as *older* → the user gets the conflict modal instead of the planned auto-restore (plan §4 edge case #3 fails in those configurations), and the modal displays a wrong "backup modified" time. The failure direction is safe (never data loss), but the plan explicitly required this fix (Steps 2b/3c/3d, edge case #10) and it was not delivered.

**Note on the plan's `children` assumption:** `py_modules/pyludusavi/models.py` `ApiBackup` (line 66) does not declare a `children` key. The adapter consumes raw dicts, not validated TypedDicts, so handle `children` defensively exactly as the plan specified: if present, scan it; if absent, the loop simply finds nothing. Do NOT edit `pyludusavi/models.py`.

**Fix — RED first.** Add this test to `tests/test_ludusavi.py`, directly below `test_compare_recency_returns_backup_differs_when_restore_preview_shows_different`. Use the existing `adapter_with_backups` helper already used by the neighboring tests (read its signature at the top of the file first; it takes `backup_data` and `restore_data` keyword arguments):

```python
def test_get_conflict_metadata_uses_newest_backup_timestamp() -> None:
    adapter, _client = adapter_with_backups(
        backup_data={
            "games": {
                "Hades": {
                    "backups": [
                        {"when": "2026-01-01T00:00:00Z"},
                        {
                            "when": "2026-03-01T00:00:00Z",
                            "children": [{"when": "2026-03-02T00:00:00Z"}],
                        },
                    ]
                }
            }
        },
        restore_data={"games": {"Hades": {"change": "Different"}}},
    )

    metadata = adapter.get_conflict_metadata("Hades")

    assert metadata["backupModifiedAt"] == "2026-03-02T00:00:00Z"
```

If `adapter_with_backups` requires the backup-preview side for `localModifiedAt` (it calls `self._client.backup(...)`), that is fine — this test only asserts `backupModifiedAt`. Run and confirm it FAILS with `assert '2026-01-01T00:00:00Z' == '2026-03-02T00:00:00Z'`:

```bash
./run.sh uv run pytest tests/test_ludusavi.py -k newest_backup_timestamp -x
```

**Fix — GREEN.** In `py_modules/sdh_ludusavi/ludusavi.py`:

1. Replace the block at lines 195–199 with:

```python
            backups = game_backups.get("backups") or []
            newest_when = _newest_backup_when(backups)
            if newest_when is not None:
                metadata["backupModifiedAt"] = newest_when
```

2. Add this module-level function at the bottom of `ludusavi.py` (next to the other module-level helpers; if none exist at the bottom, place it after the `PyludusaviAdapter` class):

```python
def _newest_backup_when(backups: object) -> str | None:
    """
    Return the lexicographically greatest RFC3339 "when" timestamp across all
    full backups and any differential children. Ludusavi emits UTC RFC3339
    strings, which sort correctly as strings; entries that are not dicts or
    lack a string "when" are ignored.
    """
    if not isinstance(backups, list):
        return None
    candidates: list[str] = []
    for entry in backups:
        if not isinstance(entry, dict):
            continue
        when = entry.get("when")
        if isinstance(when, str) and when:
            candidates.append(when)
        children = entry.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    child_when = child.get("when")
                    if isinstance(child_when, str) and child_when:
                        candidates.append(child_when)
    return max(candidates) if candidates else None
```

Lexicographic `max` is valid only because all values arrive in the same `YYYY-MM-DDTHH:MM:SSZ` UTC shape; the lifecycle layer re-parses with `datetime` anyway, so a malformed string here only affects modal display, never the restore decision.

Re-run the test from RED; it must pass. Then run the whole adapter file: `./run.sh uv run pytest tests/test_ludusavi.py tests/test_exception_boundaries.py`.

**Commit:** `fix(ludusavi): select newest backup timestamp (including differential children) for conflict metadata`

---

### Finding 2 (MEDIUM — robustness): timestamp parser does not normalize naive vs. aware datetimes

**Where:** `py_modules/sdh_ludusavi/lifecycle.py:43-51` (`_parse_iso_timestamp`) and the subtraction at `lifecycle.py:113`.

**Problem:** Plan Step 5b's `_parse_iso_utc` normalized every parsed value to aware UTC (`if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)` then `.astimezone(timezone.utc)`). The implemented `_parse_iso_timestamp` returns `datetime.fromisoformat(ts)` unmodified. If one parsed timestamp is timezone-aware and the other is naive, `(backup_dt - local_dt)` at line 113 raises `TypeError: can't subtract offset-naive and offset-aware datetimes`, and that exception is **uncaught** inside `check_game_start` — it would propagate out of the RPC call instead of safely falling back to the conflict modal. Today both production sources are aware (`localModifiedAt` is built with `tz=timezone.utc` in `ludusavi.py:222-225`; ludusavi's `when` carries a `Z` suffix, which Python 3.12 `fromisoformat` parses as aware), so this is latent rather than live — but the plan required the guard precisely because the metadata dict is typed `dict[str, object]` and any future adapter or upstream format drift would turn this into a launch-blocking crash.

**Fix — RED first.** Add to `tests/test_recency_direction.py`:

```python
def test_backup_differs_conflict_when_timestamps_mix_naive_and_aware() -> None:
    """A naive local timestamp paired with an aware backup timestamp must not
    raise; it must resolve safely (normalized comparison, not a crash)."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T02:10:00",  # naive
        backup_modified_at="2026-06-01T02:05:00+00:00",  # aware
    )
    result = manager.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"
```

Run `./run.sh uv run pytest tests/test_recency_direction.py -k naive -x` and confirm it FAILS with the `TypeError` described above (it will surface as an error, not an assertion failure — that is the correct RED signal).

**Fix — GREEN.** In `py_modules/sdh_ludusavi/lifecycle.py`, replace the `_parse_iso_timestamp` static method (lines 43–51) with:

```python
    @staticmethod
    def _parse_iso_timestamp(ts: str | None) -> datetime | None:
        """Parse an ISO-8601 timestamp to aware UTC, returning None if unparseable.

        Naive timestamps are assumed to be UTC so that mixed naive/aware
        inputs can never raise during subtraction.
        """
        if ts is None:
            return None
        try:
            parsed = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
```

And change the import on line 7 from:

```python
from datetime import datetime
```

to:

```python
from datetime import datetime, timezone
```

While editing, fold that import into the grouped import block per the file's existing style (it currently sits awkwardly between the `typing` import and the relative imports; `ruff format`/`ruff check` will tell you if ordering matters — obey ruff).

Re-run the RED test; it must now pass (naive local treated as UTC → local is newer → conflict). Run the whole file: `./run.sh uv run pytest tests/test_recency_direction.py tests/test_service.py`.

**Commit:** `fix(lifecycle): normalize parsed timestamps to aware UTC to prevent naive/aware subtraction errors`

---

### Finding 3 (MINOR — structure + missing planned tests): direction decision is inlined instead of the plan's testable `_timestamp_direction` helper

**Where:** `py_modules/sdh_ludusavi/lifecycle.py:107-119`.

**Problem:** Plan Step 5b specified a pure module-level function `_timestamp_direction(local, backup, margin) -> Literal["backup_newer", "not_newer", "unknown"]` plus two pure-function tests (Step 4 bottom). The commit inlined the comparison in `check_game_start`, so the margin boundary logic has no direct unit tests and cannot be exercised without building a full mocked manager.

**Decision for the fixing agent:** Implement this **together with Finding 2** (they touch the same lines) but as a separate refactor commit after Finding 2 is green, OR fold both into one commit if the diff is small — prefer two commits.

**Fix — RED first.** Add at the bottom of `tests/test_recency_direction.py`:

```python
from sdh_ludusavi.lifecycle import _timestamp_direction


def test_timestamp_direction_backup_newer_beyond_margin() -> None:
    assert (
        _timestamp_direction("2026-06-01T00:00:00+00:00", "2026-06-01T00:05:00Z", 120)
        == "backup_newer"
    )


def test_timestamp_direction_not_newer_at_exact_margin() -> None:
    # Strictly-greater-than semantics: exactly 120s is NOT clearly newer.
    assert (
        _timestamp_direction("2026-06-01T00:00:00+00:00", "2026-06-01T00:02:00Z", 120)
        == "not_newer"
    )


def test_timestamp_direction_unknown_on_missing_or_bad_input() -> None:
    assert _timestamp_direction(None, "2026-06-01T00:05:00Z", 120) == "unknown"
    assert _timestamp_direction("2026-06-01T00:00:00+00:00", None, 120) == "unknown"
    assert _timestamp_direction("garbage", "2026-06-01T00:05:00Z", 120) == "unknown"
    assert _timestamp_direction(123, "2026-06-01T00:05:00Z", 120) == "unknown"  # type: ignore[arg-type]
```

Run `./run.sh uv run pytest tests/test_recency_direction.py -k timestamp_direction -x` — RED is an `ImportError` (`_timestamp_direction` does not exist).

**Fix — GREEN.** In `py_modules/sdh_ludusavi/lifecycle.py`:

1. Add `Literal` to the typing import on line 5: `from typing import Any, Callable, Literal, cast`.
2. Add this module-level function above the `LifecycleDependencies` dataclass (module level, NOT a method — the tests import it directly):

```python
def _timestamp_direction(
    local_modified_at: object,
    backup_modified_at: object,
    margin_seconds: float,
) -> Literal["backup_newer", "not_newer", "unknown"]:
    """Decide restore direction from conflict-metadata timestamps.

    Returns "backup_newer" only when the backup timestamp exceeds the local
    timestamp by strictly more than margin_seconds. Missing or unparseable
    input yields "unknown".
    """
    local = GameLifecycleManager._parse_iso_timestamp(
        local_modified_at if isinstance(local_modified_at, str) else None
    )
    backup = GameLifecycleManager._parse_iso_timestamp(
        backup_modified_at if isinstance(backup_modified_at, str) else None
    )
    if local is None or backup is None:
        return "unknown"
    if (backup - local).total_seconds() > margin_seconds:
        return "backup_newer"
    return "not_newer"
```

   ⚠️ Module-level code cannot reference `GameLifecycleManager` before the class is defined. Two valid layouts — pick ONE:
   - **(a) Preferred:** move `_parse_iso_timestamp` out of the class entirely, making it a module-level `def _parse_iso_timestamp(ts: object) -> datetime | None:` (accepting `object` and returning `None` for non-`str`, which also removes the two `cast(...)` calls in `check_game_start`), and define `_timestamp_direction` right after it. Update the two call sites inside `check_game_start` accordingly and delete the staticmethod.
   - **(b)** Keep the staticmethod and define `_timestamp_direction` *below* the class. Both pass; (a) matches the plan exactly.

3. Replace the inlined block in `check_game_start` (currently lines 107–119) with:

```python
        if recency == "backup_differs":
            direction = _timestamp_direction(
                metadata.get("localModifiedAt"),
                metadata.get("backupModifiedAt"),
                RECENCY_DIFFERS_TIMEDELTA,
            )
            if direction == "backup_newer":
                return {"status": "needed", "operation": "restore", "game": game.name}
```

(The log lines required by Finding 4 are added in this same block — apply Finding 4 simultaneously to avoid touching these lines twice.)

Re-run: `./run.sh uv run pytest tests/test_recency_direction.py tests/test_service.py tests/test_ludusavi.py` — everything must pass, including every pre-existing test, unmodified.

**Commit:** `refactor(lifecycle): extract _timestamp_direction helper with direct unit tests`

---

### Finding 4 (MINOR — missing planned observability): no log lines on the `backup_differs` decision

**Where:** `py_modules/sdh_ludusavi/lifecycle.py:107-119`.

**Problem:** Plan Step 5d required two `self.dependencies.log("info", ...)` calls — one when auto-restoring because the backup is clearly newer, one when deferring to the conflict modal. Neither exists. On a Steam Deck, these are the only way to tell from logs *why* a restore happened or a modal appeared.

**Fix (apply inside the Finding 3 block edit; no separate RED test is required for log lines, but add the assertion below to lock them in):**

```python
        if recency == "backup_differs":
            direction = _timestamp_direction(
                metadata.get("localModifiedAt"),
                metadata.get("backupModifiedAt"),
                RECENCY_DIFFERS_TIMEDELTA,
            )
            if direction == "backup_newer":
                self.dependencies.log(
                    "info",
                    f"Backup for {game.name} differs and is newer by timestamp; proceeding with restore",
                    "start",
                    game.name,
                )
                return {"status": "needed", "operation": "restore", "game": game.name}
            self.dependencies.log(
                "info",
                f"Backup for {game.name} differs but direction is {direction}; deferring to conflict resolution",
                "start",
                game.name,
            )
```

Add to `tests/test_recency_direction.py` (the `log` dependency is already a MagicMock named `log` inside `_make_manager`; expose it by returning it or by reaching through `manager.dependencies.log`):

```python
def test_backup_differs_decisions_are_logged() -> None:
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T00:00:00+00:00",
        backup_modified_at="2026-06-01T02:05:00+00:00",
    )
    manager.check_game_start("Hades")
    logged = " | ".join(str(call) for call in manager.dependencies.log.call_args_list)
    assert "proceeding with restore" in logged
```

**Commit:** included in the Finding 3 commit (same block) — mention it in that commit body.

---

### Finding 5 (MINOR — test coverage gaps): three plan-specified behaviors lack assertions

**Where:** `tests/test_recency_direction.py`.

**Gap A — history recording is never asserted.** Plan Step 4 had `test_conflict_records_skipped_history_with_ambiguous_recency`. The commit's tests use a MagicMock history and never check it, so a regression that drops the `record_history` call (or fires it on the auto-restore path, which would wrongly log a "skipped" entry for a restore that proceeds) would pass the suite. Add:

```python
def test_conflict_records_skipped_history_with_ambiguous_recency() -> None:
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T02:10:00+00:00",
        backup_modified_at="2026-06-01T02:05:00+00:00",
    )
    manager.check_game_start("Hades")
    manager.dependencies.history.record_history.assert_called_once_with(
        "Hades", "start", "auto_start", "skipped", reason="ambiguous_recency"
    )


def test_auto_restore_does_not_record_skip_history() -> None:
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T00:00:00+00:00",
        backup_modified_at="2026-06-01T02:05:00+00:00",
    )
    manager.check_game_start("Hades")
    manager.dependencies.history.record_history.assert_not_called()
```

**Gap B — no test uses Ludusavi's real `Z`-suffix timestamp format.** Every lifecycle test uses `+00:00`, but production `backupModifiedAt` values end in `Z` (e.g. `2026-05-10T00:00:00Z`). Python 3.12 `fromisoformat` handles `Z`, but nothing in the suite proves the lifecycle path does. Add:

```python
def test_backup_differs_auto_restore_with_zulu_suffix_backup_timestamp() -> None:
    """Ludusavi emits RFC3339 'Z'-suffixed timestamps; the direction check must parse them."""
    manager = _make_manager(
        recency="backup_differs",
        local_modified_at="2026-06-01T00:00:00+00:00",
        backup_modified_at="2026-06-01T02:05:00Z",
    )
    result = manager.check_game_start("Hades")
    assert result == {"status": "needed", "operation": "restore", "game": "Hades"}
```

**Gap C** is the missing `_timestamp_direction` pure tests — already covered by Finding 3.

These tests assert existing behavior, so they go straight to green (no RED phase needed — the TDD rule in `AGENTS.md` §9 exempts test-only additions). Verify each one actually exercises what it claims by temporarily breaking the code if in doubt.

**Commit:** `test(lifecycle): cover history recording, skip-on-restore, and Z-suffix timestamps for backup_differs`

---

### Finding 6 (COSMETIC — naming): constant name is misleading

**Where:** `py_modules/sdh_ludusavi/constants.py:27` — `RECENCY_DIFFERS_TIMEDELTA: float = 120.0`.

**Problem:** The plan named it `RECENCY_TIMESTAMP_MARGIN_SECONDS = 120`. The shipped name says "TIMEDELTA" but the value is a plain float of seconds compared against `.total_seconds()`; a future reader may pass a `datetime.timedelta` to it. Rename to the plan's name (units in the name, no false type hint):

1. In `constants.py`: rename to `RECENCY_TIMESTAMP_MARGIN_SECONDS: float = 120.0` (keep the existing comment).
2. Update the only consumer: `from .constants import RECENCY_TIMESTAMP_MARGIN_SECONDS` in `lifecycle.py` and its use in the `backup_differs` block.
3. `grep -rn RECENCY_DIFFERS_TIMEDELTA py_modules/ tests/` must return nothing afterward.

**Commit:** `refactor(constants): rename recency margin constant to state its units` (may be folded into the Finding 3 commit since `lifecycle.py` is already being edited there).

---

### Finding 7 (COSMETIC — documentation): `compare_recency` docstring omits the five-value return contract

**Where:** `py_modules/sdh_ludusavi/ludusavi.py:152-158`.

**Problem:** Plan Step 3b required the docstring to enumerate all five return values. The shipped docstring still only says the method "uses a restore preview". The protocol stub in `types.py` got the one-line contract, but the implementation — where a maintainer will actually look — did not. Replace the docstring with:

```python
        """
        Compare the local save recency against the latest Ludusavi backup.

        Returns one of:
            "no_backup"      - no backups exist for the game
            "local_current"  - backup and local save are identical
            "backup_newer"   - backup contains data absent locally (safe restore)
            "backup_differs" - backup and local both exist and differ; direction
                               unknown from this signal alone
            "ambiguous"      - preview failed or returned an unexpected shape
        """
```

**Commit:** fold into the Finding 1 commit (same file).

---

## Items reviewed and explicitly found acceptable (no action)

- **MagicMock-based manager tests instead of plan's service-level tests:** the plan suggested mirroring `tests/test_service.py` service construction; the commit unit-tests `GameLifecycleManager` directly. The logic under test lives entirely in the manager, the dependency seam (`LifecycleDependencies`) is the real production contract, and `test_service.py`'s untouched `ambiguous_recency` conflict test still provides the integration-level payload guarantee. Acceptable deviation.
- **`record_history` left at the call site instead of inside `_conflict_response`:** deviates from plan Step 5c but is arguably cleaner (pure payload builder, single call site). Keep as is; Finding 5 Gap A adds the missing assertion.
- **`backup_newer` checked before `local_current`** (plan ordered them the other way): both are exclusive string equality checks; order is immaterial.
- **Conflict payload key set:** verified identical to pre-change (`status, operation, game, reason, localLabel, backupLabel, localModifiedAt, backupModifiedAt, backupPath` via `service._conflict_metadata` normalization at `service.py:510-514`).
- **Margin semantics:** strictly-greater-than 120 s, matching plan ("local newer, within margin, missing, unparseable → conflict"). Edge case #5 test uses 30 s delta; the exact-boundary case gains a direct test via Finding 3.

## Quality gates to run after all fixes (every one must pass)

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run verify
grep -rn RECENCY_DIFFERS_TIMEDELTA py_modules/ tests/   # must be empty after Finding 6
```

Then write a session log to `docs/agent_conversations/` per `AGENTS.md` §15 and commit it.
