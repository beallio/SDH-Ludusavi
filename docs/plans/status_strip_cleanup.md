# Status Strip Cleanup

## Problem Definition

The autosync status strip is now working through a BrowserView surface, but the
frontend still carries diagnostic UI and older React/composition fallback code. Those
paths increase maintenance risk and make the production surface ambiguous.

## Architecture Overview

The production status strip should be BrowserView-only. Autosync lifecycle handlers
publish module-level status state, the BrowserView renders a self-contained
`data:text/html` document, and module-level timers hide running and result states.
React global components, portals, composition requests, and diagnostic surface cycling
are out of scope for production.

## Core Data Structures

- `AutoSyncStatusKind`: browser-rendered status state.
- `AutoSyncStatusSource`: lifecycle, RPC result, timeout, and hide provenance.
- `AutoSyncStatusState`: current BrowserView status, visibility, and provenance.
- `AutoSyncStatusBrowserViewOwner`: Decky/Steam wrapper shape normalized to usable
  BrowserView methods.

## Public Interfaces

No backend RPCs, persisted settings, dependencies, package metadata, or README usage
change. The Logs panel should retain log viewing only; it must not expose a status
strip debug button.

## Dependency Requirements

No dependency changes are required.

## Testing Strategy

Update frontend static tests to require the BrowserView-only production contract and
reject stale debug or fallback artifacts:

- no debug status button, diagnostic labels, diagnostic publisher, or surface mode type;
- no `createPortal`, React status strip component, `EUIComposition`, composition hook,
  or global component registration;
- BrowserView wrapper normalization and verbose logs remain required;
- lifecycle/RPC provenance logs remain required;
- `local_current` still maps to `has_backup`;
- module-level timers hide status on timeout and clear on hide/dismount.

Validation commands:

```bash
./run.sh uv run pytest tests/test_frontend_static.py
./run.sh pnpm run typecheck
./run.sh pnpm run build
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```
