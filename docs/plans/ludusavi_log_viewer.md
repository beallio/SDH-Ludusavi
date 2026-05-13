# Plan - Ludusavi Log Viewer

## Objective
Add a button to the SDH-ludusavi plugin to view the internal Ludusavi log file, helping users diagnose issues within Ludusavi itself.

## Architecture Overview
1.  **Backend RPC:** Add `get_ludusavi_logs` to `SDHLudusaviService` to read the Flatpak log file.
2.  **Frontend Callable:** Define the RPC in `src/index.tsx`.
3.  **UI Component:** Add a "View Ludusavi Logs" button and a modal to display the text.

## Implementation Steps
1.  **Backend (`py_modules/sdh_ludusavi/service.py`):**
    - Implement `get_ludusavi_logs`.
    - Path: `~/.var/app/com.github.mtkennerly.ludusavi/data/ludusavi/logs/ludusavi.log`.
2.  **Backend Export (`main.py`):**
    - Export `get_ludusavi_logs` in the `Plugin` class.
3.  **Frontend (`src/index.tsx`):**
    - Add `getLudusaviLogsCall` RPC.
    - Create `LudusaviLogModal` component (or genericize `LogModal`).
    - Add button to the "Logs" section.

## Verification
- Click the button and verify the modal shows Ludusavi logs.
- Verify it handles missing log files gracefully.
