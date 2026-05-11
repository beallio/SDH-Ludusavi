import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  showModal,
  staticClasses,
  ToggleField
} from "@decky/ui";
import {
  callable,
  definePlugin,
  toaster
} from "@decky/api";
import { useEffect, useMemo, useState } from "react";
import { FaDatabase } from "react-icons/fa";

type Settings = {
  auto_sync_enabled: boolean;
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
  rclone?: string;
  status?: string;
  message?: string;
};

type LogEntry = {
  level: string;
  message: string;
  operation: string | null;
  game_name: string | null;
};

type LogModalProps = {
  logs: LogEntry[];
  closeModal?: () => void;
};

const getSettings = callable<[], Settings>("get_settings");
const setAutoSyncEnabled = callable<[enabled: boolean], Settings>("set_auto_sync_enabled");
const refreshGamesCall = callable<[force: boolean], RefreshResult>("refresh_games");
const forceBackupCall = callable<[gameName: string], OperationResult>("force_backup");
const forceRestoreCall = callable<[gameName: string], OperationResult>("force_restore");
const getVersions = callable<[], Versions>("get_versions");
const getOperationStatus = callable<[], OperationStatus>("get_operation_status");
const getRecentLogs = callable<[], LogEntry[]>("get_recent_logs");

const statusLabels: Record<GameStatus["status"], string> = {
  configured: "Configured",
  has_backup: "Backup ready",
  needs_first_backup: "Needs first backup",
  error: "Error"
};

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

function Content() {
  const [settings, setSettings] = useState<Settings>({ auto_sync_enabled: false });
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

  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const isBusy = operation.is_running || busyLabel !== null;

  useEffect(() => {
    console.log("SDH-ludusavi: Plugin mounted, starting initial load");
    void loadInitial();
  }, []);

  const loadInitial = async () => {
    setBusyLabel("Loading");
    try {
      console.log("SDH-ludusavi: Fetching initial settings and versions");
      const loadedSettings = await getSettings();
      console.log("SDH-ludusavi: Loaded settings:", loadedSettings);
      setSettings(loadedSettings);

      const loadedVersions = await getVersions();
      console.log("SDH-ludusavi: Loaded versions:", loadedVersions);
      setVersions(loadedVersions);

      console.log("SDH-ludusavi: Initializing game list (cached)");
      const refreshed = await refreshGamesCall(false);
      applyRefreshResult(refreshed);

      const loadedOperation = await getOperationStatus();
      setOperation(loadedOperation);
      const loadedLogs = await getRecentLogs();
      setLogs(loadedLogs);
    } catch (error) {
      console.error("SDH-ludusavi: Initial load failed:", error);
      setLogs(await getRecentLogs().catch(() => []));
    } finally {
      setBusyLabel(null);
    }
  };

  const applyRefreshResult = (result: RefreshResult) => {
    console.log(`SDH-ludusavi: Applying refresh result (${result.games.length} games)`);
    setGames(result.games);
    setSelectedGame((current) => {
      if (current && result.games.some((game) => game.name === current)) {
        return current;
      }
      const firstGame = result.games[0]?.name ?? "";
      console.log(`SDH-ludusavi: Defaulting selected game to ${firstGame}`);
      return firstGame;
    });
  };

  const refreshGames = async () => {
    console.log("SDH-ludusavi: Manual refresh triggered");
    setBusyLabel("Refreshing games");
    try {
      const result = await refreshGamesCall(true);
      applyRefreshResult(result);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
      toaster.toast({
        title: "SDH-ludusavi",
        body: "Ludusavi game status refreshed"
      });
    } catch (error) {
      console.error("SDH-ludusavi: Manual refresh failed:", error);
    } finally {
      setBusyLabel(null);
    }
  };

  const toggleAutoSync = async (enabled: boolean) => {
    console.log(`SDH-ludusavi: Toggling auto-sync to ${enabled}`);
    setBusyLabel("Updating settings");
    try {
      const updated = await setAutoSyncEnabled(enabled);
      setSettings(updated);
    } catch (error) {
      console.error("SDH-ludusavi: Failed to toggle auto-sync:", error);
      toaster.toast({
        title: "SDH-ludusavi settings failed",
        body: error instanceof Error ? error.message : String(error)
      });
    } finally {
      setBusyLabel(null);
    }
  };

  const runForceOperation = async (
    label: "Backup" | "Restore",
    operationCall: (gameName: string) => Promise<OperationResult>
  ) => {
    if (!selectedGame) {
      return;
    }
    console.log(`SDH-ludusavi: Triggering force ${label} for ${selectedGame}`);
    setBusyLabel(`${label} running`);
    toaster.toast({ title: `SDH-ludusavi ${label}`, body: `${label} started for ${selectedGame}` });
    try {
      const result = await operationCall(selectedGame);
      console.log(`SDH-ludusavi: Force ${label} completed:`, result);
      toaster.toast({
        title: `SDH-ludusavi ${label}`,
        body: summarizeOperationResult(result, label)
      });
      const refreshed = await refreshGamesCall(false);
      applyRefreshResult(refreshed);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
    } catch (error) {
      console.error(`SDH-ludusavi: Force ${label} failed:`, error);
      toaster.toast({
        title: `SDH-ludusavi ${label} failed`,
        body: error instanceof Error ? error.message : String(error)
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
            rgOptions={games.map((game) => ({
              label: game.name,
              data: game.name
            }))}
            selectedOption={selectedGame}
            onChange={(data: any) => {
              const value = typeof data === 'object' ? data?.data : data;
              console.log(`SDH-ludusavi: Selected game changed to ${value}`);
              setSelectedGame(value);
            }}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <div style={{ color: "#cbd5e1", fontSize: "14px", margin: "12px 0", padding: "0 4px" }}>
            <span style={{ color: "#64748b", fontWeight: "bold", marginRight: "8px" }}>Status:</span>
            {selectedStatus ? statusLabels[selectedStatus.status] : "No Ludusavi games found"}
          </div>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem layout="below" disabled={isBusy} onClick={() => void refreshGames()}>
            Refresh Games
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={isBusy || !selectedStatus}
            onClick={() => void runForceOperation("Backup", forceBackupCall)}
          >
            Force Backup
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={isBusy || selectedStatus?.status !== "has_backup"}
            onClick={() => void runForceOperation("Restore", forceRestoreCall)}
          >
            Force Restore
          </ButtonItem>
        </PanelSectionRow>

        {isBusy ? (
          <PanelSectionRow>
            <div style={{ color: "#60a5fa", fontSize: "14px", marginTop: "12px", padding: "0 4px", fontWeight: 500 }}>
              {busyLabel ?? `Running ${operation.name ?? "operation"}`}
            </div>
          </PanelSectionRow>
        ) : null}
      </PanelSection>

      <PanelSection title="Versions">
        <PanelSectionRow>
          <div style={{ color: "#cbd5e1", fontSize: "14px", display: "flex", flexDirection: "column", gap: "4px", padding: "12px", backgroundColor: "rgba(30, 41, 59, 0.3)", borderRadius: "4px" }}>
            <div>SDH-ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>
            <div>Ludusavi: {versions.ludusavi ?? versions.message ?? "Unknown"}</div>
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Logs">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<LogModal logs={logs} />)}>
            View Logs
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

function summarizeOperationResult(result: OperationResult, label: "Backup" | "Restore") {
  if (result.status === "skipped") {
    return `${label} skipped: ${result.reason ?? "unknown reason"}`;
  }
  if (result.status === "failed") {
    return `${label} failed: ${result.message ?? "unknown error"}`;
  }
  return `${label} ${result.status === "backed_up" ? "completed" : "completed"} for ${result.game}`;
}

function formatLogEntry(entry: LogEntry) {
  const game = entry.game_name ? ` ${entry.game_name}` : "";
  return `[${entry.level}]${game} ${entry.message}`;
}

export default definePlugin(() => {
  console.log("SDH-ludusavi plugin initializing");

  return {
    name: "SDH-ludusavi",
    titleView: <div className={staticClasses.Title}>SDH-ludusavi</div>,
    content: <Content />,
    icon: <FaDatabase />,
    onDismount() {
      console.log("SDH-ludusavi unloading");
    },
  };
});
