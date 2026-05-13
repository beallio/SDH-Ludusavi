# Plan - Launch Ludusavi via Hidden Reusable Steam Shortcut

Implement a feature to launch Ludusavi from a button in the Decky plugin UI using a hidden reusable Steam shortcut, following the blueprint of SDH-QuickLaunch and the technical specification in `docs/specs/sdh_ludusavi_launcher.md`.

## Problem Definition
Users want a quick way to open the Ludusavi GUI directly from the plugin. This requires a reliable launch mechanism in Steam Gaming Mode that doesn't clutter the user's library with visible shortcuts. Additionally, the button should be disabled if Ludusavi is not found on the system.

## Architecture Overview
- **Backend (Python)**: Persistent storage for the Steam shortcut `appId` and logic to discover the Ludusavi launch command.
- **Frontend Helper (TypeScript)**: Logic to interact with `SteamClient` for shortcut lifecycle management, protected by ambient types and runtime guards.
- **UI (React)**: A new `Ludusavi` panel with a `Launch` button, integrated into the existing sidebar above the `Logs` panel.

## Proposed Solution

### 1. Backend Persistence & Discovery
Update `SDHLudusaviService` and `Plugin` classes to manage `ludusaviLauncherShortcutAppId` in the plugin state and expose discovery results.
- `get_ludusavi_launcher_shortcut_id()` -> `int`
- `set_ludusavi_launcher_shortcut_id(app_id: int)` -> `bool`
- `clear_ludusavi_launcher_shortcut_id()` -> `bool`
- `get_ludusavi_command()` -> `dict | null`: Returns the command path and args used by the plugin for GUI launching. Returns `null` if Ludusavi is not found.

### 2. Frontend Infrastructure
- **Type Safety**: Create `src/types/steam-globals.d.ts` for `SteamClient` and `appStore` globals.
- **Launcher Helper**: Create `src/ludusaviLauncher.ts` with all required helper functions, runtime guards, and robust escaping as specified.

### 3. UI Integration (`src/index.tsx`)
- Add a `LudusaviPanel` component.
- Display a "Launch" button that triggers `launchLudusavi`.
- **Availability**: Disable the "Launch" button and show a "Ludusavi not found" message if the backend cannot locate the executable.
- **Feedback**: Show "Launching Ludusavi..." status during the process.
- **Placement**: Insert the `Ludusavi` panel immediately **above** the `Logs` panel.

## Key Files & Context
- `py_modules/sdh_ludusavi/service.py`: State management and discovery.
- `main.py`: RPC exports.
- `src/index.tsx`: UI layout and availability state.
- `src/ludusaviLauncher.ts`: Launcher logic.
- `src/types/steam-globals.d.ts`: Ambient declarations.

## Phased Implementation Plan

### Phase 1: Backend & Infrastructure
- T1: Add `_ludusavi_launcher_shortcut_id` to `SDHLudusaviService` state and update persistence.
- T2: Implement getter/setter/clearer methods in `SDHLudusaviService` and expose in `main.py`.
- T3: Implement `get_ludusavi_command` in `SDHLudusaviService` using `pyludusavi.discovery` logic.
- T4: Create `src/types/steam-globals.d.ts`.

### Phase 2: Launcher Logic
- T5: Create `src/ludusaviLauncher.ts` with all required helper functions and runtime guards.
- T6: Implement argument escaping and executable quoting.

### Phase 3: UI Integration
- T7: Implement `LudusaviPanel` in `src/index.tsx` with availability-aware state.
- T8: Integrate the panel into the layout above the `Logs` panel.
- T9: Fetch `ludusaviCommand` on component mount and set availability status.

## Verification & Testing
- **Backend Tests**: Add tests for the new RPC methods.
- **Build**: Ensure `npm run build` succeeds with the new types.
- **Missing Binary Test**: Simulate discovery failure and verify the button is disabled with appropriate feedback.
- **Manual**: Verify shortcut creation, hiding, mutation, and successful launch on device.
