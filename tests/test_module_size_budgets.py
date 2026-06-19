import pytest
from pathlib import Path

BUDGETS = {
    "src/surfaces/autoSyncStatusSurface.tsx": 375,
    "src/surfaces/autoSyncStatusRenderer.tsx": 180,
    "src/surfaces/autoSyncStatusBrowserView.ts": 335,
    "src/controllers/gameLifecycleController.tsx": 645,
    "src/controllers/steamLifecycleSource.ts": 260,
    "src/controllers/syncthingMonitor.ts": 565,
    "src/controllers/syncthingMonitorMachine.ts": 375,
}


def test_module_size_budgets() -> None:
    for filepath, max_lines in BUDGETS.items():
        p = Path(filepath)
        if not p.exists():
            pytest.fail(f"File {filepath} does not exist.")
        content = p.read_text(encoding="utf-8")
        lines = len(content.splitlines())
        assert lines <= max_lines, f"{filepath} has {lines} lines, exceeding budget of {max_lines}"
