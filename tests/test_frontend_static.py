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
    assert 'type="checkbox"' not in source


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


def test_frontend_uses_decky_log_modal() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "ConfirmModal",
        "showModal",
        "type LogModalProps",
        "function LogModal",
        "bAlertDialog={true}",
        'strTitle="Plugin Logs"',
        "onOK={closeModal}",
        "onCancel={closeModal}",
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
        "showModal(<LogModal logs={logs} />)",
    ]:
        assert required_text in source

    assert "showLogs" not in source
    assert "setShowLogs" not in source
