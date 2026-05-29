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
    assert "await setAutoSyncEnabled(enabled)" in source
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
    import re

    source = FRONTEND.read_text()

    pattern = r"const\s+gamesDropdownOptions\s*=\s*useMemo\((?:[\s\S]*?)\);\s*"
    match = re.search(pattern, source)
    assert match is not None, "gamesDropdownOptions useMemo block not found"

    block = match.group(0)
    assert "label: game.name" in block
    assert "statusLabels" not in block


def test_frontend_dropdown_has_below_layout() -> None:
    import re

    source = FRONTEND.read_text()

    match = re.search(r'<PanelSection\s+title=(["\'])GAME\1[\s\S]*?</PanelSection>', source)
    assert match is not None, "GAME PanelSection not found in index.tsx"
    game_section = match.group(0)

    assert "<DropdownItem" in game_section, "DropdownItem not found in GAME section"
    assert re.search(r"menuLabel\s*=\s*(['\"])Select Game\1", game_section) is not None, (
        "DropdownItem with menuLabel='Select Game' not found in GAME section"
    )
    assert re.search(r"layout\s*=\s*(['\"])below\1", game_section) is not None, (
        "Games dropdown does not have layout='below' in GAME section"
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

    assert "const result = await setSelectedGameCall(value);" in source
    assert "applySettings(result);" in source
    assert "ludusaviStore.setSelectedGame(result.selected_game);" in source


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
