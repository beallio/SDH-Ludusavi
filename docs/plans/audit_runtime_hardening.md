# Ludusavi Audit Runtime Hardening

## Problem Definition

The audit in `/tmp/ludusavi_audit_issues.md` identified backend state-safety,
cache invalidation, state-path fallback, frontend lifecycle, process-tree signaling,
async helper, and fuzzy matching concerns. Baseline verification before planning was
green on `main` with `./run.sh uv run pytest -q` reporting `217 passed`.

## Audit Triage

Valid and high-value:

- Issue 1: `_match_game` can trigger `_refresh_statuses_unlocked()` outside refresh
  serialization.
- Issue 2: `_save_state()` uses one temp path and no write lock.
- Issue 4: `_state_path()` can fail before falling back when the primary Decky state
  directory is unusable.
- Issue 5: frontend lifecycle handlers can surface unhandled promise rejections.

Valid and medium-value:

- Issue 3: empty installed app IDs normalize to `None`, so an all-games-uninstalled
  marker can miss cache invalidation.
- Issue 7: process-tree signaling spawns one `ps` subprocess per visited process.
- Issue 9: adapter config-marker failures can return `None`, which the service can
  confuse with a stable cache marker.

Partially valid:

- Issue 6: the custom wake pipe in `_run_blocking` is unnecessary, but a bare
  `run_in_executor` replacement would discard current cancellation logging,
  context propagation, and thread-safe completion behavior.
- Issue 8: four-character configured game names such as `Doom` should match longer
  launcher names, but a blanket `>= 4` fuzzy rule would weaken the current
  false-positive guard.

## Architecture Overview

Implement these fixes on `fix/audit-runtime-hardening` using the implementer workflow.
Keep all compatibility work inside first-party SDH-ludusavi code and do not modify
vendored or upstream packages.

Use atomic commits by behavior area:

1. `fix(service): serialize state and cache refreshes`
2. `fix(cache): handle empty app ids and config marker failures`
3. `fix(main): fall back from unusable state directories`
4. `fix(frontend): handle lifecycle rpc failures`
5. `perf(service): snapshot process tree before signaling`
6. `refactor(main): remove redundant run blocking wake pipe`
7. `fix(matching): support short configured game names safely`

## Core Data Structures

- Add a reentrant service state lock for shared state snapshots, state persistence,
  cache mutation, and lazy match refresh coordination.
- Preserve the existing `Settings`, notification settings, history payload, and
  backend RPC response shapes.
- Treat normalized empty installed app IDs as `""`, not `None`.
- Treat unreadable Ludusavi config markers as refresh-required without making every
  normal fast QAM open force a scan.

## Public Interfaces

No new backend RPCs, frontend callables, settings fields, or dependency changes are
planned. The fixes harden existing behavior.

Visible behavior changes:

- Lifecycle RPC failures should be logged and surfaced as failed sync state instead
  of unhandled promise rejections.
- If every Steam app ID disappears, cache invalidation should refresh the game list.
- If the primary Decky state directory is unusable, the plugin should log a warning
  and use the existing fallback state path.
- Four-character configured game names can match longer launcher names only when the
  short side is the configured Ludusavi game and the match is boundary-safe.

## Testing Strategy

Add failing tests first, then implement the minimal fixes.

Backend service tests:

- Concurrent empty-cache `_match_game` calls trigger one refresh and do not corrupt
  shared cache maps.
- Concurrent settings/history saves do not collide on the temp state file.
- `refresh_games(installed_app_ids="")` invalidates a stale installed-app marker and
  persists `""`.
- An adapter config marker returning `None` after a cached `None` still forces a
  refresh when the marker is unavailable.
- Process-tree signaling shells out to `ps` once, preserves root/child signal order,
  and falls back to the root PID when `ps` fails.
- `Doom v1.0` can fuzzy-match configured `Doom`, while existing short generic cases
  such as `Game` remain unmatched.

Main backend tests:

- `_state_path()` falls back and logs a warning when primary directory setup raises
  `OSError`.
- `_run_blocking` keeps current cancellation and thread-safe completion behavior
  while no longer using `os.pipe`, `add_reader`, or `remove_reader`.

Frontend static tests:

- `handleAppStart` and `handleAppExit` wrap lifecycle RPC work in explicit catches.
- process resume is guarded in its own catch.
- failed lifecycle exceptions hide or complete the auto-sync status strip and log the
  error.

Validation:

- `./run.sh uv run pytest tests/test_service.py tests/test_main.py tests/test_matching.py tests/test_frontend_static.py`
- `./run.sh pnpm run typecheck`
- `./run.sh uv run ruff check . --fix`
- `./run.sh uv run ruff format .`
- `./run.sh uv run ty check py_modules/sdh_ludusavi/`
- `./run.sh uv run pytest`
- `./run.sh pnpm run verify`

## Closeout

- Record a session log under `docs/agent_conversations/`.
- Run the implementer review gate only after disclosing the third-party checkout
  review to the user and receiving approval.
- Merge back to `main` only after all validation passes.
