import pytest
from pathlib import Path

BUDGETS = {
    "src/surfaces/autoSyncStatusSurface.tsx": 350,
    "src/surfaces/autoSyncStatusRenderer.tsx": 300,
    "src/surfaces/autoSyncStatusBrowserView.ts": 300,
    "src/controllers/gameLifecycleController.tsx": 550,
    "src/controllers/steamLifecycleSource.ts": 250,
    "src/controllers/syncthingMonitor.ts": 500,
    "src/controllers/syncthingMonitorMachine.ts": 350,
}


def test_module_size_budgets() -> None:
    for filepath, max_lines in BUDGETS.items():
        p = Path(filepath)
        if not p.exists():
            pytest.fail(f"File {filepath} does not exist.")
        content = p.read_text(encoding="utf-8")
        lines = len(content.splitlines())
        assert lines <= max_lines, f"{filepath} has {lines} lines, exceeding budget of {max_lines}"
