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
const refreshGamesCall = callable<[force: boolean], RefreshResult>("refresh_games");
const forceBackupCall = callable<[gameName: string], OperationResult>("force_backup");
const forceRestoreCall = callable<[gameName: string], OperationResult>("force_restore");
const getVersions = callable<[], Versions>("get_versions");
const getOperationStatus = callable<[], OperationStatus>("get_operation_status");
const getRecentLogs = callable<[], LogEntry[]>("get_recent_logs");
const getLudusaviLogs = callable<[], string>("get_ludusavi_logs");
const logCall = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");
const getLudusaviCommandCall = callable<[], LudusaviLaunchCommand | null>("get_ludusavi_command");
const handleGameStartCall = callable<[gameName: string, app_id?: string], OperationResult>("handle_game_start");
const handleGameExitCall = callable<[gameName: string, app_id?: string], OperationResult>("handle_game_exit");

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
  const [ludusaviCommand, setLudusaviCommand] = useState<LudusaviLaunchCommand | null>(null);

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
      if (loadedSettings.selected_game) {
        setSelectedGame(loadedSettings.selected_game);
      }

      log("debug", `Loaded versions: ${JSON.stringify(loadedVersions)}`);
      setVersions(loadedVersions);

      log("debug", `Loaded command: ${JSON.stringify(loadedCommand)}`);
      setLudusaviCommand(loadedCommand);

      log("debug", "Initializing game list (cached)");
      const refreshed = await refreshGamesCall(false);
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

  const applyRefreshResult = (result: RefreshResult, preferredGame?: string) => {
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
  };

  const refreshGames = async () => {
    log("info", "Manual refresh triggered");
    setBusyLabel("Refreshing games");
    try {
      const result = await refreshGamesCall(true);
      applyRefreshResult(result);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
      toaster.toast({
        title: "SDH-ludusavi",
        body: "Ludusavi game status refreshed",
        logo: <IoMdRefresh size={40} />,
        duration: 2000
      });
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
    } catch (error) {
      log("error", `Failed to persist selected game: ${error}`);
    }
  };

  const runForceOperation = async (
    label: "Backup" | "Restore",
    operationCall: (gameName: string) => Promise<OperationResult>
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
          onChange={(enabled) => void toggleAutoSync(enabled)}
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

      <LudusaviPanel ludusaviCommand={ludusaviCommand} />

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
  ludusaviCommand 
}: { 
  ludusaviCommand: LudusaviLaunchCommand | null 
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

      await launchLudusavi(ludusaviCommand);

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
      
      {!ludusaviCommand && !isLaunching && (
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

  let previousAppID: string | null = null;
  let previousAppName: string | null = null;

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
    
    if (tracked) {
      showToast("SDH-ludusavi Auto-sync", `Checking saves for ${name}...`, <FaDatabase />);
    }
    
    const result = await handleGameStartCall(name, appID);
    // Show result toast for all outcomes (restored, failed, or skipped)
    // unless auto-sync is completely disabled or another operation is running.
    if (result.status !== "skipped" || (result.reason !== "auto_sync_disabled" && result.reason !== "operation_running")) {
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
    
    if (tracked) {
      showToast("SDH-ludusavi Auto-sync", `Backing up saves for ${name}...`, <FaSave />);
    }
    
    const result = await handleGameExitCall(name, appID);
    if (result.status !== "skipped" || (result.reason !== "auto_sync_disabled" && result.reason !== "operation_running")) {
      if (result.status !== "skipped" || result.reason === "local_current") {
        const icon = result.status === "failed" ? <FaExclamationTriangle /> : <FaSave />;
        showToast("SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), icon);
      }
    }
  };

  const checkMainApp = () => {
    try {
      const mainApp = (Router as any).MainRunningApp;
      const currentAppID = mainApp?.appid ? String(mainApp.appid) : null;
      const currentAppName = mainApp?.display_name || null;

      if (currentAppID !== previousAppID) {
        // Change detected
        if (previousAppID && previousAppName) {
          void handleAppExit(previousAppName, previousAppID);
        }
        if (currentAppID && currentAppName) {
          void handleAppStart(currentAppName, currentAppID);
        }
        
        previousAppID = currentAppID;
        previousAppName = currentAppName;
      }
    } catch (err) {
      console.error("SDH-ludusavi: watcher loop failed", err);
    }
  };

  const intervalID = window.setInterval(checkMainApp, 1000);

  return {
    name: "SDH-ludusavi",
    titleView: <div className={staticClasses.Title}>SDH-ludusavi</div>,
    content: <Content />,
    icon: <LuDatabaseBackup />,
    onDismount() {
      window.clearInterval(intervalID);
      console.log("SDH-ludusavi unloading");
    },
  };
});
