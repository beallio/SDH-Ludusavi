# Plan - Add Icons to Toast Notifications

Add context-specific icons to all toast notifications and update the main plugin icon.

## Problem Definition
Toast notifications currently only show text. Adding icons will provide better visual context for the operation being performed. Additionally, the main plugin icon should be more descriptive of its purpose (backup/restore).

## Architecture Overview
Toast notifications are triggered via the `toaster.toast` API from `@decky/api`. Icons from `react-icons` can be passed to the `logo` property of the toast object. The main plugin icon is defined in the `definePlugin` return object.

## Proposed Solution
1.  Import necessary icons from `react-icons` sets (`fa`, `io`, `lu`).
2.  Update `showToast` to accept an optional `icon` (ReactNode).
3.  Update all `toaster.toast` and `showToast` calls in `src/index.tsx` with appropriate icons.
4.  Update the main plugin icon in `definePlugin`.

### Icon Mapping
- **Main Plugin Icon:** `LuDatabaseBackup` from `react-icons/lu`
- **Backup:** `FaSave` from `react-icons/fa`
- **Restore:** `FaDownload` from `react-icons/fa`
- **Refresh/Sync:** `IoMdRefresh` from `react-icons/io`
- **Logs:** `FaFileAlt` from `react-icons/fa`
- **Settings/Config:** `FaCog` from `react-icons/fa`
- **Generic/Auto-sync:** `FaDatabase` from `react-icons/fa`
- **Error:** `FaExclamationTriangle` from `react-icons/fa`

## Key Files & Context
- `src/index.tsx`: Main UI and toast logic.

## Implementation Steps
1.  Update imports in `src/index.tsx` to include `FaSave`, `FaDownload`, `FaFileAlt`, `FaCog`, `FaDatabase`, `FaExclamationTriangle`, `IoMdRefresh`, and `LuDatabaseBackup`.
2.  Refactor `showToast(title: string, body: string)` to `showToast(title: string, body: string, logo?: any)`.
3.  Update call sites:
    - `refreshGames`: Use `IoMdRefresh` icon.
    - `showLudusaviLogs` (error): Use `FaExclamationTriangle`.
    - `toggleAutoSync` (error): Use `FaExclamationTriangle`.
    - `runForceOperation`:
        - Start: `label === "Backup" ? <FaSave /> : <FaDownload />`
        - Success: Same as start.
        - Failure: `FaExclamationTriangle`
    - `handleAppStart` / `handleAppExit`:
        - Status checking/backing up: `<FaDatabase />` or `<FaSave />`.
        - Result: `result.status === "failed" ? <FaExclamationTriangle /> : (result.status === "restored" ? <FaDownload /> : <FaSave />)`
4.  Update `definePlugin` return object to use `<LuDatabaseBackup />` as the `icon`.

## Verification & Testing
1.  **Build Check**: Run `npm run build` to ensure the TypeScript/React code still compiles and imports are correct.
2.  **Manual Verification**: Verify that the correct icons appear for each notification type and the main sidebar icon is updated.
