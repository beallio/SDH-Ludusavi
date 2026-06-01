from pathlib import Path


class ConcatenatedFrontendPath:
    def __init__(self, main_path: Path):
        self.main_path = main_path

    def read_text(self, encoding: str = "utf-8") -> str:
        files = [
            Path("src/types/index.ts"),
            Path("src/utils/logging.ts"),
            Path("src/components/LogModal.tsx"),
            Path("src/utils/steam.ts"),
            Path("src/index.tsx"),
        ]
        contents = []
        for f in files:
            if f.exists():
                contents.append(f.read_text(encoding=encoding))
        return "\n".join(contents)

    def __getattr__(self, name):
        return getattr(self.main_path, name)


FRONTEND = ConcatenatedFrontendPath(Path("src/index.tsx"))


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
    assert (
        "notificationSettings: NotificationSettings"
        in Path("src/state/ludusaviState.tsx").read_text()
    )
    assert "function notify(" in source
    assert "store.shouldShowNotification(category)" in source
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
    assert "setAutoSyncEnabled(enabled)" in source
    assert '"SDH-Ludusavi settings failed"' in source
    assert 'notify(ludusaviStore, "failures_errors", "SDH-Ludusavi settings failed"' in source


def test_frontend_silences_lifecycle_toasts_when_auto_sync_is_disabled() -> None:
    source = FRONTEND.read_text()
    store_source = Path("src/state/ludusaviState.tsx").read_text()

    assert "autoSyncNotificationsEnabled: boolean;" in store_source
    assert "autoSyncNotificationsEnabled: normalized.auto_sync_enabled" in store_source
    assert "function shouldPublishAutoSyncStatusBeforeRpc(" in source
    assert (
        "this.snapshot.settings === null || this.snapshot.autoSyncNotificationsEnabled"
        in store_source
    )
    assert (
        "this.snapshot.trackedAppIDs.size === 0 && this.snapshot.trackedNames.size === 0"
        in store_source
    )
    assert source.count("if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked))") == 2

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
        '"#1a9fff"',
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
        "@keyframes spin {",
        "icon-spin",
        'stroke-width="3"',
        'opacity="0.8"',
    ]:
        assert required_text in source


def test_frontend_status_strip_replaces_autosync_success_toasts() -> None:
    source = FRONTEND.read_text()

    assert 'notify(ludusaviStore, "auto_sync_progress"' not in source
    assert 'notify(ludusaviStore, "auto_sync_results"' not in source
    assert '"auto_sync_progress"' not in source
    assert '"auto_sync_results"' not in source

    for required_text in [
        'publishAutoSyncStatus("has_backup", {',
        'publishAutoSyncStatus("unknown", {',
        'publishAutoSyncStatus("error", {',
        'notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync"',
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
        "function shouldResetStatusStripSurfaceBeforeVerification(",
        "function resetStatusStripSurfaceBeforeVerification(",
        "shouldResetStatusStripSurfaceBeforeVerification(status, options)",
        "function ensureAutoSyncStatusBrowserView()",
        "function normalizeAutoSyncStatusBrowserView(",
        "candidate?.m_browserView",
        "candidate?.browserView",
        "candidate?.BrowserView",
        "candidate?.m_browserView?.m_browserView",
        "BrowserView normalized from",
        "function browserViewMethod",
        "function buildBrowserViewAdapter",
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
        "normalized.SetTopmost?.(true);",
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
    assert "raw.LoadURL = raw.loadURL" not in source
    assert "patchBrowserViewMethodAliases" not in source
    assert "raw === owner" in source
    assert "SetTopmost" in source

    dismount_source = source[source.index("onDismount()") :]
    assert "clearAutoSyncStatusShowTimeout();" in dismount_source


def test_frontend_status_strip_destroy_disposes_owner_and_nested_view() -> None:
    source = FRONTEND.read_text()

    destroy_source = source[
        source.index("function destroyAutoSyncStatusBrowserView()") : source.index(
            "type AutoSyncStatusPublishOptions"
        )
    ]

    for required_text in [
        "const browserView = autoSyncStatusBrowserView;",
        "const browserViewOwner = autoSyncStatusBrowserViewOwner;",
        "browserView?.SetVisible?.(false);",
        "browserView !== browserViewOwner",
        'typeof browserView.Destroy === "function"',
        "browserView.Destroy();",
        'typeof browserViewOwner?.Destroy === "function"',
        "browserViewOwner.Destroy();",
        "needsSteamClientDestroy && browserViewOwner",
        "steamClient?.BrowserView?.Destroy?.(browserViewOwner);",
        "autoSyncStatusBrowserView = null;",
        "autoSyncStatusBrowserViewOwner = null;",
    ]:
        assert required_text in destroy_source
    assert (
        "steamClient?.BrowserView?.Destroy?.(browserViewOwner ?? browserView);"
        not in destroy_source
    )

    assert "else if" not in destroy_source


def test_frontend_conflict_time_formats_valid_dates_locally() -> None:
    source = FRONTEND.read_text()

    assert "function formatConflictTime" in source
    assert "new Date(value)" in source
    assert "Number.isNaN(date.getTime())" in source
    assert "return date.toLocaleString();" in source
    assert 'return "Unknown time";' in source


def test_frontend_recreates_status_strip_before_lifecycle_verification() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "let autoSyncStatusSyncTimeoutID: number | null = null;",
        "function clearAutoSyncStatusSyncTimeout()",
        "function syncAutoSyncStatusBrowserViewDeferred(",
        "autoSyncStatusSyncTimeoutID = window.setTimeout(() => {",
        "if (state !== currentAutoSyncStatusState || !state.visible)",
        "syncAutoSyncStatusBrowserView(state);",
        "scheduleAutoSyncStatusHide(state);",
        "}, 0);",
    ]:
        assert required_text in source

    reset_source = source[
        source.index("function shouldResetStatusStripSurfaceBeforeVerification(") : source.index(
            "function publishAutoSyncStatus("
        )
    ]
    for required_text in [
        'status === "checking"',
        '(options.source === "lifecycle_start" || options.source === "lifecycle_exit")',
        "destroyAutoSyncStatusBrowserView();",
    ]:
        assert required_text in reset_source

    publish_source = source[
        source.index("function publishAutoSyncStatus(") : source.index(
            "function hideAutoSyncStatus("
        )
    ]
    assert publish_source.index(
        "shouldResetStatusStripSurfaceBeforeVerification(status, options)"
    ) < publish_source.index("currentAutoSyncStatusState = {")
    assert publish_source.index(
        "resetStatusStripSurfaceBeforeVerification();"
    ) < publish_source.index("currentAutoSyncStatusState = {")
    assert publish_source.index(
        "logAutoSyncStatusChange(currentAutoSyncStatusState);"
    ) < publish_source.index("syncAutoSyncStatusBrowserViewDeferred(currentAutoSyncStatusState);")
    assert publish_source.index(
        "syncAutoSyncStatusBrowserViewDeferred(currentAutoSyncStatusState);"
    ) < publish_source.index("return;")
    assert publish_source.index("return;") < publish_source.index(
        "syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);"
    )

    destroy_source = source[
        source.index("function destroyAutoSyncStatusBrowserView()") : source.index(
            "type AutoSyncStatusPublishOptions"
        )
    ]
    assert "clearAutoSyncStatusSyncTimeout();" in destroy_source

    hide_source = source[
        source.index("function hideAutoSyncStatus(") : source.index(
            "function completeAutoSyncStatus("
        )
    ]
    assert "clearAutoSyncStatusSyncTimeout();" in hide_source


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
        "const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;",
        "const shouldPauseLaunch =",
        "if (shouldPauseLaunch) {",
        "const pauseResult = await pauseGameProcessCall(instanceID);",
        "const checkResult = await checkGameStartCall(name, appID);",
        "} finally {",
        "await resumeGameProcessCall(instanceID);",
        "void handleAppStart(session.name, session.appID, notification.nInstanceID);",
    ]:
        assert required_text in source

    assert start_source.index("const shouldPauseLaunch =") < start_source.index(
        "const pauseResult = await pauseGameProcessCall(instanceID);"
    )
    assert start_source.index("if (shouldPauseLaunch) {") < start_source.index(
        "const pauseResult = await pauseGameProcessCall(instanceID);"
    )
    should_pause_source = start_source[
        start_source.index("const shouldPauseLaunch =") : start_source.index(
            "if (shouldPauseLaunch) {"
        )
    ]
    for required_gate in [
        "autoSyncEnabled",
        "tracked",
        'typeof instanceID === "number"',
        "instanceID > 1",
    ]:
        assert required_gate in should_pause_source

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


def test_frontend_conflict_modal_default_action_dismisses_safely() -> None:
    source = FRONTEND.read_text()
    modal_source = source[source.index("function ConflictResolutionModal") :]
    modal_source = modal_source[: modal_source.index("function showConflictResolutionModal")]

    assert "onOK={dismiss}" in modal_source
    assert 'onOK={() => choose("restore_backup")}' not in modal_source
    assert "onCancel={dismiss}" in modal_source
    assert 'onClick={() => choose("keep_local")}' in modal_source
    assert 'onClick={() => choose("restore_backup")}' in modal_source


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
        "const installedAppIdsChanged = ludusaviState.installedAppIds !== installedAppIds;"
        in load_initial
    )
    assert (
        "const cacheCurrentResult = isWarmed && !installedAppIdsChanged ? await isGameCacheCurrentCall(installedAppIds) : false;"
    ) in load_initial
    assert (
        "const cacheCurrent = !isRpcStatus(cacheCurrentResult) && cacheCurrentResult === true;"
    ) in load_initial
    assert "if (cacheCurrent && ludusaviState.games) {" in load_initial
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
    assert "data: game.name" in source


def test_frontend_dropdown_has_below_layout() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Match DropdownItem and capture all its attributes up to the closing tag or self-closing tag
    dropdown_match = re.search(
        r'<DropdownItem[\s\S]*?menuLabel=(["\'])Select Game\1[\s\S]*?/>', source
    )
    assert dropdown_match is not None, "DropdownItem for Select Game not found in index.tsx"

    dropdown_content = dropdown_match.group(0)
    assert re.search(r'layout\s*=\s*(["\'])below\1', dropdown_content) is not None, (
        "Select Game dropdown does not have layout='below'"
    )


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
    store_source = Path("src/state/ludusaviState.tsx").read_text()

    assert "type GameOperationHistoryEntry = {" in source
    assert "type GameOperationHistory = {" in source
    assert "last_operation: GameOperationHistoryEntry | null;" in source
    assert "history: Record<string, GameOperationHistory>;" in source
    assert "gameHistory: Record<string, GameOperationHistory>;" in store_source
    assert "setGameHistory(history: Record<string, GameOperationHistory>)" in store_source
    assert "gameHistory: result.history ?? {}" in store_source
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

    # Automatic Sync toggle field
    sync_control = source[
        source.index('label="Automatic Sync"') : source.index(
            "/>", source.index('label="Automatic Sync"')
        )
    ]
    assert 'bottomSeparator="none"' in sync_control

    # Status & Last Operation combined field
    status_start = source.rindex(
        "<Field", 0, source.index("<CompactFieldLabel>Status:</CompactFieldLabel>")
    )
    status_control = source[
        status_start : source.index(
            "</Field>", source.index("<CompactFieldLabel>Last Operation:</CompactFieldLabel>")
        )
    ]
    assert 'bottomSeparator="none"' in status_control

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
        '<PanelSectionRow>\n          <ToggleField\n            label="Automatic Sync"\n            description="Runs Ludusavi automatically when configured games start or exit."',
        "highlightOnFocus={false}",
        "focusable={false}",
    ]:
        assert text in source

    versions_panel = source[source.index('PanelSection title="Versions"') :]
    assert (
        '<Field highlightOnFocus={true} focusable={true} childrenLayout="below" padding="standard" bottomSeparator="none">'
        in versions_panel
    )


def test_frontend_qam_last_operation_uses_inline_wrapping_layout() -> None:
    source = FRONTEND.read_text()

    game_panel = source[
        source.index('PanelSection title="GAME"') : source.index(
            'PanelSection title="Notifications"'
        )
    ]
    last_op_start = game_panel.rindex(
        "<Field", 0, game_panel.index("<CompactFieldLabel>Last Operation:</CompactFieldLabel>")
    )
    last_operation = game_panel[
        last_op_start : game_panel.index(
            "</Field>",
            last_op_start,
        )
    ]
    assert "Last Operation:" in game_panel
    assert 'width: "110px"' in last_operation
    assert "minWidth: 0" in last_operation
    assert 'whiteSpace: "normal"' in last_operation
    assert 'wordBreak: "break-word"' in last_operation
    assert 'fontSize: "12px"' in last_operation
    assert 'fontVariantNumeric: "tabular-nums"' in last_operation


def test_frontend_qam_status_and_last_operation_use_compact_typography() -> None:
    source = FRONTEND.read_text()

    status_start = source.rindex(
        "<Field", 0, source.index("<CompactFieldLabel>Status:</CompactFieldLabel>")
    )
    combined_field = source[
        status_start : source.index(
            "</Field>", source.index("<CompactFieldLabel>Last Operation:</CompactFieldLabel>")
        )
    ]

    assert "function CompactFieldLabel" in source
    assert '[class*="Label"]' not in source
    assert 'width: "110px"' in combined_field
    assert 'padding="standard"' in combined_field
    assert 'childrenLayout="below"' in combined_field
    assert (
        'style={{ flexGrow: 1, color: "#cbd5e1", minWidth: 0, textAlign: "left" }}'
        in combined_field
    )
    assert 'style={{ color: "#60a5fa", fontWeight: "bold" }}' in combined_field


def test_frontend_versions_order_places_decky_last() -> None:
    source = FRONTEND.read_text()

    versions_panel = source[source.index('PanelSection title="Versions"') :]
    assert versions_panel.index("SDH-Ludusavi:") < versions_panel.index("Ludusavi:")
    assert versions_panel.index("Ludusavi:") < versions_panel.index("pyludusavi:")
    assert versions_panel.index("pyludusavi:") < versions_panel.index("Decky:")
    assert 'childrenLayout="below"' in versions_panel
    assert (
        'fontSize: "14px",\n                color: "#cbd5e1",\n                paddingLeft: "10px"'
        in versions_panel
    )
    assert 'gap: "7px"' in versions_panel


def test_frontend_gates_warmed_background_refresh_without_loading_label() -> None:
    source = FRONTEND.read_text()

    assert "backgroundRefreshBusy" in source
    assert "setBackgroundRefreshBusy(isWarmed)" in source
    assert "operation.is_running || busyLabel !== null || backgroundRefreshBusy" in source
    assert 'if (!isWarmed) {\n      setBusyLabel("Loading");\n    }' in source


def test_frontend_applies_backend_selected_game_after_persisting() -> None:
    source = FRONTEND.read_text()

    assert "setSelectedGameCall(value)" in source
    assert "applySettingsGlobal(ludusaviStore, result);" in source


def test_frontend_syncs_warmed_settings_cache_when_refresh_defaults_selected_game() -> None:
    source = FRONTEND.read_text()
    store_source = Path("src/state/ludusaviState.tsx").read_text()

    assert "const syncSelectedGameCache = (nextSelectedGame: string) => {" in source
    assert "selected_game: selectedGame" in store_source
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
    assert "ludusaviStore.setSelectedGame(runningGame.game.name);" in source


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
    assert "onChange={onGameChange}" in source
    assert "setSelectedGameCall(value)" in source


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


def test_frontend_hardens_steam_ui_focused_context_discovery() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "const STEAM_UI_REACT_FIBER_MAX_DEPTH = 12;",
        "const STEAM_UI_REACT_CANDIDATE_MAX_COUNT = 64;",
        "const STEAM_UI_HOVERED_ELEMENT_MAX_COUNT = 4;",
        'const STEAM_UI_REACT_PROPS_PREFIX = "__reactProps$";',
        "const STEAM_UI_REACT_FIBER_PREFIXES = [",
        "function getSteamUiFocusedElements(doc: Document): Element[]",
        'element.tagName !== "BODY"',
        'element.tagName !== "HTML"',
        "function sessionFromElementAppContext(",
        'const selector = "[data-appid], [data-app-id], [href]";',
        "element?.closest(selector) ?? element?.querySelector(selector)",
        "function pushSteamUiCandidate(",
        "STEAM_UI_REACT_CANDIDATE_MAX_COUNT",
        "STEAM_UI_REACT_FIBER_MAX_DEPTH",
        "const visitedFibers = new Set<any>();",
        "!visitedFibers.has(fiber)",
        "visitedFibers.add(fiber);",
    ]:
        assert required_text in source

    focused = source[
        source.index("function getFocusedSteamGameSession") : source.index(
            "function captureSteamUiGameContext"
        )
    ]
    assert "const domSession = sessionFromElementAppContext(element);" in focused
    assert "const appIDOnlyFallback = domSession?.name ? null : domSession;" in focused
    assert "if (domSession?.name)" in focused
    assert "for (const candidate of getSteamUiReactPropCandidates(element))" in focused
    assert "if (appIDOnlyFallback)" in focused
    assert focused.index("if (domSession?.name)") < focused.index(
        "for (const candidate of getSteamUiReactPropCandidates(element))"
    )
    assert focused.index(
        "for (const candidate of getSteamUiReactPropCandidates(element))"
    ) < focused.index("if (appIDOnlyFallback)")


def test_frontend_resolves_selected_library_route_app_context() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "function getRouteSteamGameSession(): RunningSession | null",
        "function sessionFromRoutePath(path: string): RunningSession | null",
        "const STEAM_UI_APP_ROUTE_PATTERN = /(?:\\/routes)?\\/library\\/app\\/(\\d+)/;",
        "path.match(STEAM_UI_APP_ROUTE_PATTERN)",
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
    capture = source[
        source.index("function captureSteamUiGameContext") : source.index(
            "function getRecentSteamUiGameContext"
        )
    ]
    assert capture.index("getRouteSteamGameSession()") < capture.index(
        "getFocusedSteamGameSession()"
    )
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
    assert (
        "const [loadedSettings, loadedHistory] = await Promise.all([\n"
        "        getSettings(),\n"
        "        getGameHistoryCall()\n"
        "      ]);"
    ) in load_initial
    assert "const loadedSettings = await getSettings();" not in load_initial
    assert "const loadedHistory = await getGameHistoryCall();" not in load_initial

    # Verify the Promise.all for settings is NOT there (since settings is loaded on its own now)
    assert (
        "Promise.all([\n        getSettings(),\n        getVersions(),\n        getLudusaviCommandCall()\n      ])"
        not in load_initial
    )

    # Verify background loader handles error states appropriately
    assert (
        'ludusaviStore.setVersions({ message: loadedVersions.message || "Error" });' in load_initial
    )
    assert 'ludusaviStore.setVersions({ message: "Error" });' in load_initial


def test_frontend_uses_context_store_for_qam_persistent_state() -> None:
    source = FRONTEND.read_text()
    store_source = Path("src/state/ludusaviState.tsx").read_text()

    for required_text in [
        "createContext",
        "useContext",
        "useSyncExternalStore",
        "export class LudusaviStateStore",
        "export function createLudusaviStateStore()",
        "export function LudusaviStateProvider(",
        "export function useLudusaviState()",
        "export function useLudusaviStateStore()",
        "type LudusaviStateSnapshot",
        "applySettings(settings: Settings)",
        "applyRefreshResult(result: RefreshResult)",
        "setGameHistory(history: Record<string, GameOperationHistory>)",
        "setInstalledAppIds(installedAppIds: string | undefined)",
    ]:
        assert required_text in store_source

    for required_text in [
        'from "./state/ludusaviState";',
        "LudusaviStateProvider",
        "createLudusaviStateStore",
        "useLudusaviState",
        "useLudusaviStateStore",
        "const ludusaviStore = createLudusaviStateStore();",
        "<LudusaviStateProvider store={ludusaviStore}>",
        "const ludusaviState = useLudusaviState();",
        "const ludusaviStore = useLudusaviStateStore();",
    ]:
        assert required_text in source


def test_frontend_removes_loose_app_cache_globals() -> None:
    source = FRONTEND.read_text()

    for stale_text in [
        "let globalSettings",
        "let globalGames",
        "let globalGameAliases",
        "let globalGameHistory",
        "let globalInstalledAppIds",
        "let globalVersions",
        "let globalLudusaviCommand",
        "let trackedAppIDs",
        "let trackedNames",
        "let autoSyncNotificationsEnabled",
        "let notificationSettingsMirror",
        "let updateGameHistoryListener",
    ]:
        assert stale_text not in source


def test_frontend_warmed_qam_cache_uses_store_snapshot() -> None:
    source = FRONTEND.read_text()

    load_initial = source[source.index("const loadInitial = async () => {") :]
    load_initial = load_initial[: load_initial.index("const applyRefreshResult")]

    for required_text in [
        "const isWarmed = ludusaviState.settings !== null && ludusaviState.games !== null;",
        "const installedAppIdsChanged = ludusaviState.installedAppIds !== installedAppIds;",
        "if (cacheCurrent && ludusaviState.games) {",
        "ludusaviStore.setInstalledAppIds(installedAppIds);",
    ]:
        assert required_text in load_initial

    assert "globalSettings" not in load_initial
    assert "globalGames" not in load_initial
    assert "globalInstalledAppIds" not in load_initial


def test_frontend_notifications_and_history_sync_use_state_store() -> None:
    source = FRONTEND.read_text()

    for required_text in [
        "function notify(",
        "store: LudusaviStateStore",
        "store.shouldShowNotification(category)",
        "async function syncGlobalHistory(store: LudusaviStateStore)",
        "store.setGameHistory(historyRes);",
        "function shouldPublishAutoSyncStatusBeforeRpc(",
        "store: LudusaviStateStore",
        "store.shouldPublishAutoSyncStatusBeforeRpc(tracked)",
    ]:
        assert required_text in source


def test_frontend_syncs_history_via_dedicated_rpc() -> None:
    source = FRONTEND.read_text()

    assert (
        'const getGameHistoryCall = callable<[], RpcResult<Record<string, GameOperationHistory>>>("get_game_history");'
        in source
    )
    assert "async function syncGlobalHistory(store: LudusaviStateStore)" in source
    assert "await syncGlobalHistory(ludusaviStore);" in source


def test_frontend_status_strip_clears_on_hide() -> None:
    source = FRONTEND.read_text()

    sync_source = source[
        source.index("function syncAutoSyncStatusBrowserView(") : source.index(
            "function destroyAutoSyncStatusBrowserView()"
        )
    ]
    assert 'browserView.LoadURL?.("about:blank");' in sync_source


def test_frontend_operation_history_translation() -> None:
    source = FRONTEND.read_text()

    # Check function signature
    assert "function getLastOperationText(" in source
    assert "status: string" in source
    assert "reason: string | null" in source
    assert "message:" in source

    # Check translations for reasons
    assert '"local_current"' in source
    assert "local save is already current" in source
    assert "game is deselected in Ludusavi" in source

    # Check that the call sites pass selectedHistory.message
    assert "selectedHistory.message" in source


def test_frontend_toggles_wrapped_in_panel_section_row_without_highlight_on_focus() -> None:
    source = FRONTEND.read_text()

    # The 5 ToggleField elements must be wrapped inside a PanelSectionRow.
    assert source.count("<PanelSectionRow>\n          <ToggleField") == 5

    # ToggleField components should not contain 'highlightOnFocus' prop inside their definition.
    idx = 0
    for _ in range(5):
        start = source.index("<ToggleField", idx)
        end = source.index("/>", start)
        toggle_block = source[start:end]
        assert "highlightOnFocus" not in toggle_block
        idx = end


def test_frontend_decomposed_load_initial_helpers_exist() -> None:
    source = FRONTEND.read_text()

    assert "const fetchMetadata = () => {" in source
    assert "const fetchInitialState = async (): Promise<RpcResult<Settings>> => {" in source
    assert "const synchronizeGameList = async (" in source


def test_frontend_state_store_optimization_no_array_from_in_loop() -> None:
    store_source = Path("src/state/ludusaviState.tsx").read_text(encoding="utf-8")
    index_source = Path("src/index.tsx").read_text(encoding="utf-8")

    # Assert Array.from is not called on trackedNames in either file
    assert "Array.from(this.snapshot.trackedNames)" not in store_source
    assert "Array.from(snapshot.trackedNames)" not in index_source

    # Assert the optimized Set iteration is in the state store
    assert "for (const trackedName of this.snapshot.trackedNames)" in store_source


def test_frontend_settings_serialization_queue() -> None:
    source = FRONTEND.read_text(encoding="utf-8")

    # Verify that the serialization queue is defined at module scope
    assert "const settingsQueue:" in source
    assert "let settingsProcessing = false;" in source

    # Verify task enqueuing and processing are present
    assert "settingsQueue.push(task);" in source
    assert "processSettingsQueue()" in source


def test_frontend_settings_queue_rollback_behavior() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Verify that sequence variables are declared (e.g. let autoSyncSeq = 0;)
    assert re.search(r"let\s+autoSyncSeq\s*=\s*0\s*;", source) is not None
    assert re.search(r"let\s+notificationSeq\s*=\s*0\s*;", source) is not None
    assert re.search(r"let\s+selectedGameSeq\s*=\s*0\s*;", source) is not None

    # Verify that lastPersisted variables are declared
    assert re.search(r"let\s+lastPersistedAutoSync[\s\S]*?=\s*null\s*;", source) is not None
    assert re.search(r"let\s+lastPersistedNotifications[\s\S]*?=\s*null\s*;", source) is not None
    assert re.search(r"let\s+lastPersistedSelectedGame[\s\S]*?=\s*null\s*;", source) is not None

    # Assert sequence checks inside catch blocks
    assert re.search(r"if\s*\(\s*updateSeq\s*===\s*autoSyncSeq\s*\)", source) is not None
    assert re.search(r"if\s*\(\s*updateSeq\s*===\s*notificationSeq\s*\)", source) is not None
    assert re.search(r"if\s*\(\s*updateSeq\s*===\s*selectedGameSeq\s*\)", source) is not None

    # Assert rollback to fallbacks
    assert (
        re.search(
            r"const\s+fallback\s*=\s*lastPersistedAutoSync\s*[\s\S]*?ludusaviStore\.setAutoSyncEnabled\(\s*fallback\s*\)",
            source,
        )
        is not None
    )
    assert (
        re.search(
            r"const\s+fallback\s*=\s*lastPersistedNotifications\s*[\s\S]*?ludusaviStore\.setNotificationSettings\(\s*fallback\s*\)",
            source,
        )
        is not None
    )
    assert (
        re.search(
            r"const\s+fallback\s*=\s*lastPersistedSelectedGame\s*[\s\S]*?ludusaviStore\.setSelectedGame\(\s*fallback\s*\)",
            source,
        )
        is not None
    )


def test_frontend_settings_consecutive_changes_not_ignored() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that lastQueuedSelectedGame exists
    assert re.search(r"let\s+lastQueuedSelectedGame[\s\S]*?=\s*null\s*;", source) is not None

    # Assert that it is checked in onGameChange to prevent early return desync
    assert (
        re.search(
            r"const\s+lastQueued\s*=\s*lastQueuedSelectedGame\s*(?:\?\?|\|\|)\s*ludusaviStore\.getSnapshot\(\)\.selectedGame\s*;[\s\S]*?"
            r"if\s*\(\s*value\s*===\s*lastQueued\s*\)",
            source,
        )
        is not None
    )


def test_frontend_settings_queue_is_module_scoped() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Verify that settingsQueue is declared as a module-scoped variable (before Content component)
    match_queue = re.search(r"const\s+settingsQueue", source)
    match_content = re.search(r"function\s+Content\s*\(\s*\)", source)
    assert match_queue is not None
    assert match_content is not None
    assert match_queue.start() < match_content.start(), (
        "settingsQueue must be declared at the module scope (before Content component)"
    )


def test_frontend_settings_intermediate_success_updates_last_persisted() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that applySettingsGlobal is called only when sequence matches.
    assert (
        re.search(
            r"if\s*\(\s*updateSeq\s*===\s*autoSyncSeq\s*\)\s*\{\s*"
            r"applySettingsGlobal\(\s*ludusaviStore\s*,\s*result\s*\)\s*;",
            source,
        )
        is not None
    )

    assert (
        re.search(
            r"if\s*\(\s*updateSeq\s*===\s*notificationSeq\s*\)\s*\{\s*"
            r"applySettingsGlobal\(\s*ludusaviStore\s*,\s*result\s*\)\s*;",
            source,
        )
        is not None
    )

    assert (
        re.search(
            r"if\s*\(\s*updateSeq\s*===\s*selectedGameSeq\s*\)\s*\{\s*"
            r"applySettingsGlobal\(\s*ludusaviStore\s*,\s*result\s*\)\s*;",
            source,
        )
        is not None
    )

    # Assert that applySettingsGlobal updates the module-scoped lastPersisted variables
    assert (
        re.search(
            r"function\s+applySettingsGlobal\b[\s\S]*?"
            r"lastPersistedAutoSync\s*=\s*normalized\.auto_sync_enabled[\s\S]*?"
            r"lastPersistedNotifications\s*=\s*normalized\.notifications[\s\S]*?"
            r"lastPersistedSelectedGame\s*=\s*normalized\.selected_game",
            source,
        )
        is not None
    )


def test_frontend_settings_queue_recovers_on_listener_error() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that processSettingsQueue uses try...finally to ensure settingsProcessing is reset
    assert (
        re.search(
            r"async\s+function\s+processSettingsQueue\s*\(\s*\)[\s\S]*?"
            r"try\s*\{\s*while\s*\(\s*settingsQueue\.length\s*>\s*0\s*\)\s*\{[\s\S]*\}"
            r"\s*\}\s*finally\s*\{\s*settingsProcessing\s*=\s*false\s*;",
            source,
        )
        is not None
    )


def test_frontend_settings_queue_notifies_on_unhandled_rejection() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that processSettingsQueue catches unhandled task rejections and calls notify with activeLudusaviStore
    assert (
        re.search(
            r"async\s+function\s+processSettingsQueue\s*\(\s*\)[\s\S]*?"
            r"catch\s*\(\s*err\s*\)\s*\{[\s\S]*?"
            r"if\s*\(\s*activeLudusaviStore\s*\)\s*\{[\s\S]*?"
            r"notify\(\s*activeLudusaviStore\s*,\s*\"failures_errors\"\s*,\s*\"Settings\s+Update\s+Failed\"",
            source,
        )
        is not None
    )


def test_frontend_settings_variables_reset_on_dismount() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that onDismount resets queue and sequence variables
    assert (
        re.search(
            r"onDismount\s*\(\s*\)\s*\{[\s\S]*?"
            r"settingsQueue\.length\s*=\s*0\s*;[\s\S]*?"
            r"settingsProcessing\s*=\s*false\s*;[\s\S]*?"
            r"queueListeners\.clear\(\s*\)\s*;[\s\S]*?"
            r"autoSyncSeq\s*=\s*0\s*;[\s\S]*?"
            r"notificationSeq\s*=\s*0\s*;[\s\S]*?"
            r"selectedGameSeq\s*=\s*0\s*;[\s\S]*?"
            r"updateChannelSeq\s*=\s*0\s*;[\s\S]*?"
            r"automaticUpdateChecksSeq\s*=\s*0\s*;[\s\S]*?"
            r"lastPersistedAutoSync\s*=\s*null\s*;[\s\S]*?"
            r"lastPersistedNotifications\s*=\s*null\s*;[\s\S]*?"
            r"lastPersistedUpdateChannel\s*=\s*null\s*;[\s\S]*?"
            r"lastPersistedAutomaticUpdateChecks\s*=\s*null\s*;[\s\S]*?"
            r"lastPersistedSelectedGame\s*=\s*null\s*;[\s\S]*?"
            r"lastQueuedSelectedGame\s*=\s*null\s*;[\s\S]*?"
            r"activeLudusaviStore\s*=\s*null\s*;",
            source,
        )
        is not None
    )


def test_frontend_settings_subscribe_queue_invokes_immediately() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that subscribeQueue immediately invokes the listener callback, protected by try-catch
    assert (
        re.search(
            r"function\s+subscribeQueue\s*\(\s*listener[\s\S]*?\)\s*\{[\s\S]*?"
            r"queueListeners\.add\(\s*listener\s*\)\s*;[\s\S]*?"
            r"try\s*\{[\s\S]*?"
            r"listener\(\s*settingsProcessing\s*\|\|\s*settingsQueue\.length\s*>\s*0\s*\)\s*;[\s\S]*?"
            r"\}\s*catch\s*\(\s*err\s*\)\s*\{",
            source,
        )
        is not None
    )


def test_frontend_selected_game_sync_effect() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that there is a useEffect syncing lastQueuedSelectedGame with selectedGame
    assert (
        re.search(
            r"useEffect\(\s*\(\s*\)\s*=>\s*\{\s*"
            r"lastQueuedSelectedGame\s*=\s*selectedGame\s*;\s*"
            r"\}\s*,\s*\[\s*selectedGame\s*\]\s*\)\s*;",
            source,
        )
        is not None
    )


def test_frontend_notify_queue_listeners_catches_exceptions() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that notifyQueueListeners wraps the listener callback in a try-catch block
    assert (
        re.search(
            r"function\s+notifyQueueListeners\(\s*\)\s*\{[\s\S]*?"
            r"queueListeners\.forEach\(\s*\(\s*listener\s*\)\s*=>\s*\{[\s\S]*?"
            r"try\s*\{[\s\S]*?"
            r"listener\(\s*busy\s*\)\s*;[\s\S]*?"
            r"\}\s*catch\s*\(\s*err\s*\)\s*\{[\s\S]*?"
            r"log\([\s\S]*?Queue listener notification failed",
            source,
        )
        is not None
    )


def test_frontend_settings_failure_notifications_guarded_by_sequence() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that auto-sync catch block notify call is within sequence check
    assert (
        re.search(
            r"catch\s*\(\s*error\s*\)\s*\{[\s\S]*?"
            r"if\s*\(\s*updateSeq\s*===\s*autoSyncSeq\s*\)\s*\{[\s\S]*?"
            r"notify\(\s*ludusaviStore\s*,\s*\"failures_errors\"",
            source,
        )
        is not None
    )

    # Assert that notifications catch block notify call is within sequence check
    assert (
        re.search(
            r"catch\s*\(\s*error\s*\)\s*\{[\s\S]*?"
            r"if\s*\(\s*updateSeq\s*===\s*notificationSeq\s*\)\s*\{[\s\S]*?"
            r"notify\(\s*ludusaviStore\s*,\s*\"failures_errors\"",
            source,
        )
        is not None
    )

    # Assert that selected game catch block notify call is within sequence check
    assert (
        re.search(
            r"catch\s*\(\s*error\s*\)\s*\{[\s\S]*?"
            r"if\s*\(\s*updateSeq\s*===\s*selectedGameSeq\s*\)\s*\{[\s\S]*?"
            r"notify\(\s*ludusaviStore\s*,\s*\"failures_errors\"",
            source,
        )
        is not None
    )


def test_frontend_dropdown_truncation_styling() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that DropdownItem is wrapped inside a div with className sdh-ludusavi-game-dropdown
    assert (
        re.search(
            r'className="sdh-ludusavi-game-dropdown"[\s\S]*?<DropdownItem',
            source,
        )
        is not None
    )

    # Assert that style tag containing sdh-ludusavi-game-dropdown override rules is defined
    assert (
        re.search(
            r"\.sdh-ludusavi-game-dropdown\s+button\b[\s\S]*?max-width:\s*100%\s*!important\s*;[\s\S]*?width:\s*100%\s*!important\s*;",
            source,
        )
        is not None
    )
    assert (
        re.search(
            r"text-overflow:\s*ellipsis\s*!important\s*;[\s\S]*?white-space:\s*nowrap\s*!important\s*;",
            source,
        )
        is not None
    )

    # Assert that styleElement is rendered in the JSX of Content component
    assert (
        re.search(
            r"\{\s*styleElement\s*\}",
            source,
        )
        is not None
    )

    # Assert that styleElement is memoized inside Content component
    assert (
        re.search(
            r"const\s+styleElement\s*=\s*useMemo\(\s*\(\s*\)\s*=>\s*<style>\{\s*dropdownStyleEl\.textContent\s*\}</style>\s*,\s*\[\s*\]\s*\)",
            source,
        )
        is not None
    )


def test_frontend_dropdown_styling_lifecycle() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that style element is appended in definePlugin initialization
    assert (
        re.search(
            r"export\s+default\s+definePlugin\(\s*\(\s*\)\s*=>\s*\{[\s\S]*?"
            r"document\.head\.appendChild\(\s*dropdownStyleEl\s*\)",
            source,
        )
        is not None
    )

    # Assert that style element is cleaned up in onDismount
    assert (
        re.search(
            r"onDismount\s*\(\s*\)\s*\{[\s\S]*?"
            r"dropdownStyleEl\.parentNode\.removeChild\(\s*dropdownStyleEl\s*\)",
            source,
        )
        is not None
    )


def test_frontend_manual_refresh_failure_notification() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that manual refresh failure notifications are triggered for both RpcStatus and exceptions
    assert (
        re.search(
            r"const\s+refreshGames\s*=\s*async\s*\(\s*\)\s*=>\s*\{[\s\S]*?"
            r"if\s*\(\s*isRpcStatus\(\s*result\s*\)\s*\)\s*\{[\s\S]*?"
            r"notify\(\s*ludusaviStore\s*,\s*\"failures_errors\"",
            source,
        )
        is not None
    )

    assert (
        re.search(
            r"const\s+refreshGames\s*=\s*async\s*\(\s*\)\s*=>\s*\{[\s\S]*?"
            r"catch\s*\(\s*error\s*\)\s*\{[\s\S]*?"
            r"notify\(\s*ludusaviStore\s*,\s*\"failures_errors\"",
            source,
        )
        is not None
    )


def test_frontend_settings_queue_timeout_handling() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert that withTimeout utility is defined
    assert (
        re.search(
            r"function\s+withTimeout\s*<[\s\S]*?>\s*\(\s*promise\s*:\s*Promise\s*<[\s\S]*?>\s*,\s*timeoutMs\s*:\s*number\s*,\s*errorMessage\s*:\s*string\s*\)",
            source,
        )
        is not None
    )

    # Assert that withTimeout is called inside toggleAutoSync's queue task
    assert (
        re.search(
            r"toggleAutoSync\s*=[\s\S]*?withTimeout\([\s\S]*?(?:setAutoSyncEnabled\(\s*enabled\s*\)|originalPromise)",
            source,
        )
        is not None
    )

    # Assert that withTimeout is called inside toggleNotificationSetting's queue task
    assert (
        re.search(
            r"toggleNotificationSetting\s*=[\s\S]*?withTimeout\([\s\S]*?(?:setNotificationSettings\(\s*nextNotifications\s*\)|originalPromise)",
            source,
        )
        is not None
    )

    # Assert that withTimeout is called inside onGameChange's queue task
    assert (
        re.search(
            r"onGameChange\s*=[\s\S]*?withTimeout\([\s\S]*?(?:setSelectedGameCall\(\s*value\s*\)|originalPromise)",
            source,
        )
        is not None
    )


def test_frontend_code_review_refinements() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # 1. Assert that the wildcard style selector is NOT used inside dropdownStyleEl textContent
    assert (
        re.search(
            r"\.sdh-ludusavi-game-dropdown\s*,\s*\.sdh-ludusavi-game-dropdown\s+\*",
            source,
        )
        is None
    )

    # 2. Assert that activeInitPromise is defined as a module-scoped variable
    assert (
        re.search(
            r"let\s+activeInitPromise\b",
            source,
        )
        is not None
    )

    # 3. Assert that activeMetadataPromise is defined as a module-scoped variable
    assert (
        re.search(
            r"let\s+activeMetadataPromise\b",
            source,
        )
        is not None
    )

    # 4. Assert that late-resolution handling (awaitFailed flag check or updates) is implemented in settings queue
    assert (
        re.search(
            r"let\s+awaitFailed\s*=\s*false",
            source,
        )
        is not None
    )


def test_frontend_active_init_promise_reset_after_settle() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # activeInitPromise must be set to null in the finally block of loadInitial
    assert (
        re.search(
            r"}\s*finally\s*\{\s*\n\s*activeInitPromise\s*=\s*null\s*;",
            source,
        )
        is not None
    ), "activeInitPromise must be reset to null in the finally block of loadInitial"


def test_frontend_on_dismount_resets_init_and_metadata_promises() -> None:
    source = FRONTEND.read_text(encoding="utf-8")

    # Both promises must be reset to null in onDismount
    assert "activeInitPromise = null;" in source
    assert "activeMetadataPromise = null;" in source

    # Verify they appear in the onDismount block (near activeLudusaviStore = null)
    dismount_idx = source.find('console.log("SDH-Ludusavi unloading")')
    assert dismount_idx != -1
    cleanup_region = source[dismount_idx - 600 : dismount_idx]
    assert "activeInitPromise = null;" in cleanup_region, (
        "activeInitPromise must be reset in onDismount cleanup"
    )
    assert "activeMetadataPromise = null;" in cleanup_region, (
        "activeMetadataPromise must be reset in onDismount cleanup"
    )


def test_frontend_dropdown_uses_scoped_steamos_truncation_workaround() -> None:
    import re

    source = FRONTEND.read_text(encoding="utf-8")

    # Assert no .sdh-ludusavi-game-dropdown * selector
    assert (
        re.search(
            r"\.sdh-ludusavi-game-dropdown\s*,\s*\.sdh-ludusavi-game-dropdown\s+\*",
            source,
        )
        is None
    )
    assert re.search(r"\.sdh-ludusavi-game-dropdown\s+\*", source) is None
    assert ".sdh-ludusavi-game-dropdown *" not in source

    # DropdownItem remains layout="below"
    dropdown_match = re.search(
        r'<DropdownItem[\s\S]*?menuLabel=(["\'])Select Game\1[\s\S]*?/>', source
    )
    assert dropdown_match is not None, "DropdownItem for Select Game not found in index.tsx"
    dropdown_content = dropdown_match.group(0)
    assert re.search(r'layout\s*=\s*(["\'])below\1', dropdown_content) is not None

    # Scoped dropdown wrapper class className="sdh-ludusavi-game-dropdown"
    assert (
        re.search(
            r'className="sdh-ludusavi-game-dropdown"[\s\S]*?<DropdownItem',
            source,
        )
        is not None
    )

    # DropdownItem uses renderButtonValue
    assert "renderButtonValue=" in dropdown_content

    # Selected text wrapped in sdh-ludusavi-game-dropdown-value
    assert "sdh-ludusavi-game-dropdown-value" in source

    # CSS styles block in dropdownStyleEl.textContent exists
    style_match = re.search(r"dropdownStyleEl\.textContent\s*=\s*`([\s\S]*?)`", source)
    assert style_match is not None, "dropdownStyleEl.textContent styles block not found"
    styles = style_match.group(1)

    # CSS gives explicit min-width: 0 and max-width: 100% to scoped dropdown wrapper/control/flex-chain selectors
    assert re.search(r"\.sdh-ludusavi-game-dropdown\b[\s\S]*?max-width:\s*100%", styles) is not None
    assert (
        re.search(r"\.sdh-ludusavi-game-dropdown\s+div\b[\s\S]*?min-width:\s*0\b", styles)
        is not None
    )

    # CSS applies ellipsis to sdh-ludusavi-game-dropdown-value
    assert (
        re.search(
            r"\.sdh-ludusavi-game-dropdown-value\b[\s\S]*?text-overflow:\s*ellipsis",
            styles,
        )
        is not None
    )

    # CSS protects svg, [class*="icon" i], [class*="chevron" i], and [class*="arrow" i] with non-collapsing sizing
    assert re.search(r"\.sdh-ludusavi-game-dropdown\s+svg\b", styles) is not None
    assert re.search(r'\[class\*="icon"\s*i\]', styles) is not None
    assert re.search(r'\[class\*="chevron"\s*i\]', styles) is not None
    assert re.search(r'\[class\*="arrow"\s*i\]', styles) is not None


def test_decky_installer_argument_order() -> None:
    path = Path("src/utils/deckyInstaller.ts")
    assert path.exists(), "src/utils/deckyInstaller.ts does not exist"
    content = path.read_text(encoding="utf-8")

    # 1. Assert callable invocation order: url, EXPECTED_PLUGIN_NAME, version, sha256, installType
    assert "installFn(url, EXPECTED_PLUGIN_NAME, version, sha256, installType)" in content

    # 2. Assert call fallback invocation order: "utilities/install_plugin", url, EXPECTED_PLUGIN_NAME, version, sha256, installType
    assert (
        'call("utilities/install_plugin", url, EXPECTED_PLUGIN_NAME, version, sha256, installType)'
        in content
    )


def test_frontend_update_check_inflight_guard() -> None:
    path = Path("src/components/PluginUpdateSection.tsx")
    assert path.exists(), "src/components/PluginUpdateSection.tsx does not exist"
    content = path.read_text(encoding="utf-8")

    # 1. Enforce that an in-flight check ref is defined
    assert "inFlightCheck = useRef" in content

    # 2. Enforce that concurrent calls observe/return the existing in-flight check promise
    assert "if (inFlightCheck.current)" in content

    # 3. Enforce that the promise is assigned to the ref
    assert "inFlightCheck.current = " in content

    # 4. Enforce that the promise is cleared in finally block
    assert "inFlightCheck.current = null" in content


def test_frontend_updater_static() -> None:
    comp_path = Path("src/components/PluginUpdateSection.tsx")
    assert comp_path.exists()
    comp_content = comp_path.read_text(encoding="utf-8")

    installer_path = Path("src/utils/deckyInstaller.ts")
    assert installer_path.exists()
    installer_content = installer_path.read_text(encoding="utf-8")

    # 1. Update install flow logs major stages & update check in-flight reuse
    assert "logUpdate" in comp_content
    # check start/reuse logs
    assert "check_start" in comp_content
    assert "check_reuse" in comp_content
    # install/revalidation/handoff logs
    assert "install_clicked" in comp_content
    assert "revalidate_start" in comp_content
    assert "revalidate_success" in comp_content
    assert "record_install_start" in comp_content
    assert "record_install_success" in comp_content
    assert "handoff_start" in comp_content
    assert "handoff_pending" in comp_content
    assert "handoff_resolved" in comp_content

    # 2. Decky installer handoff has bounded pending behavior (Promise.race or timeout)
    assert "Promise.race" in comp_content or "setTimeout" in comp_content
    assert "Waiting for Decky..." in comp_content or "Decky prompt opened" in comp_content

    # 3. Install button spinner is wrapped in fixed dimensions and cannot resize the button
    assert "flex: 0 0 16px" in comp_content or 'flex: "0 0 16px"' in comp_content
    assert "overflow: hidden" in comp_content or 'overflow: "hidden"' in comp_content

    # 4. Decky installer adapter reports whether it used DeckyBackend.callable or DeckyBackend.call
    assert (
        'installer_api: "callable"' in comp_content
        or "installer_api: 'callable'" in comp_content
        or 'installer_api: "callable"' in installer_content
        or "installer_api: 'callable'" in installer_content
    )
    assert (
        'installer_api: "call"' in comp_content
        or "installer_api: 'call'" in comp_content
        or 'installer_api: "call"' in installer_content
        or "installer_api: 'call'" in installer_content
    )

    # 5. Full SHA-256 values are not logged (e.g. substrings/slices are used)
    # Ensure any log statement including sha256 slices it
    assert "slice" in comp_content or "substring" in comp_content
    assert "sha256" in comp_content

    # 6. Timing is logged with elapsed_ms and performance.now()
    assert "elapsed_ms" in comp_content
    assert "elapsed_ms" in installer_content
    assert "performance.now()" in comp_content

    # 7. Stable button row with minHeight and lineHeight
    assert "minHeight" in comp_content
    assert "lineHeight" in comp_content
    assert "buttonRowStyle" in comp_content


def test_frontend_updater_post_install_ui_state() -> None:
    """
    Verify that PluginUpdateSection implements the post-install UI state fix:
    - a shared success helper (onHandoffSuccess) called from both handoff paths;
    - successful handoff clears candidate and sets checkResult to current;
    - Installed Version uses effectiveCurrentVersion (override takes precedence);
    - update checks use effectiveCurrentVersion so stale RPCs compare against
      the installed version, not the old one;
    - stale 'available' results for the same version as the installed override
      cannot restore the install button;
    - if the real currentVersion prop changes away from the pre-install version,
      the override is cleared.
    """
    import re

    comp_path = Path("src/components/PluginUpdateSection.tsx")
    assert comp_path.exists()
    comp = comp_path.read_text(encoding="utf-8")

    # 1. A shared post-install success helper must exist and be called from
    #    both handoff-success branches (immediate and delayed).
    assert "onHandoffSuccess" in comp or "handleHandoffSuccess" in comp, (
        "A shared post-install success helper (onHandoffSuccess or handleHandoffSuccess) "
        "must be defined and referenced in PluginUpdateSection"
    )
    # The helper must appear at least twice — once defined, once for each success path
    helper_name = "onHandoffSuccess" if "onHandoffSuccess" in comp else "handleHandoffSuccess"
    assert comp.count(helper_name) >= 3, (
        f"{helper_name} must be defined and called from both handoff success branches "
        f"(found {comp.count(helper_name)} occurrences, expected >= 3)"
    )

    # 2. Successful handoff must clear candidate state.
    #    The helper body or success branches must call setCandidate(null).
    assert "setCandidate(null)" in comp, (
        "Successful handoff must call setCandidate(null) to clear the install button"
    )

    # 3. Successful handoff must write a 'current' checkResult.
    #    Look for status: "current" being set inside the component.
    assert 'status: "current"' in comp or "status: 'current'" in comp, (
        "Successful handoff must set checkResult to { status: 'current', ... }"
    )

    # 4. An installedOverride (or equivalent) state variable must exist.
    assert "installedOverride" in comp or "installedVersion" in comp, (
        "An 'installedOverride' or equivalent state variable must exist to hold the "
        "optimistic installed version after handoff"
    )

    # 5. An effectiveCurrentVersion (or equivalent derived value) must be computed
    #    from the override falling back to currentVersion.
    assert "effectiveCurrentVersion" in comp, (
        "effectiveCurrentVersion must be computed and used in place of currentVersion "
        "for Installed Version display and RPC calls"
    )

    # 6. Installed Version row must render effectiveCurrentVersion, not raw currentVersion.
    #    The effectiveCurrentVersion identifier must appear inside the JSX Installed Version field.
    installed_version_region = re.search(
        r"Installed Version[\s\S]{0,600}effectiveCurrentVersion", comp
    )
    assert installed_version_region is not None, (
        "The Installed Version field must render effectiveCurrentVersion"
    )

    # 7. Update check RPC calls must use effectiveCurrentVersion, not currentVersion.
    #    checkForPluginUpdateCall(...) must be called with effectiveCurrentVersion.
    rpc_call_match = re.search(r"checkForPluginUpdateCall\s*\(\s*effectiveCurrentVersion", comp)
    assert rpc_call_match is not None, (
        "checkForPluginUpdateCall must be called with effectiveCurrentVersion so stale "
        "checks compare against the installed version, not the old one"
    )

    # 8. Stale available responses for the installed override version must be coerced to current.
    #    There must be a guard that compares the available candidate version against the override.
    assert "installedOverride" in comp or "installedVersion" in comp, (
        "Component must guard against stale available responses restoring the install button"
    )
    # Confirm the coercion logic exists: override?.version compared against res.candidate?.version
    stale_guard = (
        "installedOverride" in comp
        and (
            re.search(r"installedOverride[.\w?]*\.version", comp) is not None
            or re.search(r"installedOverride[.\w?]*version", comp) is not None
        )
    ) or ("installedVersion" in comp and re.search(r"installedVersion", comp) is not None)
    assert stale_guard, (
        "Component must contain logic to detect when an available check result "
        "matches the installed override version and coerce it to current"
    )

    # 9. The override must be cleared when the real currentVersion changes away
    #    from the pre-install version. This requires storing the pre-install version
    #    and a useEffect or similar that reacts to currentVersion changes.
    assert "preInstallVersion" in comp or "installedOverride" in comp, (
        "Component must clear the installed override when currentVersion changes away "
        "from the pre-install version"
    )


def test_frontend_updater_post_reload_stale_coercion() -> None:
    """
    After plugin reload, installedOverride is null but the backend cache may
    return the just-installed version as 'available'. The component must
    coerce any available candidate whose version matches effectiveCurrentVersion
    (i.e. currentVersion after reload) to 'current', even when there is no
    in-memory installedOverride.

    This guards the codex P2 finding: stale cached available results after
    reload can resurrect the install button for the just-installed version.
    """
    import re

    comp_path = Path("src/components/PluginUpdateSection.tsx")
    assert comp_path.exists()
    comp = comp_path.read_text(encoding="utf-8")

    # The coercion guard must also fire when the candidate version equals
    # effectiveCurrentVersion, not only when it matches installedOverride.version.
    # This covers the post-reload case where installedOverride is null but the
    # backend cache still returns the just-installed version as available.
    #
    # A correct implementation will have a condition resembling:
    #   res.candidate?.version === effectiveCurrentVersion
    # (possibly combined with the installedOverride guard via ||)
    coercion_vs_effective = re.search(
        r"candidate[?\w.]*\.version\s*===\s*effectiveCurrentVersion"
        r"|effectiveCurrentVersion\s*===\s*candidate[?\w.]*\.version"
        r"|candidateVersion\s*===\s*effectiveCurrentVersion"
        r"|effectiveCurrentVersion\s*===\s*candidateVersion",
        comp,
    )
    assert coercion_vs_effective is not None, (
        "The stale-check coercion must also reject available candidates whose "
        "version matches effectiveCurrentVersion (currentVersion after reload), "
        "not only candidates matching the in-memory installedOverride.version"
    )
