# Status Update Bar Refinement

## Objective
Refine the visual presentation of the Ludusavi Auto-Sync status update bar by adjusting its vertical positioning, changing its normal primary icon color to Steam Blue, retaining a distinct warning/action color for `needs_backup`, and horizontally centering the icon plus text as one group on the screen.

## Key Files & Context
- **Target File:** `src/index.tsx`
- **Context:** The status bar is rendered as an HTML document injected into a Steam Deck BrowserView. Its bounds are calculated dynamically in `getAutoSyncStatusBounds()`, and its HTML structure is defined in `renderAutoSyncStatusHtml()`. The canonical behavior contract lives in `docs/specs/custom_status_bar_ui.md` and should be revised with the new centered visual contract before runtime code changes.

## Diagram: Target Layout
```text
+-------------------------------------------------------------+
|                                                             |
|                       (Main Screen)                         |
|                                                             |
|                                                             |
|                                                             |
+-------------------------------------------------------------+
|                  [Icon] Status Text                         | <- Status Bar (Centered group)
+-------------------------------------------------------------+
|                       (Bottom Padding)                      | <- Offset
+-------------------------------------------------------------+
```

## Implementation Plan

### Phase 1: Adjust Bounds (Padding)
We will introduce a vertical offset to ensure the status bar does not sit flush against the absolute bottom edge of the screen, improving readability on the Deck.

**Target File:** `src/index.tsx`
**Function:** `getAutoSyncStatusBounds()`

**Code Change Example:**
```typescript
function getAutoSyncStatusBounds() {
  // ...
  const width = Math.round(rawWidth);
  const height = Math.round(24 * pixelRatio);
  const bottomOffset = 48; // CSS pixel bottom offset for BrowserView bounds

  return {
    x: 0,
    y: Math.max(0, Math.round(rawHeight - height - bottomOffset)), // Subtract offset
    width,
    height,
    pixelRatio
  };
}
```

### Phase 2: Update HTML and CSS
We will modify the injected HTML string to center the icon plus text as one group and apply explicit state colors:

- Running and success states use Steam Blue (`#66c0f4`).
- `needs_backup` retains a distinct warning/action color (`#f59e0b`).
- `error` remains red (`#ef4444`).

**Target File:** `src/index.tsx`
**Function:** `renderAutoSyncStatusHtml()`

**Code Change Example:**
```typescript
function renderAutoSyncStatusHtml(state: AutoSyncStatusState) {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
/* ... existing basic styles ... */
.bar {
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center; /* Center the icon plus text as one group */
  background: rgba(0, 0, 0, 0.34);
  border-top: 1px solid rgba(255, 255, 255, 0.10);
  padding: 0 18px;
  box-sizing: border-box;
}
.text { display: flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-width: 245px; }
.icon { 
  width: 18px; 
  height: 18px; 
  display: inline-flex; 
  align-items: center; 
  justify-content: center; 
  color: ${autoSyncStatusIconColor(state.status)};
}
</style>
</head>
<body>
<div class="bar">
  <div class="text"><span class="icon">${iconSvgForAutoSyncStatus(state.status)}</span>${autoSyncStatusText[state.status]}</div>
</div>
</body>
</html>`;
}
```

## Verification & Testing
1. **Red static test:** Update `tests/test_frontend_static.py` to require the new centered visual contract: `bottomOffset = 48`, centered `.bar`, centered stable-width `.text`, Steam Blue normal color, warning/action `needs_backup` color, and no `space-between`.
2. **Spec update:** Update `docs/specs/custom_status_bar_ui.md` with the same color and centering contract.
3. **Compile:** Run the TypeScript compiler through the project wrapper to ensure `src/index.tsx` compiles without syntax errors.
4. **Launch Plugin:** Deploy the updated plugin to a Decky environment.
5. **Trigger Status:** Trigger a Ludusavi backup operation (e.g., launching/exiting a game).
6. **Visual Inspection:**
    - Verify the status bar appears above the very bottom edge of the screen (padding applied).
    - Verify the icon plus text are centered horizontally as one group.
    - Verify running/success icons are Steam Blue (`#66c0f4`).
    - Verify `needs_backup` is a distinct warning/action color (`#f59e0b`).
    - Verify errors remain red (`#ef4444`).
    - Verify the strip does not overlap SteamOS bottom action hints or game overlay chrome.

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
