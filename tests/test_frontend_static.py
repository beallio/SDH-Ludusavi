from pathlib import Path


FRONTEND = Path("src/index.tsx")


def test_frontend_exposes_sdh_ludusavi_panel_controls() -> None:
    source = FRONTEND.read_text()

    for text in [
        "SDH-Ludusavi",
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
    assert '"SDH-Ludusavi settings failed"' in source
    assert 'notify("failures_errors", "SDH-Ludusavi settings failed"' in source


def test_frontend_silences_lifecycle_toasts_when_auto_sync_is_disabled() -> None:
    source = FRONTEND.read_text()

    assert "let autoSyncNotificationsEnabled = false;" in source
    assert "autoSyncNotificationsEnabled = normalized.auto_sync_enabled;" in source
    assert "function shouldPublishAutoSyncStatusBeforeRpc(" in source
    assert "globalSettings === null || autoSyncNotificationsEnabled" in source
    assert "trackedAppIDs.size === 0 && trackedNames.size === 0" in source
    assert source.count("if (shouldPublishAutoSyncStatusBeforeRpc(tracked))") == 2

    start_status = 'publishAutoSyncStatus("checking", {'
    exit_status = 'publishAutoSyncStatus("checking", {'
    assert start_status in source
    assert exit_status in source

    assert source.index(start_status) < source.index(
        "const checkResult = await checkGameStartCall(name, appID);"
    )
    assert source.index(exit_status) < source.index(
        "const checkResult = await checkGameExitCall(name, appID);"
    )


def test_frontend_uses_browserview_only_autosync_status_strip() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'type AutoSyncStatusKind = "checking" | "backing_up" | "restoring" | "conflict" | "has_backup" | "unknown" | "error";',
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
        "onDismount()",
        "unregisterLifecycleNotifications();",
        "window.clearInterval(fallbackIntervalID);",
        "activeSessions.clear();",
        "destroyAutoSyncStatusBrowserView();",
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
        "const checkResult = await checkGameStartCall(name, appID);"
    )


def test_frontend_status_strip_matches_steamos_visual_contract() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "const STATUS_STRIP_HEIGHT_RATIO = 0.0475;",
        "const STEAM_BOTTOM_MENU_HEIGHT_RATIO = 0.02625;",
        "Math.round(rawHeight * STATUS_STRIP_HEIGHT_RATIO)",
        "Math.round(rawHeight * STEAM_BOTTOM_MENU_HEIGHT_RATIO)",
        "rawHeight - height - bottomOffset",
        "width: 100vw;",
        "height: 100vh;",
        "background: rgba(0, 0, 0, 0.34)",
        'font-family: "Motiva Sans", Arial, sans-serif;',
        "font-weight: 800;",
        "justify-content: center;",
        "min-width: 245px;",
        'state.status === "unknown" ? "#f59e0b"',
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
        'status === "checking"',
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
        'publishAutoSyncStatus("unknown", {',
        'publishAutoSyncStatus("error", {',
        'notify("failures_errors", "SDH-Ludusavi Auto-sync"',
    ]:
        assert required_text in source


def test_frontend_status_strip_uses_browserview_overlay_surface() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "type AutoSyncStatusBrowserView",
        "type AutoSyncStatusBrowserViewOwner",
        "let autoSyncStatusBrowserView: AutoSyncStatusBrowserView | null = null;",
        "let autoSyncStatusBrowserViewOwner: AutoSyncStatusBrowserViewOwner | null = null;",
        "let autoSyncStatusShowTimeoutID: number | null = null;",
        "let autoSyncStatusShowGeneration = 0;",
        "const AUTO_SYNC_STATUS_SHOW_DELAY = 100;",
        "function clearAutoSyncStatusShowTimeout()",
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
        "const showGeneration = ++autoSyncStatusShowGeneration;",
        "clearAutoSyncStatusShowTimeout();",
        "autoSyncStatusShowTimeoutID = window.setTimeout(() => {",
        "if (showGeneration !== autoSyncStatusShowGeneration || !currentAutoSyncStatusState.visible)",
        "}, AUTO_SYNC_STATUS_SHOW_DELAY);",
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

    sync_source = source[
        source.index("function syncAutoSyncStatusBrowserView(") : source.index(
            "function destroyAutoSyncStatusBrowserView()"
        )
    ]
    assert sync_source.index("browserView.SetVisible(false);") < sync_source.index(
        "browserView.LoadURL(url);"
    )

    destroy_source = source[
        source.index("function destroyAutoSyncStatusBrowserView()") : source.index(
            "type AutoSyncStatusPublishOptions"
        )
    ]
    assert "clearAutoSyncStatusShowTimeout();" in destroy_source

    dismount_source = source[source.index("onDismount()") :]
    assert "clearAutoSyncStatusShowTimeout();" in dismount_source


def test_frontend_status_strip_logs_status_provenance() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'type AutoSyncStatusSource = "lifecycle_start" | "lifecycle_exit" | "rpc_result" | "timeout" | "hide";',
        "source: AutoSyncStatusSource;",
        "gameName?: string;",
        "appID?: string;",
        "tracked?: boolean;",
        'resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];',
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
        'publishAutoSyncStatus("unknown", {',
    ]:
        assert required_text in source

    assert source.index('result.reason === "local_current"') < source.index(
        'publishAutoSyncStatus("unknown", {'
    )


def test_frontend_logs_lifecycle_rpc_boundaries() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'log("info", `Calling check_game_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);',
        "const checkResult = await checkGameStartCall(name, appID);",
        'log("info", `check_game_start result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);',
        'log("info", `Calling restore_game_on_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);',
        "const result = await restoreGameOnStartCall(name, appID);",
        'log("info", `restore_game_on_start result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);',
        'log("info", `Calling check_game_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);',
        "const checkResult = await checkGameExitCall(name, appID);",
        'log("info", `check_game_exit result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);',
        'log("info", `Calling backup_game_on_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);',
        "const result = await backupGameOnExitCall(name, appID);",
        'log("info", `backup_game_on_exit result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);',
    ]:
        assert required_text in source


def test_frontend_status_strip_uses_steam_aligned_autosync_copy() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'checking: "VERIFYING GAME SAVE"',
        'restoring: "RESTORING BACKUP SAVE"',
        'backing_up: "BACKING UP LOCAL SAVE"',
        'conflict: "SAVE CONFLICT"',
        'has_backup: "GAME SAVE UP TO DATE"',
        'error: "UNABLE TO SYNC"',
        'unknown: "UNKNOWN"',
    ]:
        assert required_text in source

    assert "BACKUP: RESTORING" not in source
    assert "BACKUP: BACKING UP" not in source


def test_frontend_lifecycle_publishes_actions_only_after_needed_checks() -> None:
    source = FRONTEND.read_text()

    start_source = source[
        source.index("const handleAppStart = async") : source.index("const handleAppExit = async")
    ]
    exit_source = source[
        source.index("const handleAppExit = async") : source.index(
            "const findRunningSessionByAppID"
        )
    ]

    assert start_source.index('publishAutoSyncStatus("checking", {') < start_source.index(
        "const checkResult = await checkGameStartCall(name, appID);"
    )
    assert start_source.index('checkResult.status === "needed"') < start_source.index(
        'publishAutoSyncStatus("restoring", {'
    )
    assert start_source.index('publishAutoSyncStatus("restoring", {') < start_source.index(
        "const result = await restoreGameOnStartCall(name, appID);"
    )

    assert exit_source.index('publishAutoSyncStatus("checking", {') < exit_source.index(
        "const checkResult = await checkGameExitCall(name, appID);"
    )
    assert exit_source.index('checkResult.status === "needed"') < exit_source.index(
        'publishAutoSyncStatus("backing_up", {'
    )
    assert exit_source.index('publishAutoSyncStatus("backing_up", {') < exit_source.index(
        "const result = await backupGameOnExitCall(name, appID);"
    )


def test_frontend_launch_gate_pauses_before_start_check_and_resumes_in_finally() -> None:
    source = FRONTEND.read_text()
    start_source = source[
        source.index("const handleAppStart = async") : source.index("const handleAppExit = async")
    ]

    for required_text in [
        'const pauseGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("pause_game_process");',
        'const resumeGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("resume_game_process");',
        "const handleAppStart = async (name: string, appID: string, instanceID?: number) => {",
        "const pauseResult = await pauseGameProcessCall(instanceID);",
        "const checkResult = await checkGameStartCall(name, appID);",
        "} finally {",
        "await resumeGameProcessCall(instanceID);",
        "void handleAppStart(session.name, session.appID, notification.nInstanceID);",
    ]:
        assert required_text in source

    assert start_source.index(
        "const pauseResult = await pauseGameProcessCall(instanceID);"
    ) < start_source.index("const checkResult = await checkGameStartCall(name, appID);")
    assert start_source.index("} finally {") < start_source.index(
        "await resumeGameProcessCall(instanceID);"
    )


def test_frontend_lifecycle_handlers_catch_rpc_failures_and_resume_failures() -> None:
    source = FRONTEND.read_text()
    start_source = source[
        source.index("const handleAppStart = async") : source.index("const handleAppExit = async")
    ]
    exit_source = source[
        source.index("const handleAppExit = async") : source.index(
            "const findRunningSessionByAppID"
        )
    ]

    for required_text in [
        "} catch (err) {",
        'log("error", `App start handling failed for ${name} (${appID}): ${err}`',
        'resultStatus: "failed"',
        "try {",
        "await resumeGameProcessCall(instanceID);",
        'log("error", `Failed to resume game process ${instanceID}: ${err}`',
    ]:
        assert required_text in start_source

    for required_text in [
        "} catch (err) {",
        'log("error", `App exit handling failed for ${name} (${appID}): ${err}`',
        'resultStatus: "failed"',
        "hideAutoSyncStatus({",
    ]:
        assert required_text in exit_source

    assert start_source.index(
        "const checkResult = await checkGameStartCall(name, appID);"
    ) < start_source.index(
        'log("error", `App start handling failed for ${name} (${appID}): ${err}`'
    )
    assert exit_source.index(
        "const checkResult = await checkGameExitCall(name, appID);"
    ) < exit_source.index('log("error", `App exit handling failed for ${name} (${appID}): ${err}`')


def test_frontend_conflict_modal_uses_backup_save_copy_not_cloud_save() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'type ConflictResolution = "keep_local" | "restore_backup";',
        'const resolveGameStartConflictCall = callable<[gameName: string, app_id: string | undefined, resolution: ConflictResolution], RpcResult<OperationResult>>("resolve_game_start_conflict");',
        "function showConflictResolutionModal",
        'strTitle="Conflict Detected"',
        "Keep Local Save",
        "Restore Backup Save",
        "backupModifiedAt",
        'publishAutoSyncStatus("conflict", {',
    ]:
        assert required_text in source

    assert "Download Cloud Save" not in source
    assert "Cloud Save" not in source


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
    assert "void handleAppStart(session.name, session.appID, notification.nInstanceID);" in source
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


def test_frontend_initial_load_skips_logs_and_warmed_refresh_when_cache_current() -> None:
    source = FRONTEND.read_text()

    load_initial = source[source.index("const loadInitial = async () => {") :]
    load_initial = load_initial[: load_initial.index("const applyRefreshResult")]
    assert "const loadedLogs = await getRecentLogs();" not in load_initial
    assert "setLogs(await getRecentLogs().catch(() => []));" not in load_initial
    assert (
        "const installedAppIdsChanged = globalInstalledAppIds !== installedAppIds;" in load_initial
    )
    assert (
        "const cacheCurrent = isWarmed && !installedAppIdsChanged && await "
        "isGameCacheCurrentCall(installedAppIds);"
    ) in load_initial
    assert "if (cacheCurrent && globalGames) {" in load_initial
    assert "applyCachedRefreshResult(" in load_initial
    assert load_initial.index("isGameCacheCurrentCall(installedAppIds)") < load_initial.index(
        "refreshGamesCall(false, installedAppIds)"
    )


def test_frontend_exposes_sdh_ludusavi_version_row() -> None:
    source = FRONTEND.read_text()

    assert "sdh_ludusavi?: string;" in source
    assert "decky?: string;" in source
    assert '<div>SDH-Ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>' in source
    assert '<div>Decky: {versions.decky ?? "Unknown"}</div>' in source
    assert source.index("SDH-Ludusavi:") < source.index("Ludusavi:")


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
        "const showPluginLogs = async () => {",
        "const currentLogs = await getRecentLogs();",
        "setLogs(currentLogs);",
        "showModal(<LogModal logs={currentLogs} />)",
        "onClick={() => void showPluginLogs()}",
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
    for required_text in [
        'const checkGameStartCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_start");',
        'const restoreGameOnStartCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("restore_game_on_start");',
        'const resolveGameStartConflictCall = callable<[gameName: string, app_id: string | undefined, resolution: ConflictResolution], RpcResult<OperationResult>>("resolve_game_start_conflict");',
        'const checkGameExitCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_exit");',
        'const backupGameOnExitCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("backup_game_on_exit");',
    ]:
        assert required_text in source


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


def test_frontend_qam_uses_global_and_game_panels() -> None:
    source = FRONTEND.read_text()

    assert 'PanelSection title="GLOBAL"' in source
    assert 'PanelSection title="GAME"' in source
    assert 'PanelSection title="Sync"' not in source

    global_panel = source[
        source.index('PanelSection title="GLOBAL"') : source.index('PanelSection title="GAME"')
    ]
    game_panel = source[
        source.index('PanelSection title="GAME"') : source.index(
            'PanelSection title="Notifications"'
        )
    ]

    assert global_panel.index('label="Automatic Sync"') < global_panel.index("Refresh Games")
    assert "Refresh Games" in global_panel
    assert "Select Game" not in global_panel
    assert "Force Backup" not in global_panel
    assert "Force Restore" not in global_panel

    for text in [
        "Select Game",
        "Status:",
        "Last Operation:",
        "Force Backup",
        "Force Restore",
    ]:
        assert text in game_panel


def test_frontend_qam_uses_custom_plugin_icon_and_plain_title() -> None:
    source = FRONTEND.read_text()

    assert "function PluginIcon()" in source
    assert "<PluginIcon />" in source
    assert "currentColor" in source
    assert 'width="1em"' in source
    assert 'height="1em"' in source
    assert "LuDatabaseBackup" not in source
    assert "staticClasses.Title" not in source
    assert 'titleView: <div className="sdh-ludusavi-title">SDH-Ludusavi</div>' in source


def test_frontend_qam_toggle_focus_stretches_to_panel_edges() -> None:
    source = FRONTEND.read_text()

    assert "function FullWidthToggle" in source
    assert 'className="sdh-ludusavi-full-width-toggle"' in source
    assert source.count("<FullWidthToggle>") == 5
    assert ".sdh-ludusavi-full-width-toggle" in source
    assert "margin-left: -32px;" in source
    assert "margin-right: -32px;" in source
    assert "width: 100%;" in source
    assert "box-sizing: border-box;" in source


def test_frontend_qam_toggles_explain_their_scope() -> None:
    source = FRONTEND.read_text()

    for text in [
        'description="Runs Ludusavi automatically when configured games start or exit."',
        'description="Enables or silences all SDH-Ludusavi toast notifications."',
        'description="Shows toasts for Force Backup and Force Restore results."',
        'description="Shows toasts when the game list refresh completes or fails."',
        'description="Shows warning toasts when sync or Ludusavi operations fail."',
    ]:
        assert text in source


def test_frontend_qam_uses_requested_row_separators() -> None:
    source = FRONTEND.read_text()

    for text, end_marker in [
        ('label="Automatic Sync"', "/>"),
        ("label={<CompactFieldLabel>Status:</CompactFieldLabel>}", "</Field>"),
        ("label={<CompactFieldLabel>Last Operation:</CompactFieldLabel>}", "</Field>"),
    ]:
        control = source[source.index(text) : source.index(end_marker, source.index(text))]
        assert 'bottomSeparator="none"' in control

    game_panel = source[
        source.index('PanelSection title="GAME"') : source.index(
            'PanelSection title="Notifications"'
        )
    ]
    force_backup_start = game_panel.rindex("<SpinnerButton", 0, game_panel.index("Force Backup"))
    force_backup = game_panel[force_backup_start : game_panel.index("Force Restore")]
    assert 'bottomSeparator="none"' in force_backup

    notifications_panel = source[
        source.index('PanelSection title="Notifications"') : source.index("<LudusaviPanel")
    ]
    for text in [
        'label="All Notifications"',
        'label="Manual Operations"',
        'label="Refresh Status"',
    ]:
        control = notifications_panel[
            notifications_panel.index(text) : notifications_panel.index(
                "/>", notifications_panel.index(text)
            )
        ]
        assert 'bottomSeparator="standard"' in control

    failures = notifications_panel[
        notifications_panel.index('label="Failures and Errors"') : notifications_panel.index(
            "/>", notifications_panel.index('label="Failures and Errors"')
        )
    ]
    assert 'bottomSeparator="none"' in failures

    logs_panel = source[
        source.index('PanelSection title="Logs"') : source.index('PanelSection title="Versions"')
    ]
    ludusavi_logs_start = logs_panel.rindex(
        "<ButtonItem", 0, logs_panel.index("View Ludusavi Logs")
    )
    ludusavi_logs = logs_panel[ludusavi_logs_start : logs_panel.index(">", ludusavi_logs_start)]
    assert 'bottomSeparator="standard"' in ludusavi_logs


def test_frontend_qam_rows_use_native_full_row_focus() -> None:
    source = FRONTEND.read_text()

    for text in [
        "Field",
        "highlightOnFocus={true}",
        "focusable={true}",
        '<ToggleField\n            label="Automatic Sync"\n            description="Runs Ludusavi automatically when configured games start or exit."\n            highlightOnFocus={true}',
        "<Field\n            label={<CompactFieldLabel>Status:</CompactFieldLabel>}",
        "<Field\n              label={<CompactFieldLabel>Last Operation:</CompactFieldLabel>}",
    ]:
        assert text in source

    versions_panel = source[source.index('PanelSection title="Versions"') :]
    assert (
        '<Field highlightOnFocus={true} focusable={true} childrenLayout="below" padding="standard" bottomSeparator="none">'
        in versions_panel
    )


def test_frontend_qam_last_operation_uses_single_line_ellipsis() -> None:
    source = FRONTEND.read_text()

    game_panel = source[
        source.index('PanelSection title="GAME"') : source.index(
            'PanelSection title="Notifications"'
        )
    ]
    last_operation = source[
        source.index("Last Operation:") : source.index(
            "Force Backup", source.index("Last Operation:")
        )
    ]
    assert "Last Operation:" in game_panel
    for text in [
        "minWidth: 0",
        'fontSize: "12px"',
        'whiteSpace: "nowrap"',
        'overflow: "hidden"',
        'textOverflow: "ellipsis"',
    ]:
        assert text in last_operation


def test_frontend_qam_status_and_last_operation_use_compact_typography() -> None:
    source = FRONTEND.read_text()

    status_field = source[
        source.index("label={<CompactFieldLabel>Status:</CompactFieldLabel>}") : source.index(
            "</Field>", source.index("label={<CompactFieldLabel>Status:</CompactFieldLabel>}")
        )
    ]
    last_operation_field = source[
        source.index(
            "label={<CompactFieldLabel>Last Operation:</CompactFieldLabel>}"
        ) : source.index(
            "</Field>",
            source.index("label={<CompactFieldLabel>Last Operation:</CompactFieldLabel>}"),
        )
    ]

    assert "function CompactFieldLabel" in source
    assert 'fontSize: "13px"' in source
    assert '[class*="Label"]' not in source
    assert 'className="sdh-ludusavi-status-field"' in status_field
    assert 'childrenContainerWidth="min"' in status_field
    assert 'padding="standard"' in status_field
    assert 'fontSize: "12px"' in status_field
    assert 'className="sdh-ludusavi-last-operation-field"' in last_operation_field
    assert 'childrenContainerWidth="min"' in last_operation_field
    assert 'padding="compact"' in last_operation_field
    assert 'maxWidth: "60%"' in last_operation_field


def test_frontend_versions_order_places_decky_last() -> None:
    source = FRONTEND.read_text()

    versions_panel = source[source.index('PanelSection title="Versions"') :]
    assert versions_panel.index("SDH-Ludusavi:") < versions_panel.index("Ludusavi:")
    assert versions_panel.index("Ludusavi:") < versions_panel.index("pyludusavi:")
    assert versions_panel.index("pyludusavi:") < versions_panel.index("Decky:")
    assert 'className="sdh-ludusavi-versions-list"' in versions_panel
    assert 'childrenLayout="below"' in versions_panel


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


def test_frontend_resets_qam_scroll_when_quick_access_opens() -> None:
    source = FRONTEND.read_text()

    assert "useQuickAccessVisible" in source
    assert "const isQuickAccessVisible = useQuickAccessVisible();" in source
    assert "const qamContentRef = useRef<HTMLDivElement | null>(null);" in source
    assert "const wasQuickAccessVisible = useRef(false);" in source
    assert "function resetQuickAccessScroll(" in source
    assert "findScrollableParent(" in source
    assert "window.requestAnimationFrame(() => {" in source
    assert 'scrollable.scrollTo({ top: 0, left: 0, behavior: "auto" });' in source
    assert 'container.scrollIntoView({ block: "start" });' in source
    assert "isQuickAccessVisible && !wasQuickAccessVisible.current" in source
    assert "ref={qamContentRef}" in source


def test_frontend_logs_and_retries_qam_scroll_reset() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        'function resetQuickAccessScroll(container: HTMLElement | null, reason = "qam_open")',
        "const resetDelays = [50, 150, 350];",
        "resetDelays.forEach((delay) => {",
        "window.setTimeout(() => resetQuickAccessScroll(qamContentRef.current, `qam_open_retry_${delay}`), delay);",
        "const beforeContainerTop = container?.getBoundingClientRect?.().top ?? -1;",
        "Math.abs(beforeContainerTop - containerTop) <= QUICK_ACCESS_TOP_EPSILON_PX",
        "`QAM scroll reset (${reason}): before=${beforeTop}, after=${afterTop}, containerTop=${containerTop}, scrollable=${scrollableTag}`",
    ]:
        assert required_text in source

    assert "qam_open_retry_0" not in source


def test_frontend_preserves_always_render_for_lifecycle_and_status_surface() -> None:
    source = FRONTEND.read_text()

    plugin_return = source[source.index('return {\n    name: "SDH-Ludusavi"') :]
    assert "alwaysRender: true" in plugin_return
    assert "onDismount()" in plugin_return
    for required_text in [
        "unregisterLifecycleNotifications();",
        "window.clearInterval(fallbackIntervalID);",
        "activeSessions.clear();",
        "clearAutoSyncStatusHideTimeout();",
        "destroyAutoSyncStatusBrowserView();",
    ]:
        assert required_text in plugin_return


def test_frontend_prefers_main_running_app_for_qam_game_selection() -> None:
    source = FRONTEND.read_text()

    assert "function getMainRunningSession(): RunningSession | null" in source
    assert "sessionFromAppOverview((Router as any).MainRunningApp);" in source
    assert 'source: "running"' in source
    assert "function getPreferredSteamGameSession(): RunningSession | null" in source
    assert "function getGameSteamAppID(game: GameStatus): string | null" in source
    assert "function findGameForRunningSession(" in source
    assert "gameAppID === session.appID" in source
    assert "normalize(game.name) === normalize(session.name)" in source
    assert "function selectCurrentSteamGameIfAvailable(" in source
    assert (
        "const runningGame = findGameForRunningSession(currentGames, runningSession, currentAliases);"
        in source
    )
    assert "setSelectedGame(runningGame.game.name);" in source


def test_frontend_applies_current_game_before_saved_selected_game() -> None:
    source = FRONTEND.read_text()

    apply_refresh = source[
        source.index("const applyRefreshResult =") : source.index("const refreshGames =")
    ]
    assert (
        "if (selectCurrentSteamGameIfAvailable(result.games, result.aliases || {})) {"
        in apply_refresh
    )
    assert "const target = preferredGame || selectedGame;" in apply_refresh
    assert apply_refresh.index(
        "selectCurrentSteamGameIfAvailable(result.games, result.aliases || {})"
    ) < apply_refresh.index("const target = preferredGame || selectedGame;")
    assert "const pendingCurrentGameSelection = useRef(false);" in source
    assert "pendingCurrentGameSelection.current = true;" in source
    assert "pendingCurrentGameSelection.current = false;" in source
    assert "void onGameChange(data)" in source
    assert "const result = await setSelectedGameCall(value);" in source


def test_frontend_logs_current_game_context_and_match_reason() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "type RunningSession = {",
        'source?: "focused" | "route" | "cached" | "running";',
        "function describeSteamGameSession(",
        "function logCurrentGameSelection(",
        "function logCurrentGameNoMatch(",
        "context=${describeSteamGameSession(session)}",
        "match=${runningGame.name}",
        "reason=${reason}",
        "games=${currentGames.length}",
        "aliasKeys=${Object.keys(currentAliases).length}",
    ]:
        assert required_text in source

    no_match = source[
        source.index("function logCurrentGameNoMatch(") : source.index(
            "function findScrollableParent("
        )
    ]
    assert 'session ? "warning" : "debug"' in no_match


def test_frontend_matches_current_game_through_ludusavi_aliases() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "function findGameForRunningSession(",
        "currentAliases: Record<string, string>",
        "const aliasTarget = findAliasTargetForSession(session, currentAliases);",
        "function findAliasTargetForSession(",
        "normalize(alias) === normalizedSessionName",
        "normalize(target) === normalizedSessionName",
        'return { game: aliasMatch, reason: "alias" };',
        "selectCurrentSteamGameIfAvailable(result.games, result.aliases || {})",
    ]:
        assert required_text in source


def test_frontend_captures_home_library_focused_game_context() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "let lastSteamUiGameContext: RunningSession | null = null;",
        "function captureSteamUiGameContext(): RunningSession | null",
        "function getFocusedSteamGameSession(): RunningSession | null",
        "function getSteamUiReactPropCandidates(",
        "__reactProps$",
        "__reactFiber$",
        "__reactInternalInstance$",
        'doc.querySelectorAll(":hover")',
        'doc.querySelector(".gpfocus, .gpfocuswithin, :focus")',
        "lastSteamUiGameContext = session;",
        "window.setInterval(captureSteamUiGameContext, 500);",
    ]:
        assert required_text in source


def test_frontend_resolves_selected_library_route_app_context() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "function getRouteSteamGameSession(): RunningSession | null",
        "function sessionFromRoutePath(path: string): RunningSession | null",
        "match(/(?:\\/routes)?\\/library\\/app\\/(\\d+)/)",
        "function getSteamAppNameFromStores(appID: string): string | null",
        "appStore?.GetAppOverviewByAppID",
        "collectionStore?.allGamesCollection?.allApps",
        "mainWindow?.location?.pathname",
        "mainWindow?.location?.hash",
    ]:
        assert required_text in source


def test_frontend_prefers_focused_or_selected_game_before_running_game() -> None:
    source = FRONTEND.read_text()

    preferred = source[
        source.index("function getPreferredSteamGameSession") : source.index(
            "function findGameForRunningSession"
        )
    ]
    assert "captureSteamUiGameContext()" in preferred
    assert "getRecentSteamUiGameContext()" in preferred
    assert "getMainRunningSession()" in preferred
    assert preferred.index("captureSteamUiGameContext()") < preferred.index(
        "getMainRunningSession()"
    )


def test_frontend_load_initial_optimizations() -> None:
    source = FRONTEND.read_text()

    # Verify placeholder state for versions on initialization
    assert 'sdh_ludusavi: "Loading..."' in source
    assert 'ludusavi: "Loading..."' in source
    assert 'pyludusavi: "Loading..."' in source
    assert 'decky: "Loading..."' in source

    # Verify loadInitial structure (non-blocking versions and command loading)
    load_initial = source[source.index("const loadInitial = async () => {") :]
    load_initial = load_initial[: load_initial.index("const applyRefreshResult")]

    assert "Load versions and commands in the background" in load_initial
    assert "const loadedSettings = await getSettings();" in load_initial

    # Verify the Promise.all for settings is NOT there (since settings is loaded on its own now)
    assert (
        "Promise.all([\n        getSettings(),\n        getVersions(),\n        getLudusaviCommandCall()\n      ])"
        not in load_initial
    )

    # Verify background loader handles error states appropriately
    assert 'setVersions({ message: loadedVersions.message || "Error" });' in load_initial
    assert 'setVersions({ message: "Error" });' in load_initial
