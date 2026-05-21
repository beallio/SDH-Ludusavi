# Plan: Last Operation Layout Revision

## Problem Definition
The current "Last Operation" display inside the Decky Loader plugin side panel has centered text, is difficult to scan quickly, does not follow the native Decky/SteamOS-style read-only status layout, and has a colon in the label. We need a clean, stable left/right anchored display that keeps the timestamp secondary, truncates long operation results nicely with ellipsis, and behaves as a read-only element.

## Architecture Overview
The styling and components are located in the main frontend plugin file (`src/index.tsx`). We will update:
1. The CSS styles injected into the panel (`qamPanelStyles`).
2. The JSX inside `src/index.tsx` for the "Last Operation" field (label, padding, width, custom flex classes).
3. The translation mapping from backend `GameOperationHistoryEntry` values into readable user-facing copy.

## Core Data Structures
We use the existing `GameOperationHistoryEntry` structure:
```typescript
type GameOperationHistoryEntry = {
  operation: "backup" | "restore" | "start" | "exit";
  trigger: "manual_backup" | "manual_restore" | "auto_start" | "auto_exit";
  status: "backed_up" | "restored" | "skipped" | "failed";
  reason: string | null;
  message: string | null;
  timestamp: string;
};
```

## Public Interfaces
No new public APIs. We will define a helper function `getLastOperationText(status: string, reason: string | null): string` internally in `src/index.tsx`.

## Dependency Requirements
No new dependencies. Uses existing `@decky/ui` components (especially `Field` and `PanelSectionRow`).

## Testing Strategy
We will update the static frontend assertions in `tests/test_frontend_static.py` to match the revised label, layout properties, classes, and structure.
We will then run all project quality checks (type checking, ruff linting, and pytests).
