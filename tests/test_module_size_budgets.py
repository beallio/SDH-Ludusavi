import pytest
from pathlib import Path

BUDGETS = {
    "src/surfaces/autoSyncStatusSurface.tsx": 375,
    "src/surfaces/autoSyncStatusRenderer.tsx": 180,
    "src/surfaces/autoSyncStatusBrowserView.ts": 335,
    "src/controllers/gameLifecycleController.tsx": 450,
    "src/controllers/gameLifecycleDecision.ts": 255,
    "src/controllers/steamLifecycleSource.ts": 260,
    "src/controllers/syncthingMonitor.ts": 565,
    "src/controllers/syncthingMonitorMachine.ts": 375,
    "py_modules/sdh_ludusavi/updater.py": 615,
    "py_modules/sdh_ludusavi/updater_client.py": 105,
    "py_modules/sdh_ludusavi/updater_discovery.py": 230,
    "py_modules/sdh_ludusavi/updater_models.py": 165,
    "py_modules/sdh_ludusavi/updater_pending.py": 75,
    "py_modules/sdh_ludusavi/updater_rate_limit.py": 35,
    "src/controllers/pluginUpdateController.tsx": 490,
    "src/controllers/pluginUpdateReducer.ts": 190,
    "src/components/qam/LudusaviContent.tsx": 625,
    "src/components/qam/useInitialContent.ts": 240,
    "src/components/qam/useGameRefresh.ts": 135,
    "src/components/qam/useSteamContext.ts": 120,
    "src/components/qam/manualOperationFinalize.ts": 65,
    "src/components/qam/refreshSelection.ts": 35,
    "src/components/qam/qamOpenSelection.ts": 35,
}


def test_module_size_budgets() -> None:
    for filepath, max_lines in BUDGETS.items():
        p = Path(filepath)
        if not p.exists():
            pytest.fail(f"File {filepath} does not exist.")
        content = p.read_text(encoding="utf-8")
        lines = len(content.splitlines())
        assert lines <= max_lines, f"{filepath} has {lines} lines, exceeding budget of {max_lines}"
