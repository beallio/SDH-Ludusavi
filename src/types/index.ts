export type NotificationSettings = {
  enabled: boolean;
  auto_sync_progress: boolean;
  auto_sync_results: boolean;
  manual_operations: boolean;
  refresh_status: boolean;
  failures_errors: boolean;
};

export type NotificationCategory = keyof Omit<NotificationSettings, "enabled">;

export type Settings = {
  auto_sync_enabled: boolean;
  selected_game: string;
  notifications: NotificationSettings;
};

export type GameOperationHistoryEntry = {
  operation: "backup" | "restore" | "start" | "exit";
  trigger: "manual_backup" | "manual_restore" | "auto_start" | "auto_exit";
  status: "backed_up" | "restored" | "skipped" | "failed";
  reason: string | null;
  message: string | null;
  timestamp: string;
};

export type GameOperationHistory = {
  last_backup: GameOperationHistoryEntry | null;
  last_restore: GameOperationHistoryEntry | null;
  last_skip: GameOperationHistoryEntry | null;
  last_failure: GameOperationHistoryEntry | null;
  last_operation: GameOperationHistoryEntry | null;
};

export type GameStatus = {
  name: string;
  steam_id?: string | number | null;
  configured: boolean;
  has_backup: boolean;
  needs_first_backup: boolean;
  error: string | null;
  status: "configured" | "has_backup" | "needs_first_backup" | "error";
};

export type RefreshResult = {
  games: GameStatus[];
  aliases: Record<string, string>;
  history: Record<string, GameOperationHistory>;
  dependency_error: string | null;
};

export type OperationStatus = {
  is_running: boolean;
  name: string | null;
  game_name: string | null;
  last_result: string | null;
  last_error: string | null;
};

export type OperationResult = {
  status: "backed_up" | "restored" | "skipped" | "failed";
  game?: string;
  reason?: string;
  message?: string;
};

export type ConflictResolution = "keep_local" | "restore_backup";

export type LifecycleCheckResult = {
  status: "needed" | "conflict" | "skipped" | "failed";
  operation?: "backup" | "restore";
  game?: string;
  reason?: string;
  message?: string;
  localModifiedAt?: string | null;
  backupModifiedAt?: string | null;
  backupPath?: string | null;
  localLabel?: string;
  backupLabel?: string;
};

export type ProcessSignalResult = {
  status: "paused" | "resumed" | "skipped" | "failed";
  pid?: number;
  reason?: string;
  message?: string;
};

export type AppLifetimeNotification = {
  unAppID: number;
  nInstanceID: number;
  bRunning: boolean;
};

export type RunningSession = {
  appID: string;
  name: string;
  source?: "focused" | "route" | "cached" | "running";
};

export type RpcStatus = {
  status: "skipped" | "failed";
  reason?: string;
  message?: string;
};

export type RpcResult<T> = T | RpcStatus;

export type AutoSyncStatusKind = "checking" | "backing_up" | "restoring" | "conflict" | "has_backup" | "unknown" | "error";

export type AutoSyncStatusSource = "lifecycle_start" | "lifecycle_exit" | "rpc_result" | "timeout" | "hide";

export type AutoSyncStatusState = {
  status: AutoSyncStatusKind;
  visible: boolean;
  source: AutoSyncStatusSource;
  gameName?: string;
  appID?: string;
  tracked?: boolean;
  resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];
};

export type AutoSyncStatusBrowserView = {
  LoadURL?: (url: string) => void;
  SetBounds?: (x: number, y: number, width: number, height: number) => void;
  SetFocus?: (value: boolean) => void;
  SetName?: (name: string) => void;
  SetVisible?: (value: boolean) => void;
  SetTopmost?: (value: boolean) => void;
  SetWindowStackingOrder?: (value: number) => void;
  Destroy?: () => void;
};

export type AutoSyncStatusBrowserViewOwner = AutoSyncStatusBrowserView & {
  browserView?: AutoSyncStatusBrowserView;
  BrowserView?: AutoSyncStatusBrowserView;
  m_browserView?: AutoSyncStatusBrowserViewOwner;
};

export type Versions = {
  sdh_ludusavi?: string;
  decky?: string;
  ludusavi?: string;
  pyludusavi?: string;
  rclone?: string;
  status?: string;
  message?: string;
};

export type LogEntry = {
  level: string;
  message: string;
  timestamp: string;
  operation: string | null;
  game_name: string | null;
};

export type LogModalProps = {
  logs: LogEntry[];
  closeModal?: () => void;
};

export type LudusaviLogModalProps = {
  logs: string;
  closeModal?: () => void;
};
