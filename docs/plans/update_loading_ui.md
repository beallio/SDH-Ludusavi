# Plan: Update Frontend Loading UI

## Objective
Move the "Loading" status message that appears during initial load to be underneath the game selection dropdown, integrate it into the "Status:" row, and update its text and formatting.

## Key Files & Context
- `src/index.tsx`: Contains the `Content` component which renders the plugin UI.

## Implementation Steps

### 1. Update Status Row in `src/index.tsx`
Modify the status row (underneath the `DropdownItem`) to conditionally display "Loading game list..." in bold blue when the plugin is performing its initial load.

```tsx
        <PanelSectionRow>
          <div style={{ color: "#cbd5e1", fontSize: "14px", margin: "12px 0", padding: "0 4px" }}>
            <span style={{ color: "#64748b", fontWeight: "bold", marginRight: "8px" }}>Status:</span>
            {isBusy && busyLabel === "Loading" ? (
              <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Loading game list...</span>
            ) : (
              selectedStatus ? statusLabels[selectedStatus.status] : "No Ludusavi games found"
            )}
          </div>
        </PanelSectionRow>
```

### 2. Remove Redundant Loading Message
Remove the conditional block at the end of the "Sync" section that previously displayed the "Loading" message.

```tsx
        {isBusy && busyLabel === "Loading" ? (
          <PanelSectionRow>
            <div style={{ color: "#60a5fa", fontSize: "14px", marginTop: "12px", padding: "0 4px", fontWeight: 500 }}>
              {busyLabel ?? `Running ${operation.name ?? "operation"}`}
            </div>
          </PanelSectionRow>
        ) : null}
```

## Verification & Testing
- **Manual Verification**:
  - Open the plugin and observe the initial load.
  - The status should read "Status: Loading game list..." in bold blue.
  - Once loaded, it should transition to the normal game status (e.g., "Status: Backup ready").
  - Ensure no "Loading" message appears at the bottom of the Sync section.
- **Regression Testing**:
  - Verify that other busy labels (e.g., "Refreshing games", "Backup running") still work as intended (displayed as spinner buttons).
