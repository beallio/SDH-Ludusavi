# Implementation Plan: Fix `compare_recency` Direction Safety (Review Finding B1)

**Plan file destination in repo:** `docs/plans/2026-06-09_fix_compare_recency_direction.md`
**Branch:** create from `refactor/code-quality-boundaries` (or current working branch), named `fix/compare-recency-direction`
**Estimated scope:** 2 backend modules, 1 constants entry, ~6 new tests, 1 existing test updated, 1 README sentence. **No frontend code changes.**

---

## 1. Problem Statement (read fully before editing anything)

`PyludusaviAdapter.compare_recency()` in `py_modules/sdh_ludusavi/ludusavi.py` runs a **restore preview** and inspects the per-game `change` field. The current mapping is:

| `change` value | Current return | Meaning of the signal |
|---|---|---|
| `"Same"` | `"local_current"` | Backup and local save are identical |
| `"New"` | `"backup_newer"` | Backup contains files that do **not exist** locally |
| `"Different"` | `"backup_newer"` | Backup and local save **both exist and differ** — direction is **unknown** |
| anything else / error | `"ambiguous"` | Unknown |

The bug: `"Different"` does **not** mean the backup is newer. It only means the two sides differ. If the user produced a newer local save outside the plugin's view (played in Desktop Mode, game crashed before the exit backup, played offline), the next Game Mode launch classifies the situation as `backup_newer`, and `lifecycle.check_game_start()` returns `{"status": "needed", "operation": "restore"}`, which causes the frontend to **automatically restore the older backup over the newer local save with no prompt**. This is silent data loss.

### Target behavior (the contract you are implementing)

1. `"New"` → keep auto-restoring. No local save exists, so restoring cannot destroy local progress. **Unchanged.**
2. `"Same"` → keep skipping (`local_current`). **Unchanged.**
3. `"Different"` → **new behavior.** The adapter reports a new value `"backup_differs"`. The lifecycle layer then corroborates direction using timestamps it can already obtain (`conflict_metadata`):
   - If the **backup timestamp is newer than the local timestamp by more than a safety margin** → auto-restore (this is the legitimate "synced from another device" case).
   - In **every other case** (local newer, within margin, either timestamp missing or unparseable) → return the existing **conflict** payload so the user chooses via the already-built `ConflictResolutionModal`. The modal's dismiss action already resolves to "skip", which is safe.
4. Errors / unknown change values → `"ambiguous"` → conflict payload. **Unchanged.**

### Invariants you must not break

- **Do not change** the RPC response shapes. `check_game_start` must still return exactly one of: a skip payload, `{"status": "needed", "operation": "restore", "game": ...}`, or the conflict payload with keys `status, operation, game, reason, localLabel, backupLabel, localModifiedAt, backupModifiedAt, backupPath`.
- **Reuse the existing reason string `"ambiguous_recency"`** for all new conflict cases. Do NOT invent a new reason string. This string is consumed by `src/formatting/operationText.ts:27,67`, `src/surfaces/autoSyncStatusSurface.tsx:202`, `tests/test_status_flow_diagram.py:34,59`, and the README glossary. Reusing it means zero frontend changes.
- **Do not modify** `resolve_game_start_conflict`, `restore_game_on_start`, `check_game_exit`, `backup_game_on_exit`, or anything in `src/`.
- Follow the repo's TDD protocol (`AGENTS.md` §9, enforced by `scripts/check_tdd.sh` in pre-commit): **write each failing test, commit nothing yet, then implement, then verify green.** Test changes and implementation must land per the repo's existing commit conventions.

---

## 2. Files You Will Touch (exhaustive list)

| File | Action |
|---|---|
| `py_modules/sdh_ludusavi/constants.py` | Add one constant |
| `py_modules/sdh_ludusavi/ludusavi.py` | Modify `compare_recency`; improve `get_conflict_metadata` backup-timestamp selection |
| `py_modules/sdh_ludusavi/lifecycle.py` | Add timestamp helpers + `_conflict_response`; rework the recency branch in `check_game_start` |
| `py_modules/sdh_ludusavi/types.py` | Docstring only on the `LudusaviAdapter.compare_recency` protocol method |
| `tests/test_ludusavi.py` | Update 1 test (line ~190); add 2 tests |
| `tests/test_recency_direction.py` | **New file** — lifecycle direction tests |
| `tests/test_exception_boundaries.py` | No change expected; run to confirm |
| `README.md` | One-sentence clarification in "Understanding Status Messages" |
| `docs/plans/2026-06-09_fix_compare_recency_direction.md` | This plan, committed per repo convention |
| `docs/agent_conversations/` | Session log per `AGENTS.md` §15 at the end |

Files that reference `compare_recency` but need **no edits** (they define fake adapters returning fixed strings; verify they still pass): `tests/test_service.py`, `tests/test_matching.py`, `tests/test_compatibility.py`, `tests/test_issue_1_matching.py`, `tests/test_issue_2_state_load.py`, `tests/test_issue_3_refresh_robustness.py`, `tests/test_issue_5_env_logging.py`, `tests/test_issue_10_sanitization.py`, `tests/test_last_operation_sync.py`.

---

## 3. Step-by-Step Implementation

### Step 0 — Environment and baseline

```bash
cd <repo-root>
./run.sh uv sync
./run.sh uv run pytest          # must be green before you start; record the count
pnpm install --frozen-lockfile --ignore-scripts
```

If the baseline is not green, **stop and report**; do not proceed on a red baseline.

### Step 1 — Add the margin constant

**File:** `py_modules/sdh_ludusavi/constants.py`
Append at the end of the file:

```python
# Minimum amount (seconds) by which the latest backup's timestamp must exceed
# the local save's newest mtime before an automatic restore is allowed when a
# restore preview reports "Different". Absorbs cross-device clock skew and
# filesystem timestamp granularity. Anything inside this margin is treated as
# a conflict and routed to the user.
RECENCY_TIMESTAMP_MARGIN_SECONDS = 120
```

### Step 2 — RED: update + add adapter tests

**File:** `tests/test_ludusavi.py`

2a. Find the test at line ~190:

```python
def test_compare_recency_returns_backup_newer_when_restore_preview_shows_changes() -> None:
```

Its fake currently uses `restore_data={"games": {"Hades": {"change": "Different"}}}` and asserts `== "backup_newer"`. **Rewrite it** to:

```python
def test_compare_recency_returns_backup_differs_when_restore_preview_shows_different() -> None:
    adapter = _make_adapter(
        backups_data={"games": {"Hades": {"backups": [{"when": "2026-01-01T00:00:00Z"}]}}},
        restore_data={"games": {"Hades": {"change": "Different"}}},
    )
    assert adapter.compare_recency("Hades") == "backup_differs"
```

(Match the existing helper/fixture names used by the neighboring tests in this file — read the surrounding `_make_adapter`-style helper first and mirror its exact signature; do not invent a new fixture style.)

2b. Add directly below it:

```python
def test_compare_recency_returns_backup_newer_when_restore_preview_shows_new() -> None:
    adapter = _make_adapter(
        backups_data={"games": {"Hades": {"backups": [{"when": "2026-01-01T00:00:00Z"}]}}},
        restore_data={"games": {"Hades": {"change": "New"}}},
    )
    assert adapter.compare_recency("Hades") == "backup_newer"


def test_get_conflict_metadata_uses_newest_backup_timestamp() -> None:
    adapter = _make_adapter(
        backups_data={
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
        # backup preview side returns no files; localModifiedAt will be absent
        backup_data={"games": {}},
    )
    metadata = adapter.get_conflict_metadata("Hades")
    assert metadata["backupModifiedAt"] == "2026-03-02T00:00:00Z"
```

Run and confirm these fail for the right reason:

```bash
./run.sh uv run pytest tests/test_ludusavi.py -k "compare_recency or conflict_metadata" -x
```

Expected failures: `backup_differs` test fails because adapter returns `backup_newer`; metadata test fails because the adapter currently takes `backups[0]["when"]`.

### Step 3 — GREEN: adapter changes

**File:** `py_modules/sdh_ludusavi/ludusavi.py`

3a. In `compare_recency` (currently lines ~152–186), replace this block:

```python
            if change == "Same":
                return "local_current"
            if change in ("New", "Different"):
                # In a restore context, New/Different implies the backup has
                # data that should be applied to local.
                return "backup_newer"
```

with:

```python
            if change == "Same":
                return "local_current"
            if change == "New":
                # No local save exists for these entries, so restoring cannot
                # overwrite local progress. Safe to treat as backup-newer.
                return "backup_newer"
            if change == "Different":
                # Backup and local save both exist and differ. The restore
                # preview does NOT indicate which side is newer; the caller
                # must corroborate direction (timestamps) or ask the user.
                return "backup_differs"
```

3b. Update the method docstring to document the full return contract:

```python
        """
        Compare the local save recency against the latest Ludusavi backup.

        Returns one of:
            "no_backup"     - no backups exist for the game
            "local_current" - backup and local save are identical
            "backup_newer"  - backup contains data absent locally (safe restore)
            "backup_differs"- backup and local both exist and differ; direction
                              unknown from this signal alone
            "ambiguous"     - preview failed or returned an unexpected shape
        """
```

3c. In `get_conflict_metadata`, replace the first try-block's backup-timestamp selection. Current code:

```python
            backups = game_backups.get("backups") or []
            if backups:
                latest_backup = backups[0]
                if isinstance(latest_backup, dict):
                    metadata["backupModifiedAt"] = latest_backup.get("when")
```

Replace with:

```python
            backups = game_backups.get("backups") or []
            newest_when = _newest_backup_when(backups)
            if newest_when is not None:
                metadata["backupModifiedAt"] = newest_when
```

3d. Add this module-level helper near `_games_from_output` at the bottom of `ludusavi.py`:

```python
def _newest_backup_when(backups: object) -> str | None:
    """
    Return the lexicographically greatest RFC3339 "when" timestamp across all
    full backups and their differential children. Ludusavi emits UTC RFC3339
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

> Note: lexicographic `max` is only valid because all values come from Ludusavi in the same `YYYY-MM-DDTHH:MM:SSZ` UTC shape. The lifecycle layer (Step 5) re-parses with `datetime` anyway, so a malformed string here only affects modal display, never the restore decision.

3e. **File:** `py_modules/sdh_ludusavi/types.py` — on the `LudusaviAdapter` protocol's `compare_recency` line, add a short docstring or trailing comment stating the five-value contract from 3b, so fake adapters in tests have a single source of truth.

Re-run Step 2's command; both new adapter tests must pass. Then run the full adapter file:

```bash
./run.sh uv run pytest tests/test_ludusavi.py tests/test_exception_boundaries.py
```

### Step 4 — RED: lifecycle direction tests (new file)

**File (create):** `tests/test_recency_direction.py`

Before writing it, open `tests/test_service.py` lines ~880–1030 and copy its existing pattern for constructing `SDHLudusaviService` with a fake adapter and `tmp_path` storage (`test_check_game_start_reports_conflict_for_ambiguous_recency` at line ~1009 is the closest template — mirror its setup exactly, including how the fake adapter exposes `recency`, `get_conflict_metadata`, `refresh_statuses`, `backup`, `restore`). Then implement these tests:

```python
from __future__ import annotations

from pathlib import Path

# Mirror the imports/fixtures used by tests/test_service.py for service construction.


def _service_with_recency(tmp_path: Path, recency: str, metadata: dict):
    """Build a service whose fake adapter returns `recency` for Hades and
    `metadata` from get_conflict_metadata. Copy the construction pattern from
    test_service.py; ensure Hades is present with has_backup=True and that
    auto_sync is enabled via service.set_auto_sync_enabled(True)."""
    ...


def test_check_game_start_restores_when_backup_differs_and_backup_clearly_newer(tmp_path: Path) -> None:
    service = _service_with_recency(
        tmp_path,
        "backup_differs",
        {
            "localModifiedAt": "2026-06-01T00:00:00+00:00",
            "backupModifiedAt": "2026-06-01T01:00:00Z",   # 1h newer > 120s margin
            "backupPath": "/backups",
        },
    )
    result = service.check_game_start("Hades")
    assert result == {"status": "needed", "operation": "restore", "game": "Hades"}


def test_check_game_start_conflicts_when_backup_differs_and_local_newer(tmp_path: Path) -> None:
    service = _service_with_recency(
        tmp_path,
        "backup_differs",
        {
            "localModifiedAt": "2026-06-01T02:00:00+00:00",  # local is newer
            "backupModifiedAt": "2026-06-01T01:00:00Z",
            "backupPath": "/backups",
        },
    )
    result = service.check_game_start("Hades")
    assert result["status"] == "conflict"
    assert result["reason"] == "ambiguous_recency"
    assert result["localModifiedAt"] == "2026-06-01T02:00:00+00:00"
    assert result["backupModifiedAt"] == "2026-06-01T01:00:00Z"


def test_check_game_start_conflicts_when_backup_differs_within_margin(tmp_path: Path) -> None:
    service = _service_with_recency(
        tmp_path,
        "backup_differs",
        {
            "localModifiedAt": "2026-06-01T01:00:00+00:00",
            "backupModifiedAt": "2026-06-01T01:01:00Z",  # only 60s newer < 120s margin
            "backupPath": "/backups",
        },
    )
    assert service.check_game_start("Hades")["status"] == "conflict"


def test_check_game_start_conflicts_when_backup_differs_and_timestamps_missing(tmp_path: Path) -> None:
    service = _service_with_recency(
        tmp_path,
        "backup_differs",
        {"localModifiedAt": None, "backupModifiedAt": None, "backupPath": None},
    )
    assert service.check_game_start("Hades")["status"] == "conflict"


def test_check_game_start_conflicts_when_backup_differs_and_timestamps_unparseable(tmp_path: Path) -> None:
    service = _service_with_recency(
        tmp_path,
        "backup_differs",
        {"localModifiedAt": "not-a-date", "backupModifiedAt": "also-bad", "backupPath": None},
    )
    assert service.check_game_start("Hades")["status"] == "conflict"


def test_check_game_start_still_restores_for_backup_newer(tmp_path: Path) -> None:
    service = _service_with_recency(tmp_path, "backup_newer", {})
    assert service.check_game_start("Hades") == {
        "status": "needed",
        "operation": "restore",
        "game": "Hades",
    }


def test_conflict_records_skipped_history_with_ambiguous_recency(tmp_path: Path) -> None:
    service = _service_with_recency(
        tmp_path,
        "backup_differs",
        {"localModifiedAt": "2026-06-01T02:00:00+00:00", "backupModifiedAt": "2026-06-01T01:00:00Z"},
    )
    service.check_game_start("Hades")
    history = service.get_game_history()["Hades"]
    assert history["last_skip"]["reason"] == "ambiguous_recency"
```

Also add two **pure-function** tests at the bottom of the same file (they will target the helper you create in Step 5):

```python
from sdh_ludusavi.lifecycle import _timestamp_direction


def test_timestamp_direction_backup_newer_beyond_margin() -> None:
    assert _timestamp_direction(
        "2026-06-01T00:00:00+00:00", "2026-06-01T00:05:00Z", 120
    ) == "backup_newer"


def test_timestamp_direction_unknown_on_missing_or_bad_input() -> None:
    assert _timestamp_direction(None, "2026-06-01T00:05:00Z", 120) == "unknown"
    assert _timestamp_direction("2026-06-01T00:00:00+00:00", None, 120) == "unknown"
    assert _timestamp_direction("garbage", "2026-06-01T00:05:00Z", 120) == "unknown"
    assert _timestamp_direction(123, "2026-06-01T00:05:00Z", 120) == "unknown"  # type: ignore[arg-type]
```

Run and confirm they fail (import error for `_timestamp_direction`, and `backup_differs` falling into the generic conflict path will make the *restore* test fail):

```bash
./run.sh uv run pytest tests/test_recency_direction.py -x
```

### Step 5 — GREEN: lifecycle changes

**File:** `py_modules/sdh_ludusavi/lifecycle.py`

5a. Add imports at the top (keep existing imports intact):

```python
from datetime import datetime, timezone
from typing import Literal

from .constants import RECENCY_TIMESTAMP_MARGIN_SECONDS
```

5b. Add two module-level helpers above the `GameLifecycleManager` class:

```python
def _parse_iso_utc(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing 'Z') to aware UTC.
    Returns None for anything that is not a parseable non-empty string."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_direction(
    local_modified_at: object,
    backup_modified_at: object,
    margin_seconds: float,
) -> Literal["backup_newer", "not_newer", "unknown"]:
    """Decide restore direction from conflict-metadata timestamps.
    'backup_newer' only when the backup timestamp exceeds the local timestamp
    by strictly more than margin_seconds. Missing/unparseable input -> 'unknown'."""
    local = _parse_iso_utc(local_modified_at)
    backup = _parse_iso_utc(backup_modified_at)
    if local is None or backup is None:
        return "unknown"
    if (backup - local).total_seconds() > margin_seconds:
        return "backup_newer"
    return "not_newer"
```

5c. Inside `GameLifecycleManager`, add a private method that factors out the existing conflict payload (currently inlined at the end of `check_game_start`, lines ~76–89):

```python
    def _conflict_response(
        self, game_name: str, metadata: dict[str, object]
    ) -> dict[str, object]:
        self.dependencies.history.record_history(
            game_name, "start", "auto_start", "skipped", reason="ambiguous_recency"
        )
        return {
            "status": "conflict",
            "operation": "restore",
            "game": game_name,
            "reason": "ambiguous_recency",
            "localLabel": "Keep Local Save",
            "backupLabel": "Restore Backup Save",
            **metadata,
        }
```

The `**metadata` spread must produce exactly the same keys as today (`localModifiedAt`, `backupModifiedAt`, `backupPath`) — it will, because `_conflict_metadata` in `service.py` already normalizes to those three keys. Do not change `service._conflict_metadata`.

5d. In `check_game_start`, replace everything from `if recency == "backup_newer":` down to the end of the method with:

```python
        if recency == "local_current":
            return self.dependencies.skip("start", game.name, "local_current")

        if recency == "backup_newer":
            return {"status": "needed", "operation": "restore", "game": game.name}

        metadata = self.dependencies.conflict_metadata(game.name)

        if recency == "backup_differs":
            direction = _timestamp_direction(
                metadata.get("localModifiedAt"),
                metadata.get("backupModifiedAt"),
                RECENCY_TIMESTAMP_MARGIN_SECONDS,
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

        return self._conflict_response(game.name, metadata)
```

Notes for the agent:
- The ordering above intentionally checks `local_current` first; preserve the existing `skip` semantics exactly.
- `conflict_metadata` is fetched **once** and reused for both the direction decision and the conflict payload — do not call it twice.
- `conflict_metadata` runs outside the operation lock today (it is invoked after `run_locked("start_check", ...)` returns); this plan deliberately keeps that existing pattern. Do not wrap it in `run_locked`.
- `"ambiguous"`, and any future unknown recency strings, fall through to `_conflict_response` — same as current behavior.

5e. Run:

```bash
./run.sh uv run pytest tests/test_recency_direction.py tests/test_service.py tests/test_ludusavi.py
```

All must pass. `test_check_game_start_reports_conflict_for_ambiguous_recency` in `test_service.py` must pass **unmodified** — if it fails, your `_conflict_response` payload diverged from the original; diff against the pre-change payload keys/values.

### Step 6 — REFACTOR / verification sweep

6a. Confirm no stale mapping remains:

```bash
grep -rn '"New", "Different"' py_modules/ && echo "FAIL: old tuple still present" || echo OK
grep -rn 'backup_differs' py_modules/ tests/   # expect: ludusavi.py, lifecycle.py, types.py docstring, the new/updated tests
```

6b. Full gates (every one must pass; these mirror CI and pre-commit):

```bash
./run.sh uv run ruff check .
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run verify
```

`pnpm run verify` is required even though no frontend files changed — it is part of the repo's commit gate and confirms the frontend types/tests are unaffected.

### Step 7 — Documentation

7a. **README.md**, section "Understanding Status Messages": after the existing line

> **Skipped — recency is ambiguous**: The plugin couldn't determine which save is newer and will prompt you to choose.

append a sentence so the user-facing contract matches the new behavior:

> This also occurs when your local save and the backup have both changed (for example, after playing in Desktop Mode); the plugin only restores automatically when the backup is clearly newer, and otherwise pauses the launch so you can choose.

7b. Commit this plan file to `docs/plans/2026-06-09_fix_compare_recency_direction.md` and write the session log JSON to `docs/agent_conversations/` following the schema used by existing entries (fields: `date`, `task_objective`, `files_modified`, `tests_added`, `design_decisions`, `results`).

---

## 4. Edge Cases — Required Behavior Table

The agent must ensure the implementation + tests cover each row. Rows marked ✅test must have an automated test from Steps 2/4.

| # | Scenario | Recency | Timestamps | Outcome | Test |
|---|---|---|---|---|---|
| 1 | First sync to a fresh device | `backup_newer` (`New`) | n/a | auto-restore | ✅ |
| 2 | Normal relaunch, nothing changed | `local_current` | n/a | skip `local_current` | existing |
| 3 | Save synced from another device | `backup_differs` | backup − local > 120 s | auto-restore | ✅ |
| 4 | Played in Desktop Mode since last backup | `backup_differs` | local ≥ backup | **conflict modal** | ✅ |
| 5 | Both sides changed ~simultaneously | `backup_differs` | |Δ| ≤ 120 s | **conflict modal** | ✅ |
| 6 | Ludusavi gave no file paths / mtimes unreadable | `backup_differs` | localModifiedAt is None | **conflict modal** | ✅ |
| 7 | Corrupt timestamp strings | `backup_differs` | unparseable | **conflict modal** | ✅ |
| 8 | Preview failed / unknown change value | `ambiguous` | n/a | conflict modal | existing |
| 9 | No backups exist | `no_backup` (via `has_backup` skip earlier) | n/a | skip `no_backup` | existing |
| 10 | Differential backup is the newest artifact | n/a | child `when` > parent `when` | modal shows child timestamp; direction uses it | ✅ (Step 2b metadata test) |

---

## 5. Acceptance Criteria (all must hold)

1. `./run.sh uv run pytest` passes with the new tests included; no previously passing test was deleted or weakened (the one test in `tests/test_ludusavi.py` is *renamed and retargeted*, which is the intended behavioral change).
2. `ruff check`, `ruff format` (no diff), `ty check`, and `pnpm run verify` all pass.
3. `grep -rn '"New", "Different"' py_modules/` returns nothing.
4. No file under `src/` was modified (`git status` shows only the files listed in §2).
5. `check_game_start`'s three response shapes are byte-for-byte compatible with the previous contract (verified by the untouched `test_service.py` conflict test).
6. Manual spot-check (if a Deck/dev environment is available — optional, do not block on it): with auto-sync on, modify a tracked game's save file locally after its last backup, launch the game in Game Mode, and confirm the conflict modal appears instead of an automatic restore.

## 6. Out of Scope — Do NOT do these

- Do not add timeouts, locks, or threading changes (those are separate findings B2/B3).
- Do not modify `pyludusavi` (vendored dependency) — all changes live in `sdh_ludusavi`.
- Do not change the conflict modal, status-strip states, notification text, or any frontend reason-string handling.
- Do not make the 120 s margin user-configurable in this change.
- Do not "improve" `_run_blocking`, `service.py` property shims, or anything else you notice along the way. One change, one plan.

## 7. Rollback

The change is two pure-logic edits behind existing response contracts. Revert by `git revert` of the commits from this plan; no state-file, settings, or schema migration is involved, and no persisted data format changes.
