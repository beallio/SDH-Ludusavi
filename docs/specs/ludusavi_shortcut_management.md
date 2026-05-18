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
- The plugin will no longer attempt to hide the shortcut.

### 2. AppID Caching and Persistence
- The plugin shall persist the `appid` of the "Ludusavi" shortcut in its backend state.
- When launching, the plugin will follow this resolution order:
    1.  **Cached AppID:** Check the backend for a saved `appid`. If it exists and corresponds to an app in the Steam `appStore`, use it.
    2.  **Name Search:** If no cached AppID exists or it is invalid, search the Steam `appStore` for any shortcut exactly named "Ludusavi".
    3.  **Creation:** If no shortcut named "Ludusavi" exists, create a new one.
- Whenever a shortcut is identified (via search or creation), its `appid` must be saved to the backend for future reference.

### 3. Removal of Hiding Logic
- Remove `hideShortcutIfSupported` function and all associated logic from `src/ludusaviLauncher.ts`.
- The shortcut should be treated as a standard, visible non-Steam game.

### 4. Implementation Details (Frontend)

#### `src/ludusaviLauncher.ts`
- Remove `LUDUSAVI_SHORTCUT_NAME` and `LUDUSAVI_RUNNING_NAME`.
- Ensure `USER_SHORTCUT_NAME` (or a single `SHORTCUT_NAME` constant) is set to `"Ludusavi"`.
- Refactor `ensureLudusaviShortcut()`:
    ```typescript
    async function ensureLudusaviShortcut(): Promise<LauncherShortcutState> {
      // 1. Check cached AppID
      const savedAppId = await getSavedShortcutAppId();
      if (savedAppId > 0) {
        const gameId = getGameIdFromAppId(savedAppId);
        if (gameId) {
          console.log(`SDH-ludusavi: Using cached shortcut AppID: ${savedAppId}`);
          return { appId: savedAppId, gameId, managed: true };
        }
        console.warn(`SDH-ludusavi: Cached shortcut ${savedAppId} no longer valid.`);
      }

      // 2. Search by name
      const existing = findUserLudusaviShortcut(); // Rename or refactor to search by name
      if (existing) {
        console.log(`SDH-ludusavi: Found existing shortcut by name: ${existing.appId}`);
        await saveShortcutAppId(existing.appId);
        return existing;
      }

      // 3. Create new
      return await createLudusaviShortcut(); // No longer "hidden"
    }
    ```
- Refactor `launchLudusavi()`:
    - Call `ensureLudusaviShortcut()`.
    - Set the shortcut name to `"Ludusavi"` (redundant if already named so, but ensures consistency).
    - Set Exe, Launch Options, and Compat Tool.
    - Launch via `RunGame`.

### 5. Implementation Details (Backend)
- No significant changes required as `get_ludusavi_launcher_shortcut_id` and `set_ludusavi_launcher_shortcut_id` already exist in `py_modules/sdh_ludusavi/service.py`.

## Verification & Testing

### Test Cases
1.  **Fresh Install:**
    - Click "Launch" in the plugin.
    - Verify a shortcut named "Ludusavi" is created.
    - Verify it is visible in the Steam library.
    - Verify it launches Ludusavi.
2.  **Persistence:**
    - Restart Steam/Decky.
    - Click "Launch" again.
    - Verify it uses the *same* shortcut (no duplicates).
    - Check logs to ensure it used the cached AppID.
3.  **Manual Shortcut Adoption:**
    - Delete any plugin-created shortcuts.
    - Manually add a non-Steam game and name it "Ludusavi".
    - Click "Launch" in the plugin.
    - Verify the plugin adopts this shortcut and populates its `appid` in the backend.
4.  **Hiding Removal:**
    - Verify that `SetAppHidden` or similar calls are no longer appearing in the console logs during launch.
