# Refactor Ludusavi Discovery to pyludusavi [COMPLETED]

## Problem Definition
`sdh_ludusavi` currently contains custom logic for discovering the Ludusavi raw binary and its configuration directory. This logic should be moved to the `pyludusavi` library to improve its autonomy and simplify the plugin's backend. The plugin does not run as root, so DBUS initialization issues are not a concern.

## Architecture Overview
The discovery logic will be moved to `py_modules/pyludusavi/discovery.py`. `pyludusavi.Ludusavi` will be updated to automatically use these discovery methods if appropriate parameters (like `flatpak_id` and `flatpak_user_home`) are provided.

## Proposed Changes

### 1. `py_modules/pyludusavi/discovery.py`
- Add `find_ludusavi_binary(flatpak_id: str, user_home: str | None) -> str | None`:
    - Logic to search for Ludusavi in standard locations and Flatpak-specific paths (prioritizing the raw binary if found).
- Add `find_ludusavi_config_dir(flatpak_id: str, user_home: str | None, binary_path: str) -> str | None`:
    - Logic to find the configuration directory for a Flatpak-based binary when running outside the sandbox.
- Export these in `py_modules/pyludusavi/__init__.py`.

### 2. `py_modules/pyludusavi/main.py`
- Update `Ludusavi.__init__` to:
    - Automatically attempt raw binary discovery if `explicit_path` is not provided and `flatpak_id` is.
    - Automatically attempt config directory discovery if a raw binary is used and `config_dir` is not provided.

### 3. `py_modules/sdh_ludusavi/ludusavi.py`
- Remove `_find_ludusavi_binary`.
- Remove `_find_ludusavi_config_dir`.
- Simplify `PyludusaviAdapter.__init__` to just instantiate `Ludusavi` with `flatpak_id`, `flatpak_user_home`, and `flatpak_user`.

### 4. `tests/test_ludusavi.py`
- Update mocks to reflect the removal of internal discovery functions.

## Verification & Testing
- Run existing tests: `./run.sh uv run pytest`
- Add new unit tests in `tests/test_ludusavi_discovery.py` for the new `pyludusavi` discovery methods.
