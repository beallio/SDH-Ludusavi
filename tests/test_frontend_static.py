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
        '"set_notification_settings"',
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


def test_frontend_exposes_notification_preferences_panel() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'PanelSection title="Notifications"',
        'label="All Notifications"',
        'label="Manual Operations"',
        'label="Refresh Status"',
        'label="Failures and Errors"',
        "settings.notifications.enabled",
        "disabled={!settings.notifications.enabled || isBusy}",
        "onChange={(enabled: boolean) => void toggleNotificationSetting",
    ]:
        assert required_text in source

    assert 'label="Auto-sync Progress"' not in source
    assert 'label="Auto-sync Results"' not in source
    assert source.index('PanelSection title="Notifications"') < source.index("<LudusaviPanel")


def test_frontend_centralizes_notification_aware_toasts() -> None:
    source = FRONTEND.read_text()

    assert "type NotificationCategory =" in source
    assert "let notificationSettingsMirror" in source
    assert "function notify(" in source
    assert "shouldShowNotification(category)" in source
    assert "toaster.toast" in source
    assert source.count("toaster.toast") == 1
    for category in [
        '"manual_operations"',
        '"refresh_status"',
        '"failures_errors"',
    ]:
        assert category in source


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
    assert '"SDH-ludusavi settings failed"' in source
    assert 'notify("failures_errors", "SDH-ludusavi settings failed"' in source


def test_frontend_silences_lifecycle_toasts_when_auto_sync_is_disabled() -> None:
    source = FRONTEND.read_text()

    assert "let autoSyncNotificationsEnabled = false;" in source
    assert "autoSyncNotificationsEnabled = normalized.auto_sync_enabled;" in source
    assert "function shouldPublishAutoSyncStatusBeforeRpc(" in source
    assert "globalSettings === null || autoSyncNotificationsEnabled" in source
    assert "trackedAppIDs.size === 0 && trackedNames.size === 0" in source
    assert source.count("if (shouldPublishAutoSyncStatusBeforeRpc(tracked))") == 2

    start_status = 'publishAutoSyncStatus("restoring", {'
    exit_status = 'publishAutoSyncStatus("backing_up", {'
    assert start_status in source
    assert exit_status in source

    assert source.index(start_status) < source.index(
        "const result = await handleGameStartCall(name, appID);"
    )
    assert source.index(exit_status) < source.index(
        "const result = await handleGameExitCall(name, appID);"
    )


def test_frontend_uses_browserview_only_autosync_status_strip() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'type AutoSyncStatusKind = "backing_up" | "restoring" | "has_backup" | "needs_backup" | "error";',
        "let currentAutoSyncStatusState: AutoSyncStatusState",
        "currentAutoSyncStatusState = {",
        "function hideAutoSyncStatus(",
        'source: "hide"',
        "function publishAutoSyncStatus(",
        'source: "hide",',
        "alwaysRender: true",
        "function scheduleAutoSyncStatusHide(",
        "function clearAutoSyncStatusHideTimeout()",
        "autoSyncStatusHideTimeoutID",
        "window.clearTimeout(autoSyncStatusHideTimeoutID);",
    ]:
        assert required_text in source

    for stale_text in [
        'import { createPortal } from "react-dom";',
        "createPortal(",
        "document.body",
        "function AutoSyncStatusStrip()",
        "type AutoSyncStatusListener",
        "autoSyncStatusListeners",
        "routerHook.addGlobalComponent",
        "routerHook.removeGlobalComponent",
        "EUIComposition",
        "findModuleChild",
        "UseUIComposition",
        "AutoSyncStatusComposition",
    ]:
        assert stale_text not in source


def test_frontend_hides_status_strip_for_backend_silent_autosync_skips() -> None:
    source = FRONTEND.read_text()

    assert (
        'const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];'
        in source
    )
    lifecycle_source = source[source.index("const handleAppStart = async") :]
    assert lifecycle_source.count("hideAutoSyncStatus({") >= 2
    assert lifecycle_source.index("hideAutoSyncStatus({") > lifecycle_source.index(
        "const result = await handleGameStartCall(name, appID);"
    )


def test_frontend_status_strip_matches_steamos_visual_contract() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "const bottomOffset = 48;",
        "rawHeight - height - bottomOffset",
        "width: 100vw;",
        "height: 100vh;",
        "background: rgba(0, 0, 0, 0.34)",
        'font-family: "Motiva Sans", Arial, sans-serif;',
        "font-weight: 800;",
        "justify-content: center;",
        "min-width: 245px;",
        'state.status === "needs_backup" ? "#f59e0b"',
        '"#66c0f4"',
        '"#ef4444"',
        "border-top: 1px solid rgba(255, 255, 255, 0.10);",
    ]:
        assert required_text in source

    assert "justify-content: space-between;" not in source


def test_frontend_status_strip_uses_inline_browserview_icons() -> None:
    package_json = Path("package.json").read_text()
    source = FRONTEND.read_text()

    assert "@fortawesome/" not in package_json
    assert "FontAwesomeIcon" not in source
    assert "library.add" not in source

    for required_text in [
        "function iconSvgForAutoSyncStatus(",
        'status === "restoring"',
        "transform: rotate(180deg);",
        '<svg viewBox="0 0 20 20"',
        'stroke="#0b151f"',
    ]:
        assert required_text in source


def test_frontend_status_strip_replaces_autosync_success_toasts() -> None:
    source = FRONTEND.read_text()

    assert 'notify("auto_sync_progress"' not in source
    assert 'notify("auto_sync_results"' not in source
    assert '"auto_sync_progress"' not in source
    assert '"auto_sync_results"' not in source

    for required_text in [
        'publishAutoSyncStatus("has_backup", {',
        'publishAutoSyncStatus("needs_backup", {',
        'publishAutoSyncStatus("error", {',
        'notify("failures_errors", "SDH-ludusavi Auto-sync"',
    ]:
        assert required_text in source


def test_frontend_status_strip_uses_browserview_overlay_surface() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "type AutoSyncStatusBrowserView",
        "type AutoSyncStatusBrowserViewOwner",
        "let autoSyncStatusBrowserView: AutoSyncStatusBrowserView | null = null;",
        "let autoSyncStatusBrowserViewOwner: AutoSyncStatusBrowserViewOwner | null = null;",
        "function ensureAutoSyncStatusBrowserView()",
        "function normalizeAutoSyncStatusBrowserView(",
        "candidate?.m_browserView",
        "candidate?.browserView",
        "candidate?.BrowserView",
        "candidate?.m_browserView?.m_browserView",
        "BrowserView normalized from",
        "rootWindow?.CreateBrowserView",
        "rootWindow.CreateBrowserView(",
        '"sdh-ludusavi-autosync-status-strip"',
        "steamClient?.BrowserView?.Create",
        "function renderAutoSyncStatusHtml(",
        '"data:text/html;charset=utf-8,"',
        "function syncAutoSyncStatusBrowserView(",
        "browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);",
        "browserView.SetVisible(false);",
        "browserView.SetVisible?.(true);",
        "syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);",
        "destroyAutoSyncStatusBrowserView();",
        "autoSyncStatusBrowserViewOwner",
        'log("info", "Creating BrowserView via GamepadUIMainWindowInstance"',
        'log("info", "Creating BrowserView via SteamClient.BrowserView.Create"',
        'log("info",',
        "`BrowserView created: type=${typeof autoSyncStatusBrowserViewOwner}",
        "normalized.SetWindowStackingOrder?.(50);",
        "SetTopmost(true)",
        "browserView.LoadURL(url);",
        "setTimeout(() => {",
        "pixelRatio",
        "Math.round(",
        "background: rgba(0, 0, 0, 0.34)",
    ]:
        assert required_text in source
    assert source.index("rootWindow?.CreateBrowserView") < source.index(
        "steamClient?.BrowserView?.Create"
    )


def test_frontend_status_strip_logs_status_provenance() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'type AutoSyncStatusSource = "lifecycle_start" | "lifecycle_exit" | "rpc_result" | "timeout" | "hide";',
        "source: AutoSyncStatusSource;",
        "gameName?: string;",
        "appID?: string;",
        "tracked?: boolean;",
        'resultStatus?: OperationResult["status"] | RpcStatus["status"];',
        "function logAutoSyncStatusChange(",
        "source=${state.source}",
        'game=${state.gameName ?? "unknown"}',
        'app_id=${state.appID ?? "unknown"}',
        'tracked=${state.tracked ?? "unknown"}',
        'result=${state.resultStatus ?? "none"}',
        "visible=${state.visible}",
    ]:
        assert required_text in source


def test_frontend_status_strip_maps_local_current_to_up_to_date() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'if (result.status === "skipped") {',
        'if (result.reason === "local_current") {',
        'publishAutoSyncStatus("has_backup", {',
        "resultStatus: result.status",
        'publishAutoSyncStatus("needs_backup", {',
    ]:
        assert required_text in source

    assert source.index('result.reason === "local_current"') < source.index(
        'publishAutoSyncStatus("needs_backup", {'
    )


def test_frontend_logs_lifecycle_rpc_boundaries() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'log("info", `Calling handle_game_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);',
        "const result = await handleGameStartCall(name, appID);",
        'log("info", `handle_game_start result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);',
        'log("info", `Calling handle_game_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);',
        "const result = await handleGameExitCall(name, appID);",
        'log("info", `handle_game_exit result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);',
    ]:
        assert required_text in source


def test_frontend_has_no_status_strip_diagnostic_ui_or_modes() -> None:
    source = FRONTEND.read_text()

    for stale_text in [
        "AutoSyncStatusSurfaceMode",
        "autoSyncDiagnosticModes",
        "autoSyncDiagnosticModeIndex",
        "function publishNextDebugAutoSyncStatus()",
        'source: "debug_button",',
        'gameName: "Debug diagnostic",',
        'appID: "debug",',
        "Debug: Cycle Status Strip Surface",
        "DIAGNOSTIC:",
    ]:
        assert stale_text not in source


def test_frontend_uses_app_lifetime_notifications_for_lifecycle_detection() -> None:
    source = FRONTEND.read_text()

    assert "RegisterForAppLifetimeNotifications" in source
    assert "RegisterForGameActionEnd" not in source
    assert "type AppLifetimeNotification" in source
    assert "type RunningSession" in source
    assert "const activeSessions = new Map<number, RunningSession>();" in source
    assert "notification.nInstanceID" in source
    assert "notification.bRunning" in source
    assert "handleLifetimeNotification" in source
    assert "void handleAppStart(session.name, session.appID);" in source
    assert "void handleAppExit(session.name, session.appID);" in source


def test_frontend_lifecycle_polling_is_fallback_only() -> None:
    source = FRONTEND.read_text()

    assert "startFallbackPolling" in source
    assert "RegisterForAppLifetimeNotifications" in source
    assert "registerLifetime" in source
    assert 'if (typeof registerLifetime === "function")' in source
    assert "window.setInterval(checkMainApp, 1000)" in source
    assert source.index("window.setInterval(checkMainApp, 1000)") > source.index(
        "const startFallbackPolling = () => {"
    )
    assert "const intervalID = window.setInterval(checkMainApp, 1000);" not in source


def test_frontend_lifecycle_resolution_handles_non_steam_shortcuts() -> None:
    source = FRONTEND.read_text()

    assert "notification.unAppID > 0" in source
    assert "Router.RunningApps" in source
    assert "unAppID may be 0 for non-Steam shortcuts" in source
    assert "resolveLifetimeSession" in source
    assert "activeSessions.get(notification.nInstanceID)" in source


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
        'const refreshGamesCall = callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>("refresh_games");'
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


def test_frontend_displays_durable_operation_history() -> None:
    source = FRONTEND.read_text()

    assert "type GameOperationHistoryEntry = {" in source
    assert "type GameOperationHistory = {" in source
    assert "last_operation: GameOperationHistoryEntry | null;" in source
    assert "history: Record<string, GameOperationHistory>;" in source
    assert (
        "const [gameHistory, setGameHistory] = useState<Record<string, GameOperationHistory>>(globalGameHistory ?? {});"
        in source
    )
    assert "setGameHistory(result.history ?? {});" in source
    assert "Last Operation:" in source


def test_frontend_gates_warmed_background_refresh_without_loading_label() -> None:
    source = FRONTEND.read_text()

    assert "backgroundRefreshBusy" in source
    assert "setBackgroundRefreshBusy(isWarmed)" in source
    assert "operation.is_running || busyLabel !== null || backgroundRefreshBusy" in source
    assert 'if (!isWarmed) {\n      setBusyLabel("Loading");\n    }' in source


def test_frontend_applies_backend_selected_game_after_persisting() -> None:
    source = FRONTEND.read_text()

    assert "const result = await setSelectedGameCall(value);" in source
    assert "applySettings(result);" in source
    assert "setSelectedGame(result.selected_game);" in source


def test_frontend_syncs_warmed_settings_cache_when_refresh_defaults_selected_game() -> None:
    source = FRONTEND.read_text()

    assert "const syncSelectedGameCache = (nextSelectedGame: string) => {" in source
    assert "selected_game: nextSelectedGame" in source
    assert "syncSelectedGameCache(target);" in source
    assert "syncSelectedGameCache(firstGame);" in source
