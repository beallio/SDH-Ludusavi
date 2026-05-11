# UI Refinement - Mockup Integration

## Objective
Update the plugin's frontend UI to match the layout and features provided in the user's mockup, ensuring compliance with Decky Loader standards (icons, components, and behavior).

## Key Files & Context
- `src/index.tsx`: The main frontend component.
- `react-icons/fa`: Source for Decky-compliant icons.

## Proposed Solution

### Layout Changes
- **Header**: Add a header section with the `FaDatabase` icon and "SDH-ludusavi" title.
- **Sync Section**:
  - Keep "Automatic Sync" as the toggle label (per user request).
  - Use `DropdownItem` (a native Decky UI component) to ensure it is visually inline and consistent with other Decky Loader elements.
  - **New Status Row**: Add a dedicated row showing "Status: <Current Status>" under the dropdown.
  - Action Buttons: Ensure "Refresh Games", "Force Backup", and "Force Restore" match the mockup's order and disabling logic (Restore is only enabled if `has_backup` is true).
- **Versions Section**: Keep the "SDH-ludusavi" and "Ludusavi" versions. (Note: `rclone` remains removed as per previous bugfix).
- **Logs Section**: Rename "Show Logs" to "View Logs" and keep the `showModal(<LogModal />)` behavior.

### Component Mapping
- Mockup `ButtonItem` -> Decky UI `ButtonItem`.
- Mockup `Toggle` -> Decky UI `ToggleField`.
- Mockup `LogModal` (Fixed overlay) -> Decky UI `ConfirmModal` (via `showModal`).
- Icons: Use `FaDatabase` for the header.

## Phased Implementation Plan

### Phase 1: Structure Update
- Modify `src/index.tsx` to add the "Status" label row.
- Update button labels and section titles.
- Refine the `DropdownItem` selection logic to ensure it's "sticky" and correctly mapped.

### Phase 2: Visual Polishing
- Add inline styles to match the mockup's color palette (slates/blues) and padding while remaining native-feeling in SteamOS.
- Ensure the `LogModal` formatting matches the mockup's mono font and padding.

### Phase 3: Validation
- Build the frontend.
- Run protocol checks.
- Verify on device/emulator.

## Verification
- `pnpm run build` succeeds.
- Frontend static tests pass.
- Manual verification of game selection and status display.