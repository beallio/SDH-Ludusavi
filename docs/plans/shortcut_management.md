# Plan: Ludusavi Shortcut Management

## Objective
Implement the changes specified in `docs/specs/ludusavi_shortcut_management.md` to unify the shortcut name to "Ludusavi", cache the AppID with robust conflict resolution, remove shortcut hiding logic, and update documentation.

## Key Files & Context
- `src/ludusaviLauncher.ts`: Primary file for shortcut management and launch logic.
- `py_modules/sdh_ludusavi/service.py`: Backend service for persisting the shortcut AppID.
- `README.md`: Project documentation.

## Implementation Steps

### 1. Frontend Refactoring (`src/ludusaviLauncher.ts`)
- **Cleanup Constants:**
    - Remove `LUDUSAVI_SHORTCUT_NAME` and `LUDUSAVI_RUNNING_NAME`.
    - Keep `USER_SHORTCUT_NAME = "Ludusavi"`.
- **Remove Hiding Logic:**
    - Delete `hideShortcutIfSupported` function.
    - Delete `calculateGameId` function.
- **Refactor Shortcut Creation:**
    - Rename `createHiddenLudusaviShortcut` to `createLudusaviShortcut`.
    - Remove hiding logic calls.
    - Add logging: `SDH-ludusavi: Created new "Ludusavi" shortcut (AppID: ${appId})`.
- **Refactor Shortcut Resolution (`ensureLudusaviShortcut`):**
    - Implement **Name-First** resolution:
        1.  Search `appStore` for name "Ludusavi".
        2.  If found:
            - Compare with cached AppID.
            - Update cache if mismatched or missing.
            - Return found shortcut.
        3.  If NOT found by name:
            - Check cached AppID.
            - If cached ID is valid in `appStore`:
                - Return cached shortcut.
            - If cached ID is invalid:
                - Create new "Ludusavi" shortcut.
                - Update cache.
- **Add Detailed Logging:**
    - Add `console.log` for every decision point in the resolution flow as specified.

### 2. Documentation Updates
- **README.md:** Update to mention the visible "Ludusavi" shortcut and its behavior.

## Verification & Testing

### Test Cases (Manual)
1.  **Fresh Install:** Launch creates "Ludusavi" and logs AppID.
2.  **User Pre-add:** User adds "Ludusavi" manually; plugin adopts it and updates cache on first launch.
3.  **Manual Deletion:** User deletes shortcut; plugin recreates it and updates cache.
4.  **AppID Mismatch:** User replaces shortcut with a new one named "Ludusavi" (new AppID); plugin detects mismatch, updates cache, and launches the new one.
5.  **Visibility:** Confirm shortcut is visible in Steam library and no "hide" calls occur in logs.
6.  **Logs:** Verify all resolution steps appear in the console/Decky logs.
