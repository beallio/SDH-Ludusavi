import { showModal } from "@decky/ui";
import { useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FaDownload, FaExclamationTriangle, FaSave } from "react-icons/fa";
import { IoMdRefresh } from "react-icons/io";

import {
  forceBackupCall,
  getGameHistoryCall,
  getLudusaviCommandCall,
  getLudusaviLogs,
  getOperationStatus,
  getRecentLogs,
  getSettings,
  getVersions,
  isGameCacheCurrentCall,
  refreshGamesCall,
  restoreBackupVersionCall
} from "../../api/ludusaviRpc";
import { LogModal, LudusaviLogModal } from "../LogModal";
import { PluginUpdateSection } from "../PluginUpdateSection";
import { summarizeOperationResult } from "../../formatting/operationText";
import type { PluginRuntime } from "../../runtime/pluginRuntime";
import {
  defaultSettings,
  LudusaviStateStore,
  useLudusaviState,
  useLudusaviStateStore
} from "../../state/ludusaviState";
import type {
  GameStatus,
  LogEntry,
  NotificationCategory,
  OperationResult,
  OperationStatus,
  RefreshResult,
  RpcResult,
  RpcStatus,
} from "../../types";
import { log, logUiEvent } from "../../utils/logging";
import {
  captureSteamUiGameContext,
  getInstalledAppIdsString
} from "../../utils/steam";
import { AutoSyncSettingsSection } from "./AutoSyncSettingsSection";
import { GameSettingsSection } from "./GameSettingsSection";
import { BackupBrowserModal } from "../modals/BackupBrowserModal";
import { LudusaviLauncherSection } from "./LudusaviLauncherSection";
import { NotificationSettingsSection } from "./NotificationSettingsSection";
import { QamStyles } from "./QamStyles";
import { LogsSection, VersionsSection } from "./VersionAndLogsSection";
import { resolveAppliedSelection } from "./refreshSelection";
import { resolveQamOpenSelection } from "./qamOpenSelection";
import { runOperationFinalize } from "./manualOperationFinalize";
import { useSteamContext, selectCurrentSteamGameIfAvailable } from "./useSteamContext";
import { useInitialContent } from "./useInitialContent";
import { useGameRefresh } from "./useGameRefresh";

const EMPTY_GAMES: readonly GameStatus[] = Object.freeze([]);

type LudusaviContentProps = {
  runtime: PluginRuntime;
  dropdownCssText: string | null;
  notify: (
    store: LudusaviStateStore,
    category: NotificationCategory,
    title: string,
    body: string,
    logo?: any
  ) => void;
  isRpcStatus: <T>(result: RpcResult<T>) => result is RpcStatus;
  logRpcStatus: (result: RpcStatus, operation: string) => void;
};

export function LudusaviContent({
  runtime,
  dropdownCssText,
  notify,
  isRpcStatus,
  logRpcStatus
}: LudusaviContentProps) {
  const ludusaviState = useLudusaviState();
  const ludusaviStore = useLudusaviStateStore();
  const isQuickAccessVisible = useQuickAccessVisible();
  const qamContentRef = useRef<HTMLDivElement | null>(null);
  const isMounted = useRef(true);
  const operationInProgress = useRef(false);
  const explicitSelectionRef = useRef(false);
  const styleElement = useMemo(
    () => <QamStyles cssText={dropdownCssText} />,
    [dropdownCssText]
  );

  const settings = ludusaviState.settings ?? defaultSettings();
  const games = ludusaviState.games ?? EMPTY_GAMES;
  const gamesDropdownOptions = useMemo(() => {
    return games.map((game) => ({
      label: game.name,
      data: game.name
    }));
  }, [games]);
  const gameAliases = ludusaviState.gameAliases;
  const gameHistory = ludusaviState.gameHistory;
  const selectedGame = ludusaviState.selectedGame;
  const versions =
    ludusaviState.versions ?? {
      sdh_ludusavi: "Loading...",
      ludusavi: "Loading...",
      pyludusavi: "Loading...",
      decky: "Loading..."
    };
  const [operation, setOperation] = useState<OperationStatus>({
    is_running: false,
    name: null,
    game_name: null,
    last_result: null,
    last_error: null
  });
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [backgroundRefreshBusy, setBackgroundRefreshBusy] = useState(false);
  const ludusaviCommand = ludusaviState.ludusaviCommand;
  const notifySettingsFailure = useCallback(
    (title: string, body: string) => {
      notify(ludusaviStore, "failures_errors", title, body, <FaExclamationTriangle />);
    },
    [ludusaviStore, notify]
  );
  const settingsController = useMemo(
    () =>
      runtime.settings.createController({
        ludusaviStore,
        notifyFailure: notifySettingsFailure
      }),
    [runtime.settings, ludusaviStore, notifySettingsFailure]
  );





  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const selectedHistory = useMemo(() => {
    const history = gameHistory[selectedGame];
    return history?.last_operation ?? null;
  }, [gameHistory, selectedGame]);
  const isBusy = operation.is_running || busyLabel !== null || backgroundRefreshBusy;


  useSteamContext({
    isQuickAccessVisible,
    games,
    gameAliases,
    selectedGame,
    settingsLoaded: ludusaviState.settings !== null,
    operationInProgress: operationInProgress.current,
    qamContentRef,
    setDisplayedGame: (gameName) => ludusaviStore.setDisplayedGame(gameName),
    resolveQamOpenSelection,
    explicitSelectionPending: explicitSelectionRef.current,
    onExplicitSelectionConsumed: () => {
      explicitSelectionRef.current = false;
    },
  });

  useInitialContent({
    isMounted: () => isMounted.current,
    isWarmed: ludusaviState.settings !== null && ludusaviState.games !== null,
    installedAppIds: ludusaviState.installedAppIds,
    cachedGames: ludusaviState.games ?? null,
    initPromise: runtime.contentLoad.initPromise,
    metadataPromise: runtime.contentLoad.metadataPromise,
    setInitPromise: (p) => { runtime.contentLoad.initPromise = p; },
    setMetadataPromise: (p) => { runtime.contentLoad.metadataPromise = p; },
    getOperationStatus,
    getVersions,
    getLudusaviCommandCall,
    getSettings,
    getGameHistoryCall,
    isGameCacheCurrentCall,
    refreshGamesCall,
    applySettings: (settings) => runtime.settings.applySettings(ludusaviStore, settings),
    hydrateDisplayedGame: (gameName) => ludusaviStore.hydrateDisplayedGame(gameName),
    setGameHistory: (history) => ludusaviStore.setGameHistory(history),
    setVersions: (versions) => ludusaviStore.setVersions(versions),
    setLudusaviCommand: (command) => ludusaviStore.setLudusaviCommand(command),
    applyRefreshResult: (result, preferredGame, allowSelection) => applyRefreshResult(result, preferredGame, allowSelection),
    applyCachedRefreshResult: (preferredGame, allowSelection) => applyCachedRefreshResult(preferredGame, allowSelection),
    setInstalledAppIds: (appIds) => ludusaviStore.setInstalledAppIds(appIds),
    setOperation,
    setBackgroundRefreshBusy,
    setBusyLabel,
    isRpcStatus,
    logRpcStatus,
    logError: (message) => log("error", message),
  });

  const { refreshGames } = useGameRefresh({
    gamesCount: games.length,
    getInstalledAppIdsString,
    refreshGamesCall,
    getOperationStatus,
    getRecentLogs,
    applyRefreshResult: (result, preferredGame) => applyRefreshResult(result, preferredGame),
    setInstalledAppIds: (appIds) => ludusaviStore.setInstalledAppIds(appIds),
    setOperation,
    setLogs,
    setBusyLabel,
    notifyFailure: (title, body, icon) => notify(ludusaviStore, "failures_errors", title, body, icon),
    notifySuccess: (title, body, icon) => notify(ludusaviStore, "refresh_status", title, body, icon),
    isMounted: () => isMounted.current,
    isRpcStatus,
    logRpcStatus,
    icons: { refresh: <IoMdRefresh />, warning: <FaExclamationTriangle /> },
  });




  useEffect(() => {
    isMounted.current = true;
    runtime.settings.clearLastQueuedSelectedGame();
    logUiEvent("qam_content_mounted", {}, "info");
    return () => {
      logUiEvent("qam_content_unmounted", {}, "info");
      isMounted.current = false;
    };
  }, []);

  useEffect(() => {
    runtime.settings.syncLastQueuedSelectedGame(selectedGame);
  }, [selectedGame, runtime.settings]);


  useEffect(() => {
    if (isQuickAccessVisible) {
      return;
    }

    captureSteamUiGameContext();
    const contextIntervalID = window.setInterval(captureSteamUiGameContext, 500);
    return () => window.clearInterval(contextIntervalID);
  }, [isQuickAccessVisible]);


  const applyCachedRefreshResult = (preferredGame?: string, allowSteamContextSelection = false): boolean => {
    const cachedGames = ludusaviState.games;
    if (!cachedGames) {
      return false;
    }

    const cachedAliases = ludusaviState.gameAliases;

    if (allowSteamContextSelection && selectCurrentSteamGameIfAvailable(cachedGames, cachedAliases, (gameName) => ludusaviStore.setDisplayedGame(gameName))) {
      return true;
    }

    const currentSelectedGame = ludusaviStore.getSnapshot().selectedGame;
    const outcome = resolveAppliedSelection({
      games: cachedGames,
      preferredGame,
      liveSelection: currentSelectedGame,
    });
    ludusaviStore.setDisplayedGame(outcome.game);

    return true;
  };

  const applyRefreshResult = (
    result: RpcResult<RefreshResult>,
    preferredGame?: string,
    allowSteamContextSelection = false
  ): boolean => {
    if (isRpcStatus(result)) {
      logRpcStatus(result, "refresh");
      return false;
    }

    if (result.dependency_error) {
      log("error", `Ludusavi refresh failed: ${result.dependency_error}`, "refresh");
      notify(
        ludusaviStore,
        "failures_errors",
        "SDH-Ludusavi refresh failed",
        result.dependency_error,
        <FaExclamationTriangle />
      );
      return false;
    }

    log(
      "debug",
      `Applying refresh result (${result.games.length} games, ${Object.keys(result.aliases || {}).length} aliases)`
    );
    ludusaviStore.applyRefreshResult(result);
    log("info", `Tracked ${ludusaviStore.getSnapshot().trackedNames.size} game names/aliases`);

    if (
      allowSteamContextSelection &&
      selectCurrentSteamGameIfAvailable(result.games, result.aliases || {}, (gameName) => ludusaviStore.setDisplayedGame(gameName))
    ) {
      return true;
    }

    const currentSelectedGame = ludusaviStore.getSnapshot().selectedGame;
    const outcome = resolveAppliedSelection({
      games: result.games,
      preferredGame,
      liveSelection: currentSelectedGame,
    });
    if (outcome.source === "first") {
      log("debug", `Defaulting selected game to ${outcome.game}`);
    }
    ludusaviStore.setDisplayedGame(outcome.game);

    return true;
  };


  const showLudusaviLogs = async () => {
    logUiEvent("ludusavi_logs_requested", {}, "info", "logs");
    try {
      const result = await getLudusaviLogs();
      const logs =
        typeof result === "string" ? result : result.message || `Failed to fetch logs: ${result.status}`;
      showModal(<LudusaviLogModal logs={logs} />);
      logUiEvent("ludusavi_logs_opened", { character_count: logs.length }, "info", "logs");
    } catch (error) {
      log("error", `Failed to fetch Ludusavi logs: ${error}`);
      notify(
        ludusaviStore,
        "failures_errors",
        "SDH-Ludusavi",
        "Failed to fetch Ludusavi logs",
        <FaExclamationTriangle />
      );
    }
  };

  const showPluginLogs = async () => {
    try {
      logUiEvent("plugin_logs_requested", { cached_log_count: logs.length }, "info", "logs");
      const currentLogs = await getRecentLogs();
      if (isMounted.current) {
        setLogs(currentLogs);
      }
      showModal(<LogModal logs={currentLogs} />);
      logUiEvent("plugin_logs_opened", { log_count: currentLogs.length }, "info", "logs");
    } catch (error) {
      log("error", `Failed to fetch plugin logs: ${error}`);
      notify(
        ludusaviStore,
        "failures_errors",
        "SDH-Ludusavi",
        "Failed to fetch plugin logs",
        <FaExclamationTriangle />
      );
    }
  };

  const confirmInstalledPluginVersion = useCallback(
    (version: string) => {
      ludusaviStore.setVersions({
        ...(ludusaviStore.getSnapshot().versions ?? {}),
        sdh_ludusavi: version
      });
    },
    [ludusaviStore]
  );

  const {
    onGameChange,
    toggleAutoSync,
    toggleGameSync,
    toggleAutomaticUpdateChecks,
    toggleNotificationSetting,
    toggleUpdateChannel,
    toggleDebugLogging
  } = settingsController;

  const handleGameChange = (data: Parameters<typeof onGameChange>[0]) => {
    explicitSelectionRef.current = true;
    onGameChange(data);
  };

  const runForceOperation = async (
    label: "Backup" | "Restore",
    operationCall: (gameName: string) => Promise<RpcResult<OperationResult>>
  ) => {
    if (!selectedGame) {
      logUiEvent("manual_operation_skipped", { reason: "no_selected_game", type: label }, "warning");
      return;
    }
    operationInProgress.current = true;
    const startedAt = performance.now();
    logUiEvent("manual_operation_started", { type: label }, "info", label, selectedGame);
    setBusyLabel(`${label} running`);
    const icon = label === "Backup" ? <FaSave /> : <FaDownload />;
    notify(
      ludusaviStore,
      "manual_operations",
      `SDH-Ludusavi ${label}`,
      `${label} started for ${selectedGame}`,
      icon
    );
    try {
      const result = await operationCall(selectedGame);
      logUiEvent(
        "manual_operation_completed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          reason: result.reason,
          status: result.status,
          type: label,
        },
        result.status === "failed" ? "error" : "info",
        label,
        selectedGame,
      );
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      const category = result.status === "failed" ? "failures_errors" : "manual_operations";
      notify(
        ludusaviStore,
        category,
        `SDH-Ludusavi ${label}`,
        summarizeOperationResult(result, label),
        resultIcon
      );
      await runOperationFinalize({
        selectedGame,
        refreshGamesCall,
        getOperationStatus,
        getRecentLogs,
        getGameHistoryCall,
        applyRefreshResult,
        setOperation,
        setLogs,
        setGameHistory: ludusaviStore.setGameHistory.bind(ludusaviStore),
        isMounted: () => isMounted.current,
        isRpcStatus,
      });
    } catch (error) {
      logUiEvent(
        "manual_operation_failed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          message: error instanceof Error ? error.message : String(error),
          type: label,
        },
        "error",
        label,
        selectedGame,
      );
      log("error", `Force ${label} failed: ${error}`, label, selectedGame);
      notify(
        ludusaviStore,
        "failures_errors",
        `SDH-Ludusavi ${label} failed`,
        error instanceof Error ? error.message : String(error),
        <FaExclamationTriangle />
      );
    } finally {
      operationInProgress.current = false;
      if (isMounted.current) {
        setBusyLabel(null);
      }
    }
  };

  const runSnapshotRestore = async (backupId: string, whenLabel: string) => {
    if (!selectedGame) return;
    operationInProgress.current = true;
    const label = "Restore";
    const startedAt = performance.now();
    logUiEvent("manual_operation_started", { type: label, backup_id: backupId }, "info", label, selectedGame);
    setBusyLabel(`${label} running`);
    const icon = <FaDownload />;
    notify(
      ludusaviStore,
      "manual_operations",
      `SDH-Ludusavi ${label}`,
      `${label} started for ${selectedGame} (${whenLabel})`,
      icon
    );
    try {
      const result = await restoreBackupVersionCall(selectedGame, backupId);
      logUiEvent(
        "manual_operation_completed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          reason: result.reason,
          status: result.status,
          type: label,
          backup_id: backupId,
        },
        result.status === "failed" ? "error" : "info",
        label,
        selectedGame,
      );
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      const category = result.status === "failed" ? "failures_errors" : "manual_operations";
      notify(
        ludusaviStore,
        category,
        `SDH-Ludusavi ${label}`,
        summarizeOperationResult(result, label),
        resultIcon
      );
      await runOperationFinalize({
        selectedGame,
        refreshGamesCall,
        getOperationStatus,
        getRecentLogs,
        getGameHistoryCall,
        applyRefreshResult,
        setOperation,
        setLogs,
        setGameHistory: ludusaviStore.setGameHistory.bind(ludusaviStore),
        isMounted: () => isMounted.current,
        isRpcStatus,
      });
    } catch (error) {
      logUiEvent(
        "manual_operation_failed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          message: error instanceof Error ? error.message : String(error),
          type: label,
          backup_id: backupId,
        },
        "error",
        label,
        selectedGame,
      );
      log("error", `Snapshot ${label} failed: ${error}`, label, selectedGame);
      notify(
        ludusaviStore,
        "failures_errors",
        `SDH-Ludusavi ${label} failed`,
        error instanceof Error ? error.message : String(error),
        <FaExclamationTriangle />
      );
    } finally {
      operationInProgress.current = false;
      if (isMounted.current) {
        setBusyLabel(null);
      }
    }
  };

  return (
    <div ref={qamContentRef} className="sdh-ludusavi-qam-container">
      {styleElement}

      <AutoSyncSettingsSection
        settings={settings}
        isBusy={isBusy}
        refreshLoading={busyLabel === "Refreshing games"}
        onToggleAutoSync={(enabled) => void toggleAutoSync(enabled)}
        onRefreshGames={() => void refreshGames()}
      />

      <GameSettingsSection
        isBusy={isBusy}
        busyLabel={busyLabel}
        gamesDropdownOptions={gamesDropdownOptions}
        selectedGame={selectedGame}
        selectedStatus={selectedStatus}
        selectedHistory={selectedHistory}
        gameSyncEnabled={!(settings.sync_disabled_games ?? []).includes(selectedGame)}
        onGameChange={handleGameChange}
        onToggleGameSync={(enabled) => void toggleGameSync(selectedGame, enabled)}
        onForceBackup={() => void runForceOperation("Backup", forceBackupCall)}
        onBrowseBackups={() => {
          if (!selectedGame) return;
          showModal(
            <BackupBrowserModal
              gameName={selectedGame}
              isRpcStatus={isRpcStatus}
              logRpcStatus={logRpcStatus}
              onRestoreSnapshot={runSnapshotRestore}
            />
          );
        }}
      />

      <NotificationSettingsSection
        settings={settings}
        isBusy={isBusy}
        onToggleNotificationSetting={(key, enabled) => void toggleNotificationSetting(key, enabled)}
      />

      <LudusaviLauncherSection
        ludusaviCommand={ludusaviCommand}
        isLoading={busyLabel === "Loading"}
      />

      <LogsSection
        onShowPluginLogs={() => void showPluginLogs()}
        onShowLudusaviLogs={() => void showLudusaviLogs()}
        debugLogging={settings.debug_logging}
        isBusy={isBusy}
        onToggleDebugLogging={(enabled) => void toggleDebugLogging(enabled)}
      />

      <PluginUpdateSection
        currentVersion={versions.sdh_ludusavi ?? "Unknown"}
        updateChannel={settings.update_channel}
        automaticUpdateChecks={settings.automatic_update_checks}
        onToggleUpdateChannel={toggleUpdateChannel}
        onToggleAutomaticUpdateChecks={toggleAutomaticUpdateChecks}
        onInstallVersionConfirmed={confirmInstalledPluginVersion}
      />

      <VersionsSection versions={versions} />
    </div>
  );
}
