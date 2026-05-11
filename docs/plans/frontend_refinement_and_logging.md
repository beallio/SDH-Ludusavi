# Frontend Refinements and Logging

## Objective
Address dropdown selection bugs, clean up version strings, and integrate frontend logging with the Decky Loader logger.

## Changes
- **src/index.tsx**:
  - Update `rgOptions` in `DropdownItem` to only include `game.name` in the `label`.
  - Simplify `selectedOption` to use `selectedGame` directly.
  - Integrate `console.log` and `console.error` throughout the component to track state changes and errors, ensuring they are visible in Decky's log system.
  - In `Content.useEffect`, add logging for the initial load sequence.
- **py_modules/sdh_ludusavi/service.py**:
  - In `get_versions`, strip the leading "ludusavi " from the Ludusavi version string if present.

## Verification
- Verify that game names in the dropdown no longer show statuses like "- Backup ready".
- Verify that selecting a game correctly updates the dropdown display and the "Status:" row below it.
- Verify the Ludusavi version is shown as "0.30.0" instead of "ludusavi 0.30.0".
- Check Decky logs to ensure frontend events (loading, selection, errors) are correctly logged.
- Run `./run.sh uv run pytest` to ensure no backend regressions.
