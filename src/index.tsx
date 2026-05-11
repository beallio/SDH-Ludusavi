import {
  ButtonItem,
  ConfirmModal,
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
const refreshGamesCall = callable<[], RefreshResult>("refresh_games");
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
  const [dependencyError, setDependencyError] = useState<string | null>(null);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);

  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const isBusy = operation.is_running || busyLabel !== null;

  useEffect(() => {
    void loadInitial();
  }, []);

  const loadInitial = async () => {
    setBusyLabel("Loading");
    try {
      const loadedSettings = await getSettings();
      setSettings(loadedSettings);

      const [refreshed, loadedVersions] = await Promise.all([
        refreshGamesCall(),
        getVersions()
      ]);
      applyRefreshResult(refreshed);
      setVersions(loadedVersions);

      const loadedOperation = await getOperationStatus();
      setOperation(loadedOperation);
      const loadedLogs = await getRecentLogs();
      setLogs(loadedLogs);
    } catch (error) {
      setDependencyError(error instanceof Error ? error.message : String(error));
      setLogs(await getRecentLogs().catch(() => []));
    } finally {
      setBusyLabel(null);
    }
  };

  const applyRefreshResult = (result: RefreshResult) => {
    setGames(result.games);
    setDependencyError(result.dependency_error);
    setSelectedGame((current) => {
      if (current && result.games.some((game) => game.name === current)) {
        return current;
      }
      return result.games[0]?.name ?? "";
    });
  };

  const refreshGames = async () => {
    setBusyLabel("Refreshing games");
    try {
      const result = await refreshGamesCall();
      applyRefreshResult(result);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
      toaster.toast({
        title: "SDH-ludusavi",
        body: result.dependency_error ?? "Ludusavi game status refreshed"
      });
    } finally {
      setBusyLabel(null);
    }
  };

  const toggleAutoSync = async (enabled: boolean) => {
    const updated = await setAutoSyncEnabled(enabled);
    setSettings(updated);
  };

  const runForceOperation = async (
    label: "Backup" | "Restore",
    operationCall: (gameName: string) => Promise<OperationResult>
  ) => {
    if (!selectedGame) {
      return;
    }
    setBusyLabel(`${label} running`);
    toaster.toast({ title: `SDH-ludusavi ${label}`, body: `${label} started for ${selectedGame}` });
    try {
      const result = await operationCall(selectedGame);
      toaster.toast({
        title: `SDH-ludusavi ${label}`,
        body: summarizeOperationResult(result, label)
      });
      const refreshed = await refreshGamesCall();
      applyRefreshResult(refreshed);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
    } catch (error) {
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
          <select
            value={selectedGame}
            onChange={(event) => setSelectedGame(event.target.value)}
            style={{ width: "100%" }}
          >
            {games.map((game) => (
              <option key={game.name} value={game.name}>
                {game.name} - {statusLabels[game.status]}
              </option>
            ))}
          </select>
        </PanelSectionRow>

        <PanelSectionRow>
          <div>
            <div>{selectedStatus ? statusLabels[selectedStatus.status] : "No Ludusavi games found"}</div>
            {selectedStatus?.error ? <div>{selectedStatus.error}</div> : null}
            {dependencyError ? <div>{dependencyError}</div> : null}
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
            disabled={isBusy || !selectedStatus?.has_backup}
            onClick={() => void runForceOperation("Restore", forceRestoreCall)}
          >
            Force Restore
          </ButtonItem>
        </PanelSectionRow>

        {isBusy ? (
          <PanelSectionRow>
            <div>{busyLabel ?? `Running ${operation.name ?? "operation"}`}</div>
          </PanelSectionRow>
        ) : null}
      </PanelSection>

      <PanelSection title="Versions">
        <PanelSectionRow>
          <div>
            <div>SDH-ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>
            <div>Ludusavi: {versions.ludusavi ?? versions.message ?? "Unknown"}</div>
            <div>rclone: {versions.rclone ?? "Unknown"}</div>
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Logs">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<LogModal logs={logs} />)}>
            Show Logs
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
