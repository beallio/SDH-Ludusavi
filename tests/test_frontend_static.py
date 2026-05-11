from pathlib import Path


FRONTEND = Path("src/index.tsx")


def test_frontend_exposes_sdh_ludusavi_panel_controls() -> None:
    source = FRONTEND.read_text()

    for text in [
        "SDH-ludusavi",
        "Automatic Sync",
        "Refresh Games",
        "Force Backup",
        "Force Restore",
        "Show Logs",
    ]:
        assert text in source


def test_frontend_wires_backend_calls_and_toasts() -> None:
    source = FRONTEND.read_text()

    for callable_name in [
        '"get_settings"',
        '"set_auto_sync_enabled"',
        '"refresh_games"',
        '"force_backup"',
        '"force_restore"',
        '"get_versions"',
        '"get_operation_status"',
        '"get_recent_logs"',
    ]:
        assert callable_name in source

    assert "toaster.toast" in source
    assert "is_running" in source
    assert "dependency_error" in source


def test_frontend_uses_decky_toggle_for_automatic_sync() -> None:
    source = FRONTEND.read_text()

    assert "ToggleField" in source
    assert 'label="Automatic Sync"' in source
    assert "checked={settings.auto_sync_enabled}" in source
    assert "disabled={isBusy}" in source
    assert "onChange={(enabled) => void toggleAutoSync(enabled)}" in source
    assert 'type="checkbox"' not in source


def test_frontend_toggle_reports_busy_and_failures() -> None:
    source = FRONTEND.read_text()

    assert 'setBusyLabel("Updating settings")' in source
    assert "await setAutoSyncEnabled(enabled)" in source
    assert 'title: "SDH-ludusavi settings failed"' in source


def test_frontend_initial_load_fetches_logs_after_refresh() -> None:
    source = FRONTEND.read_text()

    assert "const loadedLogs = await getRecentLogs();" in source
    assert source.index("applyRefreshResult(refreshed);") < source.index(
        "const loadedLogs = await getRecentLogs();"
    )


def test_frontend_exposes_sdh_ludusavi_version_row() -> None:
    source = FRONTEND.read_text()

    assert "sdh_ludusavi?: string;" in source
    assert '<div>SDH-ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>' in source
    assert source.index("SDH-ludusavi:") < source.index("Ludusavi:")


def test_frontend_renders_logs_inline_to_avoid_closing_qam() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "const [showingLogs, setShowingLogs] = useState(false);",
        "if (showingLogs) {",
        '<PanelSection title="Plugin Logs">',
        "onClick={() => setShowingLogs(false)}",
        "Back",
        'maxHeight: "60vh"',
        'overflowY: "auto"',
        'fontFamily: "monospace"',
        'fontSize: "12px"',
        'whiteSpace: "pre-wrap"',
        'backgroundColor: "rgba(0, 0, 0, 0.3)"',
        'padding: "10px"',
        'borderRadius: "4px"',
        'userSelect: "text"',
        'logs.length === 0 ? "No recent logs" : logs.map(formatLogEntry).join("\\n")',
        "onClick={() => setShowingLogs(true)}",
        "Show Logs",
    ]:
        assert required_text in source

    assert "showModal" not in source
    assert "ConfirmModal" not in source
