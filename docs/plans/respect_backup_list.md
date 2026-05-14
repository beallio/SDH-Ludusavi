# Plan: Respect Ludusavi's Backup List (Decision Filtering)

## Problem Definition
The plugin currently attempts to backup games that are present in Ludusavi's scan results even if they are deselected (ignored) in Ludusavi's configuration. This occurs because the plugin only filters by the presence of files or registry entries, ignoring the `decision` field in Ludusavi's API output.

## Architecture Overview
The plugin interacts with Ludusavi via `PyludusaviAdapter`. It maintains a list of manageable games in `LudusaviService`. Both components need to be aware of the `decision` field to properly respect user exclusions.

## Core Data Structures
No changes to data structures are required, but we will use the existing `decision` field from the Ludusavi API output (mapped via `pyludusavi`).

## Public Interfaces
No changes to public interfaces.

## Dependency Requirements
None beyond existing `pyludusavi`.

## Implementation Plan

### 1. Update Game Discovery
Modify `PyludusaviAdapter.refresh_statuses` in `py_modules/sdh_ludusavi/ludusavi.py` to filter out games where `decision` is `Ignored` or `Cancelled`.

### 2. Update Auto-Backup Logic
Modify `LudusaviService.handle_game_exit` in `py_modules/sdh_ludusavi/service.py` to check the `decision` field in the backup preview. If it's `Ignored` or `Cancelled`, skip the backup.

## Testing Strategy

### 1. Unit Test for Discovery
Create `tests/test_backup_list_filter.py` to verify that `refresh_statuses` correctly filters games based on the `decision` field.

### 2. Unit Test for Service Logic
Update `tests/test_service.py` or create a new test to verify that `handle_game_exit` respects the `decision` field in the preview.

## Verification
- Run `./run.sh uv run pytest tests/test_backup_list_filter.py`
- Run `./run.sh uv run pytest tests/test_service.py`
- Run all quality checks: `./run.sh uv run ruff check .`, `./run.sh uv run ty check py_modules/sdh_ludusavi/`, etc.
