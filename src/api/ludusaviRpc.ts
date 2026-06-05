import { callable } from "@decky/api";

import type { LudusaviLaunchCommand } from "../ludusaviLauncher";
import type {
  ConflictResolution,
  GameOperationHistory,
  LifecycleCheckResult,
  LogEntry,
  NotificationSettings,
  OperationResult,
  OperationStatus,
  ProcessSignalResult,
  RefreshResult,
  RpcResult,
  Settings,
  Versions,
  SyncthingWatchStartResult,
  SyncthingPollResult
} from "../types";

export const getSettings = callable<[], RpcResult<Settings>>("get_settings");
export const getGameHistoryCall = callable<[], RpcResult<Record<string, GameOperationHistory>>>("get_game_history");
export const setAutoSyncEnabled = callable<[enabled: boolean], RpcResult<Settings>>(
  "set_auto_sync_enabled"
);
export const setNotificationSettings = callable<
  [settings: NotificationSettings],
  RpcResult<Settings>
>("set_notification_settings");
export const setSelectedGameCall = callable<[gameName: string], RpcResult<Settings>>(
  "set_selected_game"
);
export const refreshGamesCall = callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>("refresh_games");
export const isGameCacheCurrentCall = callable<[installed_app_ids?: string], boolean>(
  "is_game_cache_current"
);
export const forceBackupCall = callable<[gameName: string], RpcResult<OperationResult>>(
  "force_backup"
);
export const forceRestoreCall = callable<[gameName: string], RpcResult<OperationResult>>(
  "force_restore"
);
export const getVersions = callable<[], RpcResult<Versions>>("get_versions");
export const getOperationStatus = callable<[], OperationStatus>("get_operation_status");
export const getRecentLogs = callable<[], LogEntry[]>("get_recent_logs");
export const getLudusaviLogs = callable<[], RpcResult<string>>("get_ludusavi_logs");
export const setUpdateChannelCall = callable<[channel: string], RpcResult<Settings>>(
  "set_update_channel"
);
export const setAutomaticUpdateChecksCall = callable<[enabled: boolean], RpcResult<Settings>>(
  "set_automatic_update_checks"
);
export const getLudusaviCommandCall = callable<
  [],
  RpcResult<LudusaviLaunchCommand | null>
>("get_ludusavi_command");
export const pauseGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("pause_game_process");
export const resumeGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("resume_game_process");
export const checkGameStartCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_start");
export const restoreGameOnStartCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("restore_game_on_start");
export const resolveGameStartConflictCall = callable<[gameName: string, app_id: string | undefined, resolution: ConflictResolution], RpcResult<OperationResult>>("resolve_game_start_conflict");
export const checkGameExitCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_exit");
export const backupGameOnExitCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("backup_game_on_exit");
export const startSyncthingActivityWatchCall = callable<
  [phase: string, gameName?: string, appID?: string],
  RpcResult<SyncthingWatchStartResult>
>("start_syncthing_activity_watch");
export const getSyncthingActivityCall = callable<[watchID: string], RpcResult<SyncthingPollResult>>(
  "get_syncthing_activity"
);
export const stopSyncthingActivityWatchCall = callable<[watchID: string], RpcResult<SyncthingPollResult>>(
  "stop_syncthing_activity_watch"
);
