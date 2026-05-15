# Specification: Ludusavi Shortcut Management

## Objective
Refactor the process of creating and managing the non-Steam shortcut for Ludusavi. The goal is to provide a consistent, visible, and persistent shortcut named "Ludusavi" that the plugin uses for launching the GUI, avoiding redundant shortcut creation and ensuring the shortcut remains visible to the user.

## Background
Currently, the plugin uses a dual-shortcut approach:
- It looks for a user-created shortcut named "Ludusavi".
- If not found, it creates its own managed shortcut named "[Plugin] Ludusavi Launcher", which it attempts to hide from the user.
- It renames this managed shortcut to "[Plugin] Ludusavi" during execution.

This complexity is unnecessary and can lead to multiple shortcuts or confusion.

## Proposed Changes

### 1. Unified Shortcut Identity
- The shortcut name shall be strictly "Ludusavi".
- The plugin will no longer use separate "Launcher" and "Running" names.
- All code attempting to hide the shortcut (`SetAppHidden`, etc.) shall be removed.

### 2. Robust AppID Caching and Conflict Resolution
To handle cases where a user might manually add, delete, or rename shortcuts, the plugin must implement a robust resolution strategy:

#### Resolution Flow (Pre-Launch)
1.  **Name Search (Primary):** Before relying on the cache, the plugin shall search the Steam `appStore` for any shortcut exactly named "Ludusavi".
    - **Match Found:** 
        - Compare its `appid` with the cached `appid` from the backend.
        - If the cached ID is missing or different, update the backend cache with the new `appid`.
        - Use this shortcut for the launch.
        - **Log:** `SDH-ludusavi: Found "Ludusavi" shortcut by name (AppID: {appid}). Cache was {status}.`
    - **No Match Found:** Proceed to step 2.

2.  **Cache Validation (Fallback):** If no shortcut named "Ludusavi" is found by name:
    - Check the cached `appid`.
    - If it exists, check if it still corresponds to a valid app in Steam.
    - If valid, use it (and ensure its name is set to "Ludusavi").
    - If invalid (shortcut deleted), proceed to step 3.

3.  **Creation:** If neither a name match nor a valid cache entry exists:
    - Create a new shortcut named "Ludusavi".
    - Immediately save the new `appid` to the backend cache.
    - **Log:** `SDH-ludusavi: No "Ludusavi" shortcut found. Created new shortcut (AppID: {appid}) and updated cache.`

### 3. Removal of Hiding Logic
- Remove `hideShortcutIfSupported` function and all associated logic from `src/ludusaviLauncher.ts`.
- The shortcut should be treated as a standard, visible non-Steam game.

### 4. Implementation Details (Frontend)

#### `src/ludusaviLauncher.ts`
- Remove `LUDUSAVI_SHORTCUT_NAME` and `LUDUSAVI_RUNNING_NAME`.
- Ensure `USER_SHORTCUT_NAME` (or a single `SHORTCUT_NAME` constant) is set to `"Ludusavi"`.
- Refactor `ensureLudusaviShortcut()` to implement the **Resolution Flow** above.
- Add comprehensive `console.log` statements for each branch of the resolution logic.

### 5. Implementation Details (Backend)
- `get_ludusavi_launcher_shortcut_id` and `set_ludusavi_launcher_shortcut_id` in `py_modules/sdh_ludusavi/service.py` will continue to serve as the source of truth for the cache.

### 6. Documentation Updates
- **README.md:** Update "Usage" or "Launcher" sections to reflect that the plugin uses a visible "Ludusavi" shortcut.
- **Internal Specs:** Update `docs/specs/sdh_ludusavi_launcher.md` (if it exists) to match this new behavior.

## Verification & Testing

### Test Cases
1.  **Fresh Install:**
    - Click "Launch". Verify "Ludusavi" is created and cached.
2.  **Manual User Addition (Before Plugin):**
    - User adds "Ludusavi" manually. Plugin clicks "Launch".
    - Verify plugin finds the manual shortcut, caches its ID, and does NOT create a second one.
3.  **Manual Deletion:**
    - User deletes the shortcut. Plugin clicks "Launch".
    - Verify plugin recreates it and updates the cache.
4.  **Cache Mismatch:**
    - User deletes the shortcut and adds a NEW "Ludusavi" manually (getting a new AppID).
    - Click "Launch". Verify plugin detects the mismatch, updates the cache to the new ID, and uses the new shortcut.
5.  **Logging:**
    - Monitor Decky logs (via Log viewer or console) to ensure all resolution steps are logged clearly.
