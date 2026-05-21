# Code Review Refactors

## Problem Definition
Four issues were identified in recent commits and reviews:
1. **Log Pollution in `_run_blocking`**: When `_run_blocking` is cancelled, it raises a `CancelledError` but the underlying thread's future completes in the background and sets an exception. Since the caller has cancelled, the future is never awaited, leading to "Future exception was never retrieved" warnings on garbage collection.
2. **Diagnostics Race Condition**: `service.py::_ludusavi` checks `_diagnostics_logged` outside of the double-checked locking block, allowing concurrent threads to spawn duplicate background logging processes.
3. **React State Memory Leak**: `index.tsx::loadInitial` executes background RPC resolutions for versions and commands without tracking mount-state checks, resulting in state setter calls on unmounted components or out-of-order race conditions.
4. **Clean Code styling**: Ad-hoc inline CSS properties are mixed in JSX status layouts instead of residing in the file's injected stylesheet.

## Architecture Overview
- **Future Exception Cleanups**: Attach a done callback to the future inside `_run_blocking` to consume the exception if the caller is cancelled.
- **Diagnostics Thread-Safety**: Protect `_diagnostics_logged` check and call under `self._adapter_lock` inside `service.py` to prevent duplicate diagnostics logs.
- **React Mount Tracking**: Use a React `useRef` to track component mount status in `src/index.tsx` and guard all state updates in `loadInitial`.
- **CSS Cleanups**: Replace inline styles in the status field and last operation elements with new CSS rules in the injected `qamPanelStyles`.

## Core Data Structures
No changes to persistent data structures.

## Public Interfaces
Public API signatures remain unchanged.

## Dependency Requirements
No new dependencies.

## Testing Strategy
- Run the full test suite to ensure no regressions.
- Specifically verify async execution and cancellation behavior.
- Validate that the type checker and linters pass.
