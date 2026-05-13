# Plan: Add Pyludusavi Version and Ludusavi Log Viewer

## Problem Definition
The user wants to see the `pyludusavi` version in the plugin's version list and have a way to view Ludusavi's own logs from within the Decky plugin GUI. Additionally, the `pyludusavi` dependency needs to be updated to `0.2.0`.

## Architecture Overview
- **Dependencies**: Update `pyproject.toml` to require `pyludusavi>=0.2.0`.
- **Backend**:
  - `SDHLudusaviService` will be updated to include `pyludusavi` in its version list.
  - A new method `get_ludusavi_logs` will be added to `SDHLudusaviService` to read the `ludusavi.log` file.
  - `LudusaviAdapter` and `PyludusaviAdapter` will be updated to provide the log file path.
- **Frontend**:
  - `Versions` type will be updated to include `pyludusavi`.
  - The "Versions" section in the GUI will display the `pyludusavi` version.
  - A new button "View Ludusavi Logs" will be added to the "Logs" section.
  - A new modal (or reused `LogModal`) will display the Ludusavi logs.

## Core Data Structures
- `Versions` (TypeScript): Updated to include `pyludusavi: string`.
- `get_ludusavi_logs` (Python/RPC): Returns a string or list of log lines.

## Public Interfaces
- `get_ludusavi_logs()`: New RPC method.
- `get_versions()`: Updated to return `pyludusavi` key.

## Dependency Requirements
- `pyludusavi>=0.2.0` (to be updated).

## Testing Strategy
- **Backend**:
  - Unit test for `get_versions` to ensure `pyludusavi` is present.
  - Unit test for `get_ludusavi_logs` with a mock log file.
- **Frontend**:
  - Manual verification of the GUI elements (versions and button).
  - Manual verification of the log modal content.

## Implementation Steps

### 1. Dependencies: Update pyludusavi
- Update `pyproject.toml`: Change `pyludusavi>=0.1.1` to `pyludusavi>=0.2.0`.
- Run `./run.sh uv sync` to update the lock file and environment.

### 2. Backend: Update Version Resolution
- In `py_modules/sdh_ludusavi/service.py`:
  - Import `pyludusavi`.
  - Update `get_versions` to include `pyludusavi.__version__`.

### 3. Backend: Implement Log Retrieval
- In `py_modules/sdh_ludusavi/service.py`:
  - Add `get_log_path` to `LudusaviAdapter` protocol.
  - Implement `get_ludusavi_logs` in `SDHLudusaviService`.
- In `py_modules/sdh_ludusavi/ludusavi.py`:
  - Implement `get_log_path` in `PyludusaviAdapter` using `self._client.config_path()`.
- In `main.py`:
  - Add `get_ludusavi_logs` RPC method.

### 4. Frontend: Update Types and Callables
- In `src/index.tsx`:
  - Update `Versions` type.
  - Add `getLudusaviLogs` callable.

### 5. Frontend: Update GUI
- In `src/index.tsx`:
  - Update `Content` component to display `pyludusavi` version.
  - Add "View Ludusavi Logs" button and logic to show modal with logs.

### 6. Verification
- Run backend tests.
- Build and test in Decky environment.
