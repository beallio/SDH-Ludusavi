# Clear Stale BrowserView Content

## Problem Definition
The status strip uses a hardcoded 100ms `AUTO_SYNC_STATUS_SHOW_DELAY` before setting the BrowserView to visible to prevent visual flashing of the previous status document. However, when the BrowserView is hidden or synced as invisible, it retains the last loaded HTML content. When it is shown again with a new URL, a flash of stale content can occur if loading/rendering takes longer than 100ms.

## User Review Required
None.

## Proposed Changes

### SDH-Ludusavi Plugin Frontend

#### [MODIFY] [index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)

- Update [syncAutoSyncStatusBrowserView](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx#L908):
  When the state is invisible (the `else` branch of the visibility check), navigate the BrowserView to `about:blank` in addition to calling `SetVisible(false)`. This guarantees that the BrowserView's render and paint buffers are completely cleared of any stale document state while the view is off-screen.

### Testing Strategy

#### Dependency Requirements
None.

#### Automated Tests
- Run `./run.sh uv run pytest`
- Create a new static test `test_frontend_status_strip_clears_on_hide` in [test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py) that asserts `LoadURL` with `about:blank` is present in the `else` (invisible) path of `syncAutoSyncStatusBrowserView`.

## Verification Plan

### Automated Tests
- Run the python test suite via:
  ```bash
  ./run.sh uv run pytest
  ```
