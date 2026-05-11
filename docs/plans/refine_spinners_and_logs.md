# Plan - Refine Spinners and Logs

Apply cosmetic and functional refinements to Spinners and Logs as requested.

## Problem Definition
1. **Spinner Color:** The current spinners use default styling. They should be colored `#1a9fff` (blue) to better match the requested aesthetic.
2. **Log Ordering:** Logs are currently retrieved in reverse chronological order (newest at top). The expectation is most recent at the bottom.
3. **Log Timestamps:** Log entries lack timestamps, making it difficult to correlate events with real-world time.

## Proposed Solution

### 1. Backend Enhancements
- **LogEntry Structure:** Update `LogEntry` dataclass to include a `timestamp` field.
- **Unified Logging:** Update the `log` method in `SDHLudusaviService` to generate a standard `YYYY-MM-DD HH:MM:SS` timestamp when creating entries.
- **Log Retrieval:** Change `get_recent_logs` to return the `deque` entries in their natural order (oldest to newest) instead of reversing them.

### 2. Frontend Enhancements
- **Spinner Styling:** Update the `SpinnerButton` component to apply `color: "#1a9fff"` to the `Spinner` component.
- **Log Rendering:** Update `formatLogEntry` to include the timestamp in the rendered string.

## Changes

### Backend (`py_modules/sdh_ludusavi/service.py`)
- Import `datetime` from `datetime`.
- Update `LogEntry` dataclass with `timestamp: str`.
- Update `SDHLudusaviService.get_recent_logs` to remove `reversed()`.
- Update `SDHLudusaviService.log` to generate and store `timestamp`.

### Frontend (`src/index.tsx`)
- Update `LogEntry` type definition to include `timestamp`.
- Update `formatLogEntry` to include `entry.timestamp`.
- Update `SpinnerButton` to pass `color="#1a9fff"` to the `Spinner` component.

## Verification & Testing
1. **Log Order:** Verify in the "View Logs" modal that new entries appear at the bottom.
2. **Timestamps:** Verify that each log entry starts with a timestamp (e.g., `[2026-05-11 15:45:00]`).
3. **Spinner Color:** Visually verify (if possible via build check or proxy) that the spinner is blue.
4. **Tests:** Update `tests/test_refinements.py` to assert timestamp presence and chronological order.
