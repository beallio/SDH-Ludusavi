# Local Implementation Plan: Resolve Last Operation Review Findings

This plan details the changes to address the code review findings identified in `/tmp/sdh_ludusavi/review_findings.md`.

## Proposed Changes

### Finding 1: Redundant String Splitting & Unsafe Direct Property Chaining

#### [MODIFY] [index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx#L1404-L1416)

**Problem:**
The JSX render block currently performs redundant string splitting operations on `selectedHistory.timestamp` and uses unsafe direct property chaining (`split('.')[0]`) without optional chaining inside the body:
```typescript
                    {selectedHistory.timestamp &&
                    selectedHistory.timestamp.split(/[T ]/)[1]?.split(".")[0] ? (
                      <div ...>
                        ({formatDateMDY(selectedHistory.timestamp)} {formatTime12h(selectedHistory.timestamp.split(/[T ]/)[1].split(".")[0])})
                      </div>
                    ) : null}
```

**Fix:**
We will replace this guard block with an Immediately Invoked Function Expression (IIFE) that executes block-scoped logic safely:
1. Performs an early return of `null` if `selectedHistory.timestamp` is falsy.
2. Performs the split safely.
3. Checks if `timePart` is valid using optional chaining (`parts[1]?.split(".")[0]`). If it's falsy, it returns `null`.
4. Renders the JSX cleanly, computing both formatted strings exactly once, eliminating redundant string splitting.

**Detailed Diff:**
```diff
-                    {selectedHistory.timestamp &&
-                    selectedHistory.timestamp.split(/[T ]/)[1]?.split(".")[0] ? (
-                      <div
-                        style={{
-                          fontSize: "12px",
-                          opacity: 0.65,
-                          marginTop: "2px",
-                          fontVariantNumeric: "tabular-nums"
-                        }}
-                      >
-                        ({formatDateMDY(selectedHistory.timestamp)} {formatTime12h(selectedHistory.timestamp.split(/[T ]/)[1].split(".")[0])})
-                      </div>
-                    ) : null}
+                    {(() => {
+                      if (!selectedHistory.timestamp) return null;
+                      const parts = selectedHistory.timestamp.split(/[T ]/);
+                      const timePart = parts[1]?.split(".")[0];
+                      if (!timePart) return null;
+
+                      return (
+                        <div
+                          style={{
+                            fontSize: "12px",
+                            opacity: 0.65,
+                            marginTop: "2px",
+                            fontVariantNumeric: "tabular-nums"
+                          }}
+                        >
+                          ({formatDateMDY(selectedHistory.timestamp)} {formatTime12h(timePart)})
+                        </div>
+                      );
+                    })()}
```

---

### Finding 2: Fragile Static Code Assertions in Tests

#### [MODIFY] [test_last_operation_date_display.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_last_operation_date_display.py#L4-L11)

**Problem:**
The test uses raw substring matching:
```python
    assert "function formatDateMDY" in source
    assert "formatDateMDY(selectedHistory.timestamp)" in source
```

**Fix:**
We will update this using regular expressions `re.search` which allows optional spaces (`\s*`) and word boundaries to keep tests resilient:
1. `re.search(r"function\s+formatDateMDY\s*\(", source)`: Matches `function formatDateMDY(...)` with any formatting spacing.
2. `re.search(r"formatDateMDY\s*\(\s*selectedHistory\.timestamp\s*\)", source)`: Matches `formatDateMDY(selectedHistory.timestamp)` with any spacing around parentheses or arguments.

**Detailed Diff:**
```diff
+import re
+
 def test_frontend_format_date_mdy_exists_and_is_used() -> None:
     source = Path("src/index.tsx").read_text(encoding="utf-8")
 
-    # Assert formatDateMDY helper is defined
-    assert "function formatDateMDY" in source
-
-    # Assert formatDateMDY is used on selectedHistory.timestamp
-    assert "formatDateMDY(selectedHistory.timestamp)" in source
+    # Use regular expressions to handle potential spacing/formatting variation
+    assert re.search(r"function\s+formatDateMDY\s*\(", source) is not None
+    assert re.search(r"formatDateMDY\s*\(\s*selectedHistory\.timestamp\s*\)", source) is not None
```

---

## Testing Strategy
1. Run `./run.sh pnpm run typecheck` to verify no type or compilation errors.
2. Run `./run.sh uv run pytest` to check the Python and static test suite.
