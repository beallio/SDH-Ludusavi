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
        "View Logs",
    ]:
        assert text in source


def test_frontend_wires_backend_calls_and_toasts() -> None:
    source = FRONTEND.read_text()

    for callable_name in [
        '"get_settings"',
        '"set_auto_sync_enabled"',
        '"set_selected_game"',
        '"refresh_games"',
        '"force_backup"',
        '"force_restore"',
        '"get_versions"',
        '"get_operation_status"',
        '"get_recent_logs"',
        '"log"',
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
    assert "onChange={(enabled: boolean) => void toggleAutoSync(enabled)}" in source
    assert 'type="checkbox"' not in source


def test_frontend_toggle_reports_busy_and_failures() -> None:
    source = FRONTEND.read_text()

    assert 'setBusyLabel("Updating settings")' in source
    assert "await setAutoSyncEnabled(enabled)" in source
    assert 'title: "SDH-ludusavi settings failed"' in source


def test_frontend_initial_load_fetches_logs_after_refresh() -> None:
    source = FRONTEND.read_text()

    assert "const loadedLogs = await getRecentLogs();" in source
    assert source.index("applyRefreshResult(refreshed") < source.index(
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


def test_frontend_uses_simplified_dropdown_labels() -> None:
    source = FRONTEND.read_text()

    assert "label: game.name" in source
    assert "statusLabels" not in source.split("rgOptions")[1].split("})")[0]


def test_frontend_includes_verbose_logging() -> None:
    source = FRONTEND.read_text()

    assert 'log("info", "Plugin mounted, starting initial load")' in source
    assert 'log("info", `Selected game changed to ${value}`)' in source
    assert 'log("error", `Initial load failed: ${error}`)' in source


def test_frontend_has_loading_game_list_status() -> None:
    source = FRONTEND.read_text()

    assert "Loading game list..." in source
    assert 'color: "#60a5fa"' in source
    assert 'fontWeight: "bold"' in source


def test_frontend_models_rpc_status_results_for_call_wrapped_methods() -> None:
    source = FRONTEND.read_text()

    assert "type RpcStatus = {" in source
    assert "type RpcResult<T> = T | RpcStatus;" in source
    assert (
        'const refreshGamesCall = callable<[force: boolean], RpcResult<RefreshResult>>("refresh_games");'
        in source
    )
    assert 'const getVersions = callable<[], RpcResult<Versions>>("get_versions");' in source
    assert (
        "const handleGameStartCall = callable<[gameName: string, app_id?: string], "
        'RpcResult<OperationResult>>("handle_game_start");'
    ) in source
    assert (
        "const handleGameExitCall = callable<[gameName: string, app_id?: string], "
        'RpcResult<OperationResult>>("handle_game_exit");'
    ) in source


def test_frontend_guards_refresh_and_version_rpc_status_payloads() -> None:
    source = FRONTEND.read_text()

    assert "function isRpcStatus<T>(result: RpcResult<T>): result is RpcStatus" in source
    assert "if (isRpcStatus(loadedVersions))" in source
    assert "if (isRpcStatus(result))" in source
    assert 'logRpcStatus(result, "refresh")' in source
    assert 'logRpcStatus(loadedVersions, "versions")' in source
