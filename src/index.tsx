import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  showModal,
  staticClasses,
  ToggleField,
  Spinner,
  Router
} from "@decky/ui";
import {
  callable,
  definePlugin,
  toaster
} from "@decky/api";
import React, { useEffect, useMemo, useState } from "react";
import { FaDatabase, FaSave, FaDownload, FaExclamationTriangle } from "react-icons/fa";
import { IoMdRefresh } from "react-icons/io";
import { LuDatabaseBackup } from "react-icons/lu";

import { launchLudusavi, LudusaviLaunchCommand } from "./ludusaviLauncher";

type Settings = {
  auto_sync_enabled: boolean;
  selected_game: string;
};

type GameStatus = {
  name: string;
  configured: boolean;
  has_backup: boolean;
  needs_first_backup: boolean;
  error: string | null;
  status: "configured" | "has_backup" | "needs_first_backup" | "error";
};

type RefreshResult = {
  games: GameStatus[];
  aliases: Record<string, string>;
  dependency_error: string | null;
};

type OperationStatus = {
  is_running: boolean;
  name: string | null;
  game_name: string | null;
  last_result: string | null;
  last_error: string | null;
};

type OperationResult = {
  status: "backed_up" | "restored" | "skipped" | "failed";
  game?: string;
  reason?: string;
  message?: string;
};

type AppLifetimeNotification = {
  unAppID: number;
  nInstanceID: number;
  bRunning: boolean;
};

type RunningSession = {
  appID: string;
  name: string;
};

type RpcStatus = {
  status: "skipped" | "failed";
  reason?: string;
  message?: string;
};

type RpcResult<T> = T | RpcStatus;

type Versions = {
  sdh_ludusavi?: string;
  ludusavi?: string;
  pyludusavi?: string;
  rclone?: string;
  status?: string;
  message?: string;
};

type LogEntry = {
  level: string;
  message: string;
  timestamp: string;
  operation: string | null;
  game_name: string | null;
};

type LogModalProps = {
  logs: LogEntry[];
  closeModal?: () => void;
};

type LudusaviLogModalProps = {
  logs: string;
  closeModal?: () => void;
};

const getSettings = callable<[], Settings>("get_settings");
const setAutoSyncEnabled = callable<[enabled: boolean], Settings>("set_auto_sync_enabled");
const setSelectedGameCall = callable<[gameName: string], Settings>("set_selected_game");
const refreshGamesCall = callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>("refresh_games");
const forceBackupCall = callable<[gameName: string], RpcResult<OperationResult>>("force_backup");
const forceRestoreCall = callable<[gameName: string], RpcResult<OperationResult>>("force_restore");
const getVersions = callable<[], RpcResult<Versions>>("get_versions");
const getOperationStatus = callable<[], OperationStatus>("get_operation_status");
const getRecentLogs = callable<[], LogEntry[]>("get_recent_logs");
const getLudusaviLogs = callable<[], string>("get_ludusavi_logs");
const logCall = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");
const getLudusaviCommandCall = callable<[], LudusaviLaunchCommand | null>("get_ludusavi_command");
const handleGameStartCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("handle_game_start");
const handleGameExitCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("handle_game_exit");

const getInstalledAppIdsString = async (): Promise<string | undefined> => {
  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    if (!steamClient?.Apps?.GetInstalledApps) {
      return undefined;
    }
    const appsResult = steamClient.Apps.GetInstalledApps();
    const apps = appsResult instanceof Promise ? await appsResult : appsResult;
    
    if (!Array.isArray(apps)) return undefined;
    
    const appIds = apps
      .map((app: any) => parseInt(app?.appid ?? app?.nAppID ?? app?.unAppID ?? app?.id, 10))
      .filter((id: number) => !isNaN(id));
      
    appIds.sort((a, b) => a - b);
    return appIds.join(",");
  } catch (err) {
    return undefined;
  }
};

const log = (level: "info" | "debug" | "warning" | "error", message: string, operation?: string, gameName?: string) => {
  const prefix = `SDH-ludusavi${operation ? `:${operation}` : ""}${gameName ? ` [${gameName}]` : ""}`;
  const fullMsg = `${prefix}: ${message}`;
  
  console.log(fullMsg);

  void logCall(level, message, operation, gameName);
};

const statusLabels: Record<GameStatus["status"], string> = {
  configured: "Configured",
  has_backup: "Backup ready",
  needs_first_backup: "Needs first backup",
  error: "Error"
};

function SpinnerButton({ children, loading, ...props }: any) {
  return (
    <ButtonItem {...props} disabled={props.disabled || loading}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "10px" }}>
        {loading && <Spinner style={{ width: "18px", height: "18px", color: "#1a9fff" }} />}
        {children}
      </div>
    </ButtonItem>
  );
}

function LogModal({ logs, closeModal }: LogModalProps) {
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Plugin Logs"
      onOK={closeModal}
      onCancel={closeModal}
    >
      <div
        style={{
          maxHeight: "60vh",
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          backgroundColor: "rgba(0, 0, 0, 0.3)",
          padding: "10px",
          borderRadius: "4px",
          userSelect: "text",
        }}
      >
        {logs.length === 0 ? "No recent logs" : logs.map(formatLogEntry).join("\n")}
      </div>
    </ConfirmModal>
  );
}

function LudusaviLogModal({ logs, closeModal }: LudusaviLogModalProps) {
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Ludusavi Logs"
      onOK={closeModal}
      onCancel={closeModal}
    >
      <div
        style={{
          maxHeight: "60vh",
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          backgroundColor: "rgba(0, 0, 0, 0.3)",
          padding: "10px",
          borderRadius: "4px",
          userSelect: "text",
        }}
      >
        {logs || "No Ludusavi logs available"}
      </div>
    </ConfirmModal>
  );
}

let trackedAppIDs = new Set<string>();
let trackedNames = new Set<string>();
let cachedLudusaviCommand: LudusaviLaunchCommand | null = null;
let autoSyncNotificationsEnabled = false;

/** Normalize a game name for fuzzy matching, mirroring backend _normalize. */
function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9.-]+/g, " ").trim();
}

function showToast(title: string, body: string, logo?: any) {
  try {
    log("debug", `Showing toast: ${title} - ${body}`);
    const toastObj = { 
      title, 
      body, 
      logo: logo ? React.cloneElement(logo, { size: 40 }) : undefined,
      duration: 2000 
    };
    
    // Attempt standard toaster
    toaster.toast(toastObj);
    
  } catch (err) {
    log("error", `Failed to show toast: ${err}`);
  }
}

function isRpcStatus<T>(result: RpcResult<T>): result is RpcStatus {
  return (
    typeof result === "object" &&
    result !== null &&
    "status" in result &&
    ((result as RpcStatus).status === "skipped" || (result as RpcStatus).status === "failed")
  );
}

function logRpcStatus(result: RpcStatus, operation: string) {
  const level = result.status === "failed" ? "error" : "warning";
  const reason = result.reason ? ` (${result.reason})` : "";
  const message = result.message ?? `${operation} ${result.status}${reason}`;
  log(level, message, operation);
}

function Content() {
  const [settings, setSettings] = useState<Settings>({ auto_sync_enabled: false, selected_game: "" });
  const [games, setGames] = useState<GameStatus[]>([]);
  const [selectedGame, setSelectedGame] = useState("");
  const [versions, setVersions] = useState<Versions>({});
  const [operation, setOperation] = useState<OperationStatus>({
    is_running: false,
    name: null,
    game_name: null,
    last_result: null,
    last_error: null
  });
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [ludusaviCommand, setLudusaviCommand] = useState<LudusaviLaunchCommand | null>(cachedLudusaviCommand);

  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const isBusy = operation.is_running || busyLabel !== null;

  useEffect(() => {
    log("info", "Plugin mounted, starting initial load");
    void loadInitial();
  }, []);

  const loadInitial = async () => {
    setBusyLabel("Loading");
    try {
      log("debug", "Fetching initial settings and versions");
      const [loadedSettings, loadedVersions, loadedCommand] = await Promise.all([
        getSettings(),
        getVersions(),
        getLudusaviCommandCall()
      ]);

      log("debug", `Loaded settings: ${JSON.stringify(loadedSettings)}`);
      setSettings(loadedSettings);
      autoSyncNotificationsEnabled = loadedSettings.auto_sync_enabled;
      if (loadedSettings.selected_game) {
        setSelectedGame(loadedSettings.selected_game);
      }

      log("debug", `Loaded versions: ${JSON.stringify(loadedVersions)}`);
      if (isRpcStatus(loadedVersions)) {
        logRpcStatus(loadedVersions, "versions");
      } else {
        setVersions(loadedVersions);
      }

      log("debug", `Loaded command: ${JSON.stringify(loadedCommand)}`);
      cachedLudusaviCommand = loadedCommand;
      setLudusaviCommand(loadedCommand);

      log("debug", "Initializing game list (cached)");
      const installedAppIds = await getInstalledAppIdsString();
      const refreshed = await refreshGamesCall(false, installedAppIds);
      applyRefreshResult(refreshed, loadedSettings.selected_game);

      const loadedOperation = await getOperationStatus();
      setOperation(loadedOperation);
      const loadedLogs = await getRecentLogs();
      setLogs(loadedLogs);
    } catch (error) {
      log("error", `Initial load failed: ${error}`);
      setLogs(await getRecentLogs().catch(() => []));
    } finally {
      setBusyLabel(null);
    }
  };

  const applyRefreshResult = (result: RpcResult<RefreshResult>, preferredGame?: string): boolean => {
    if (isRpcStatus(result)) {
      logRpcStatus(result, "refresh");
      return false;
    }

    if (result.dependency_error) {
      log("error", `Ludusavi refresh failed: ${result.dependency_error}`, "refresh");
      toaster.toast({
        title: "SDH-ludusavi refresh failed",
        body: result.dependency_error,
        logo: <FaExclamationTriangle size={40} />,
        duration: 4000
      });
      return false;
    }

    log("debug", `Applying refresh result (${result.games.length} games, ${Object.keys(result.aliases || {}).length} aliases)`);
    setGames(result.games);
    
    // Update global tracking sets for toast filtering
    trackedAppIDs = new Set(result.games.map(g => (g as any).steam_id).filter(id => !!id) as string[]);
    
    const names = new Set<string>();
    result.games.forEach(g => names.add(normalize(g.name)));
    Object.entries(result.aliases || {}).forEach(([alias, target]) => {
      names.add(normalize(alias));
      names.add(normalize(target));
    });
    trackedNames = names;
    
    log("info", `Tracked ${trackedNames.size} game names/aliases`);

    setSelectedGame((current) => {
      const target = preferredGame || current;
      if (target && result.games.some((game) => game.name === target)) {
        return target;
      }
      const firstGame = result.games[0]?.name ?? "";
      log("debug", `Defaulting selected game to ${firstGame}`);
      return firstGame;
    });

    return true;
  };

  const refreshGames = async () => {
    log("info", "Manual refresh triggered");
    setBusyLabel("Refreshing games");
    try {
      const installedAppIds = await getInstalledAppIdsString();
      const result = await refreshGamesCall(true, installedAppIds);
      if (applyRefreshResult(result)) {
        setOperation(await getOperationStatus());
        setLogs(await getRecentLogs());
        toaster.toast({
          title: "SDH-ludusavi",
          body: "Ludusavi game status refreshed",
          logo: <IoMdRefresh size={40} />,
          duration: 2000
        });
      }
    } catch (error) {
      log("error", `Manual refresh failed: ${error}`);
    } finally {
      setBusyLabel(null);
    }
  };

  const showLudusaviLogs = async () => {
    log("info", "Showing Ludusavi logs");
    try {
      const ludusaviLogs = await getLudusaviLogs();
      showModal(<LudusaviLogModal logs={ludusaviLogs} />);
    } catch (error) {
      log("error", `Failed to fetch Ludusavi logs: ${error}`);
      toaster.toast({
        title: "SDH-ludusavi",
        body: "Failed to fetch Ludusavi logs",
        logo: <FaExclamationTriangle size={40} />,
        duration: 2000
      });
    }
  };

  const toggleAutoSync = async (enabled: boolean) => {
    log("info", `Toggling auto-sync to ${enabled}`);
    setBusyLabel("Updating settings");
    try {
      const updated = await setAutoSyncEnabled(enabled);
      setSettings(updated);
      autoSyncNotificationsEnabled = updated.auto_sync_enabled;
    } catch (error) {
      log("error", `Failed to toggle auto-sync: ${error}`);
      toaster.toast({
        title: "SDH-ludusavi settings failed",
        body: error instanceof Error ? error.message : String(error),
        logo: <FaExclamationTriangle size={40} />,
        duration: 2000
      });
    } finally {
      setBusyLabel(null);
    }
  };

  const onGameChange = async (data: any) => {
    const value = typeof data === 'object' ? data?.data : data;
    log("info", `Selected game changed to ${value}`);
    setSelectedGame(value);
    try {
      const updated = await setSelectedGameCall(value);
      setSettings(updated);
      autoSyncNotificationsEnabled = updated.auto_sync_enabled;
    } catch (error) {
      log("error", `Failed to persist selected game: ${error}`);
    }
  };

  const runForceOperation = async (
    label: "Backup" | "Restore",
    operationCall: (gameName: string) => Promise<RpcResult<OperationResult>>
  ) => {
    if (!selectedGame) {
      return;
    }
    log("info", `Triggering force ${label} for ${selectedGame}`, label, selectedGame);
    setBusyLabel(`${label} running`);
    const icon = label === "Backup" ? <FaSave /> : <FaDownload />;
    toaster.toast({ 
      title: `SDH-ludusavi ${label}`, 
      body: `${label} started for ${selectedGame}`,
      logo: React.cloneElement(icon as any, { size: 40 }),
      duration: 2000
    });
    try {
      const result = await operationCall(selectedGame);
      log("info", `Force ${label} completed: ${JSON.stringify(result)}`, label, selectedGame);
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      toaster.toast({
        title: `SDH-ludusavi ${label}`,
        body: summarizeOperationResult(result, label),
        logo: React.cloneElement(resultIcon as any, { size: 40 }),
        duration: 2000
      });
      const refreshed = await refreshGamesCall(false);
      applyRefreshResult(refreshed);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
    } catch (error) {
      log("error", `Force ${label} failed: ${error}`, label, selectedGame);
      toaster.toast({
        title: `SDH-ludusavi ${label} failed`,
        body: error instanceof Error ? error.message : String(error),
        logo: <FaExclamationTriangle size={40} />,
        duration: 2000
      });
    } finally {
      setBusyLabel(null);
    }
  };

  return (
    <>
      <PanelSection title="Sync">
        <ToggleField
          label="Automatic Sync"
          checked={settings.auto_sync_enabled}
          disabled={isBusy}
          onChange={(enabled: boolean) => void toggleAutoSync(enabled)}
        />

        <PanelSectionRow>
          <DropdownItem
            menuLabel="Select Game"
            disabled={isBusy}
            rgOptions={games.map((game) => ({
              label: game.name,
              data: game.name
            }))}
            selectedOption={selectedGame}
            onChange={(data: any) => void onGameChange(data)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <div style={{ color: "#cbd5e1", fontSize: "14px", margin: "12px 0", padding: "0 4px" }}>
            <span style={{ color: "#64748b", fontWeight: "bold", marginRight: "8px" }}>Status:</span>
            {isBusy && busyLabel === "Loading" ? (
              <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Loading game list...</span>
            ) : isBusy && busyLabel === "Refreshing games" ? (
              <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Game refresh in progress...</span>
            ) : isBusy && busyLabel === "Backup running" ? (
              <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Backup in progress...</span>
            ) : isBusy && busyLabel === "Restore running" ? (
              <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Restore in progress...</span>
            ) : (
              selectedStatus ? statusLabels[selectedStatus.status] : "No Ludusavi games found"
            )}
          </div>
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton 
            layout="below" 
            disabled={isBusy} 
            loading={busyLabel === "Refreshing games"}
            onClick={() => void refreshGames()}
          >
            Refresh Games
          </SpinnerButton>
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            disabled={isBusy || !selectedStatus}
            loading={busyLabel === "Backup running"}
            onClick={() => void runForceOperation("Backup", forceBackupCall)}
          >
            Force Backup
          </SpinnerButton>
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            disabled={isBusy || selectedStatus?.status !== "has_backup"}
            loading={busyLabel === "Restore running"}
            onClick={() => void runForceOperation("Restore", forceRestoreCall)}
          >
            Force Restore
          </SpinnerButton>
        </PanelSectionRow>
      </PanelSection>

      <LudusaviPanel ludusaviCommand={ludusaviCommand} isLoading={busyLabel === "Loading"} />

      <PanelSection title="Logs">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<LogModal logs={logs} />)}>
            View Logs
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void showLudusaviLogs()}>
            View Ludusavi Logs
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Versions">
        <PanelSectionRow>
          <div style={{ color: "#cbd5e1", fontSize: "14px", display: "flex", flexDirection: "column", gap: "4px", padding: "12px", backgroundColor: "rgba(30, 41, 59, 0.3)", borderRadius: "4px" }}>
            <div>SDH-ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>
            <div>Ludusavi: {versions.ludusavi ?? versions.message ?? "Unknown"}</div>
            <div>pyludusavi: {versions.pyludusavi ?? "Unknown"}</div>
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

function summarizeOperationResult(result: OperationResult, label: string) {
  if (result.status === "skipped") {
    switch (result.reason) {
      case "auto_sync_disabled": return `Auto-sync skipped: feature disabled`;
      case "operation_running": return `Auto-sync skipped: another operation is running`;
      case "unmatched_game": return `Auto-sync skipped: could not match game name`;
      case "not_processed": return `Auto-sync skipped: game is deselected in Ludusavi`;
      case "no_backup": return `Auto-sync skipped: no backup found for ${result.game}`;

      case "local_current": return `Auto-sync skipped: local save is already current`;
      case "ambiguous_recency": return `Auto-sync skipped: recency is ambiguous`;
      default: return `${label} skipped: ${result.reason ?? "unknown reason"}`;
    }
  }
  if (result.status === "failed") {
    return `${label} failed: ${result.message ?? "unknown error"}`;
  }
  const action = result.status === "backed_up" ? "Backup" : "Restore";
  return `${action} completed for ${result.game}`;
}

function formatLogEntry(entry: LogEntry) {
  const game = entry.game_name ? ` ${entry.game_name}` : "";
  return `[${entry.timestamp}] [${entry.level}]${game} ${entry.message}`;
}

function LudusaviPanel({ 
  ludusaviCommand,
  isLoading
}: { 
  ludusaviCommand: LudusaviLaunchCommand | null,
  isLoading: boolean
}) {
  const [status, setStatus] = useState<string | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);

  async function onLaunch() {
    try {
      setIsLaunching(true);
      setStatus("Launching Ludusavi...");

      if (!ludusaviCommand) {
        throw new Error("Ludusavi not found on system.");
      }

      await launchLudusavi(ludusaviCommand, { logger: log });

      setStatus("Ludusavi launch requested.");
      // Best-effort clear status after 3s
      setTimeout(() => setStatus(null), 3000);
    } catch (err) {
      console.error(err);
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLaunching(false);
    }
  }

  return (
    <PanelSection title="Ludusavi">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={onLaunch}
          disabled={isLaunching || !ludusaviCommand}
        >
          Launch
        </ButtonItem>
      </PanelSectionRow>

      {status && (
        <PanelSectionRow>
          <div style={{ color: "#60a5fa", fontSize: "14px", fontWeight: "bold", padding: "0 4px" }}>
            {status}
          </div>
        </PanelSectionRow>
      )}
      
      {!ludusaviCommand && !isLaunching && !isLoading && (
        <PanelSectionRow>
          <div style={{ color: "#ef4444", fontSize: "12px", padding: "0 4px" }}>
            Ludusavi not found. Please install it via Flatpak or add to PATH.
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

export default definePlugin(() => {
  console.log("SDH-ludusavi plugin initializing");

  const activeSessions = new Map<number, RunningSession>();
  let fallbackIntervalID: number | null = null;
  let fallbackPreviousAppID: string | null = null;
  let fallbackPreviousAppName: string | null = null;
  let lifecycleRegistration: unknown = null;

  const isTracked = (name: string, appID: string) => {
    if (trackedAppIDs.has(appID)) {
      log("debug", `Match found via AppID: ${appID}`);
      return true;
    }
    
    const normalizedInput = normalize(name);
    if (trackedNames.has(normalizedInput)) {
      log("debug", `Match found via exact name: ${normalizedInput}`);
      return true;
    }

    // Substring matching (mirroring backend fuzzy logic)
    for (const trackedName of Array.from(trackedNames)) {
      if (
        (normalizedInput.length > 4 && trackedName.includes(normalizedInput)) ||
        (trackedName.length > 4 && normalizedInput.includes(trackedName))
      ) {
        log("debug", `Match found via substring: ${normalizedInput} <-> ${trackedName}`);
        return true;
      }
    }

    log("debug", `No match for ${name} (${appID}) [normalized: ${normalizedInput}]`);
    return false;
  };

  const handleAppStart = async (name: string, appID: string) => {
    const tracked = isTracked(name, appID);
    log("info", `App started: ${name} (${appID}) tracked=${tracked}`);
    
    if (tracked && autoSyncNotificationsEnabled) {
      showToast("SDH-ludusavi Auto-sync", `Checking saves for ${name}...`, <FaDatabase />);
    }
    
    const result = await handleGameStartCall(name, appID);
    // Show result toast for all outcomes (restored, failed, or skipped)
    // unless auto-sync is completely disabled, another operation is running,
    // or the game simply isn't managed by Ludusavi (unmatched or ignored).
    const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
    if (result.status !== "skipped" || !silentReasons.includes(result.reason ?? "")) {
      let icon = <FaDatabase />;
      if (result.status === "failed") icon = <FaExclamationTriangle />;
      else if (result.status === "restored") icon = <FaDownload />;
      else if (result.status === "backed_up") icon = <FaSave />;

      showToast("SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), icon);
    }
  };

  const handleAppExit = async (name: string, appID: string) => {
    const tracked = isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);
    
    if (tracked && autoSyncNotificationsEnabled) {
      showToast("SDH-ludusavi Auto-sync", `Backing up saves for ${name}...`, <FaSave />);
    }
    
    const result = await handleGameExitCall(name, appID);
    const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
    if (result.status !== "skipped" || !silentReasons.includes(result.reason ?? "")) {
      if (result.status !== "skipped" || result.reason === "local_current") {
        const icon = result.status === "failed" ? <FaExclamationTriangle /> : <FaSave />;
        showToast("SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), icon);
      }
    }
  };

  const sessionFromAppOverview = (app: any): RunningSession | null => {
    const appID = app?.appid ? String(app.appid) : null;
    const name = app?.display_name || null;
    if (!appID || !name) {
      return null;
    }
    return { appID, name };
  };

  const getMainRunningSession = (): RunningSession | null => {
    return sessionFromAppOverview((Router as any).MainRunningApp);
  };

  const findRunningSessionByAppID = (appID: string): RunningSession | null => {
    // Router.RunningApps lets Steam app lifetime events recover the display name.
    const runningApps = (Router as any).RunningApps;
    if (Array.isArray(runningApps)) {
      for (const app of runningApps) {
        const session = sessionFromAppOverview(app);
        if (session?.appID === appID) {
          return session;
        }
      }
    }

    const mainSession = getMainRunningSession();
    if (mainSession?.appID === appID) {
      return mainSession;
    }

    return null;
  };

  const findStartupSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const startupSession = activeSessions.get(-1) ?? null;
    if (!startupSession) {
      return null;
    }
    if (notification.unAppID === 0 || startupSession.appID === String(notification.unAppID)) {
      return startupSession;
    }
    return null;
  };

  const resolveLifetimeSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const existingSession = activeSessions.get(notification.nInstanceID);
    if (existingSession) {
      return existingSession;
    }

    if (!notification.bRunning) {
      const startupSession = findStartupSession(notification);
      if (startupSession) {
        return startupSession;
      }
    }

    if (notification.unAppID > 0) {
      const appID = String(notification.unAppID);
      const runningSession = findRunningSessionByAppID(appID);
      if (runningSession) {
        return runningSession;
      }
      return { appID, name: "" };
    }

    // unAppID may be 0 for non-Steam shortcuts, so fall back to Router state.
    return getMainRunningSession();
  };

  const handleLifetimeNotification = (notification: AppLifetimeNotification) => {
    try {
      const session = resolveLifetimeSession(notification);
      if (!session?.name) {
        log(
          "warning",
          `Could not resolve app lifetime notification: ${JSON.stringify(notification)}`,
          "lifecycle"
        );
        return;
      }

      if (notification.bRunning) {
        const startupSession = findStartupSession(notification);
        if (startupSession?.appID === session.appID) {
          activeSessions.delete(-1);
          activeSessions.set(notification.nInstanceID, session);
          log(
            "debug",
            `Promoted startup session for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name
          );
          return;
        }

        if (activeSessions.has(notification.nInstanceID)) {
          log(
            "debug",
            `Duplicate app start ignored for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name
          );
          return;
        }

        activeSessions.set(notification.nInstanceID, session);
        void handleAppStart(session.name, session.appID);
        return;
      }

      activeSessions.delete(notification.nInstanceID);
      const startupSession = activeSessions.get(-1);
      if (startupSession?.appID === session.appID) {
        activeSessions.delete(-1);
      }
      void handleAppExit(session.name, session.appID);
    } catch (err) {
      console.error("SDH-ludusavi: app lifetime notification failed", err);
    }
  };

  const checkMainApp = () => {
    try {
      const mainApp = (Router as any).MainRunningApp;
      const currentAppID = mainApp?.appid ? String(mainApp.appid) : null;
      const currentAppName = mainApp?.display_name || null;

      if (currentAppID !== fallbackPreviousAppID) {
        // Change detected
        if (fallbackPreviousAppID && fallbackPreviousAppName) {
          void handleAppExit(fallbackPreviousAppName, fallbackPreviousAppID);
        }
        if (currentAppID && currentAppName) {
          void handleAppStart(currentAppName, currentAppID);
        }
        
        fallbackPreviousAppID = currentAppID;
        fallbackPreviousAppName = currentAppName;
      }
    } catch (err) {
      console.error("SDH-ludusavi: watcher loop failed", err);
    }
  };

  const startFallbackPolling = () => {
    log("warning", "Steam app lifetime notifications unavailable; using Router polling", "lifecycle");
    fallbackIntervalID = window.setInterval(checkMainApp, 1000);
  };

  const reconcileStartupSession = () => {
    const session = getMainRunningSession();
    if (!session) {
      return;
    }

    activeSessions.set(-1, session);
    void handleAppStart(session.name, session.appID);
  };

  const unregisterLifecycleNotifications = () => {
    const registration = lifecycleRegistration as
      | { unregister?: () => void; Unregister?: () => void }
      | (() => void)
      | null;
    if (!registration) {
      return;
    }

    if (typeof registration === "function") {
      registration();
    } else if (typeof registration.unregister === "function") {
      registration.unregister();
    } else if (typeof registration.Unregister === "function") {
      registration.Unregister();
    }
  };

  const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
  const gameSessions = steamClient?.GameSessions;
  const registerLifetime = gameSessions?.RegisterForAppLifetimeNotifications;
  if (typeof registerLifetime === "function") {
    lifecycleRegistration = registerLifetime.call(gameSessions, (notification: AppLifetimeNotification) => {
      handleLifetimeNotification(notification);
    });
    reconcileStartupSession();
  } else {
    startFallbackPolling();
  }

  return {
    name: "SDH-ludusavi",
    titleView: <div className={staticClasses.Title}>SDH-ludusavi</div>,
    content: <Content />,
    icon: <LuDatabaseBackup />,
    onDismount() {
      unregisterLifecycleNotifications();
      if (fallbackIntervalID !== null) {
        window.clearInterval(fallbackIntervalID);
      }
      activeSessions.clear();
      console.log("SDH-ludusavi unloading");
    },
  };
});
