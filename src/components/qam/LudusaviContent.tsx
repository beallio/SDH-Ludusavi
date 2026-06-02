import { showModal } from "@decky/ui";
import { useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FaDownload, FaExclamationTriangle, FaSave } from "react-icons/fa";
import { IoMdRefresh } from "react-icons/io";

import {
  forceBackupCall,
  forceRestoreCall,
  getGameHistoryCall,
  getLudusaviCommandCall,
  getLudusaviLogs,
  getOperationStatus,
  getRecentLogs,
  getSettings,
  getVersions,
  isGameCacheCurrentCall,
  refreshGamesCall
} from "../../api/ludusaviRpc";
import { LogModal, LudusaviLogModal } from "../LogModal";
import { PluginUpdateSection } from "../PluginUpdateSection";
import { summarizeOperationResult } from "../../formatting/operationText";
import {
  applySettingsGlobal,
  clearLastQueuedSelectedGame,
  createSettingsMutationController,
  getSettingsQueueBusy,
  subscribeQueue,
  syncLastQueuedSelectedGame
} from "../../settings/settingsMutationController";
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
  Settings
} from "../../types";
import { log } from "../../utils/logging";
import {
  captureSteamUiGameContext,
  findGameForRunningSession,
  getInstalledAppIdsString,
  getPreferredSteamGameSession,
  logCurrentGameNoMatch,
  logCurrentGameSelection,
  resetQuickAccessScroll
} from "../../utils/steam";
import { AutoSyncSettingsSection } from "./AutoSyncSettingsSection";
import { GameSettingsSection } from "./GameSettingsSection";
import { LudusaviLauncherSection } from "./LudusaviLauncherSection";
import { NotificationSettingsSection } from "./NotificationSettingsSection";
import { QamStyles } from "./QamStyles";
import { LogsSection, VersionsSection } from "./VersionAndLogsSection";

const EMPTY_GAMES: readonly GameStatus[] = Object.freeze([]);

let activeInitPromise: Promise<OperationStatus> | null = null;
let activeMetadataPromise: Promise<void> | null = null;

export function resetLudusaviContentLoadState() {
  activeInitPromise = null;
  activeMetadataPromise = null;
}

type LudusaviContentProps = {
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
  dropdownCssText,
  notify,
  isRpcStatus,
  logRpcStatus
}: LudusaviContentProps) {
  const ludusaviState = useLudusaviState();
  const ludusaviStore = useLudusaviStateStore();
  const isQuickAccessVisible = useQuickAccessVisible();
  const qamContentRef = useRef<HTMLDivElement | null>(null);
  const wasQuickAccessVisible = useRef(false);
  const pendingCurrentGameSelection = useRef(false);
  const isMounted = useRef(true);
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
  const [queueBusy, setQueueBusy] = useState(getSettingsQueueBusy());
  const ludusaviCommand = ludusaviState.ludusaviCommand;
  const notifySettingsFailure = useCallback(
    (title: string, body: string) => {
      notify(ludusaviStore, "failures_errors", title, body, <FaExclamationTriangle />);
    },
    [ludusaviStore, notify]
  );
  const settingsController = useMemo(
    () =>
      createSettingsMutationController({
        ludusaviStore,
        isMounted,
        setBusyLabel,
        notifyFailure: notifySettingsFailure
      }),
    [ludusaviStore, notifySettingsFailure]
  );

  useEffect(() => {
    return subscribeQueue((busy) => {
      if (isMounted.current) {
        setQueueBusy(busy);
        if (!busy) {
          setBusyLabel((prev) => (prev === "Updating settings" ? null : prev));
        }
      }
    });
  }, []);

  const syncSelectedGameCache = (nextSelectedGame: string) => {
    ludusaviStore.syncSelectedGameCache(nextSelectedGame);
  };

  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const selectedHistory = useMemo(() => {
    const history = gameHistory[selectedGame];
    return history?.last_operation ?? null;
  }, [gameHistory, selectedGame]);
  const isBusy = operation.is_running || busyLabel !== null || backgroundRefreshBusy || queueBusy;

  function selectCurrentSteamGameIfAvailable(
    currentGames: readonly GameStatus[],
    currentAliases: Record<string, string>
  ): boolean {
    const runningSession = getPreferredSteamGameSession();
    if (!runningSession) {
      logCurrentGameNoMatch(null, currentGames, currentAliases);
      return false;
    }

    const runningGame = findGameForRunningSession(currentGames, runningSession, currentAliases);
    if (!runningGame) {
      logCurrentGameNoMatch(runningSession, currentGames, currentAliases);
      return false;
    }

    ludusaviStore.setSelectedGame(runningGame.game.name);
    logCurrentGameSelection(
      runningSession,
      runningGame.game,
      runningGame.reason,
      currentGames,
      currentAliases
    );
    return true;
  }

  useEffect(() => {
    isMounted.current = true;
    clearLastQueuedSelectedGame();
    log("info", "Plugin mounted, starting initial load");
    void loadInitial();
    return () => {
      isMounted.current = false;
    };
  }, []);

  useEffect(() => {
    syncLastQueuedSelectedGame(selectedGame);
  }, [selectedGame]);

  useEffect(() => {
    if (isQuickAccessVisible && !wasQuickAccessVisible.current) {
      pendingCurrentGameSelection.current = true;
      const resetDelays = [50, 150, 350];
      resetQuickAccessScroll(qamContentRef.current);
      resetDelays.forEach((delay) => {
        window.setTimeout(
          () => resetQuickAccessScroll(qamContentRef.current, `qam_open_retry_${delay}`),
          delay
        );
      });
    }
    wasQuickAccessVisible.current = isQuickAccessVisible;
  }, [isQuickAccessVisible]);

  useEffect(() => {
    if (!isQuickAccessVisible || !pendingCurrentGameSelection.current || games.length === 0) {
      return;
    }

    selectCurrentSteamGameIfAvailable(games, gameAliases);
    pendingCurrentGameSelection.current = false;
  }, [gameAliases, games, isQuickAccessVisible]);

  useEffect(() => {
    if (isQuickAccessVisible) {
      return;
    }

    captureSteamUiGameContext();
    const contextIntervalID = window.setInterval(captureSteamUiGameContext, 500);
    return () => window.clearInterval(contextIntervalID);
  }, [isQuickAccessVisible]);

  const loadInitial = async () => {
    const isWarmed = ludusaviState.settings !== null && ludusaviState.games !== null;
    if (!isMounted.current) return;
    if (!isWarmed) {
      setBusyLabel("Loading");
    }
    setBackgroundRefreshBusy(isWarmed);

    fetchMetadata();

    if (!activeInitPromise) {
      log("debug", `Creating new initialization promise (warmed=${isWarmed})`);
      activeInitPromise = (async () => {
        const loadedSettings = await fetchInitialState();
        await synchronizeGameList(isWarmed, loadedSettings);
        return getOperationStatus();
      })();
    } else {
      log("debug", "Reusing in-flight initialization promise");
    }

    try {
      const loadedOperation = await activeInitPromise;
      if (isMounted.current) {
        setOperation(loadedOperation);
      }
    } catch (error) {
      log("error", `Initial load failed: ${error}`);
    } finally {
      activeInitPromise = null;
      if (isMounted.current) {
        setBackgroundRefreshBusy(false);
        setBusyLabel(null);
      }
    }
  };

  const fetchMetadata = () => {
    const snapshot = ludusaviStore.getSnapshot();
    if (snapshot.versions !== null && snapshot.ludusaviCommand !== null) {
      return;
    }
    if (activeMetadataPromise) {
      return;
    }
    // Load versions and commands in the background asynchronously.
    activeMetadataPromise = (async () => {
      try {
        const [versionsResult, commandResult] = await Promise.allSettled([
          getVersions(),
          getLudusaviCommandCall()
        ]);

        if (versionsResult.status === "fulfilled") {
          const loadedVersions = versionsResult.value;
          log("debug", `Loaded versions: ${JSON.stringify(loadedVersions)}`);
          if (isRpcStatus(loadedVersions)) {
            logRpcStatus(loadedVersions, "versions");
            ludusaviStore.setVersions({ message: loadedVersions.message || "Error" });
          } else {
            ludusaviStore.setVersions(loadedVersions);
          }
        } else {
          log("error", `Background load of versions failed: ${versionsResult.reason}`);
          ludusaviStore.setVersions({ message: "Error" });
        }

        if (commandResult.status === "fulfilled") {
          const loadedCommand = commandResult.value;
          log("debug", `Loaded command: ${JSON.stringify(loadedCommand)}`);
          if (isRpcStatus(loadedCommand)) {
            logRpcStatus(loadedCommand, "command discovery");
          } else {
            ludusaviStore.setLudusaviCommand(loadedCommand);
          }
        } else {
          log("error", `Background load of command failed: ${commandResult.reason}`);
        }
      } catch (err) {
        log("error", `fetchMetadata failed: ${err}`);
      } finally {
        activeMetadataPromise = null;
      }
    })();
  };

  const fetchInitialState = async (): Promise<RpcResult<Settings>> => {
    const [loadedSettings, loadedHistory] = await Promise.all([
      getSettings(),
      getGameHistoryCall()
    ]);

    log("debug", `Loaded settings: ${JSON.stringify(loadedSettings)}`);
    if (isRpcStatus(loadedSettings)) {
      logRpcStatus(loadedSettings, "settings");
    } else {
      applySettingsGlobal(ludusaviStore, loadedSettings);
    }

    if (isRpcStatus(loadedHistory)) {
      logRpcStatus(loadedHistory, "history");
    } else {
      ludusaviStore.setGameHistory(loadedHistory);
    }

    return loadedSettings;
  };

  const synchronizeGameList = async (isWarmed: boolean, loadedSettings: RpcResult<Settings>) => {
    log("debug", "Initializing game list (cached)");
    const installedAppIds = await getInstalledAppIdsString();
    const installedAppIdsChanged = ludusaviState.installedAppIds !== installedAppIds;

    const cacheCurrentResult =
      isWarmed && !installedAppIdsChanged
        ? await isGameCacheCurrentCall(installedAppIds)
        : false;

    const cacheCurrent = !isRpcStatus(cacheCurrentResult) && cacheCurrentResult === true;
    const preferredGame = isRpcStatus(loadedSettings) ? undefined : loadedSettings.selected_game;

    if (cacheCurrent && ludusaviState.games) {
      applyCachedRefreshResult(preferredGame);
    } else {
      const refreshed = await refreshGamesCall(false, installedAppIds);
      if (applyRefreshResult(refreshed, preferredGame)) {
        ludusaviStore.setInstalledAppIds(installedAppIds);
      }
    }
  };

  const applyCachedRefreshResult = (preferredGame?: string): boolean => {
    const cachedGames = ludusaviState.games;
    if (!cachedGames) {
      return false;
    }

    const cachedAliases = ludusaviState.gameAliases;

    if (selectCurrentSteamGameIfAvailable(cachedGames, cachedAliases)) {
      return true;
    }

    const target = preferredGame || selectedGame;
    if (target && cachedGames.some((game) => game.name === target)) {
      ludusaviStore.setSelectedGame(target);
      syncSelectedGameCache(target);
    } else {
      const firstGame = cachedGames[0]?.name ?? "";
      ludusaviStore.setSelectedGame(firstGame);
      syncSelectedGameCache(firstGame);
    }
    return true;
  };

  const applyRefreshResult = (
    result: RpcResult<RefreshResult>,
    preferredGame?: string
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

    if (selectCurrentSteamGameIfAvailable(result.games, result.aliases || {})) {
      return true;
    }

    const target = preferredGame || selectedGame;
    if (target && result.games.some((game: GameStatus) => game.name === target)) {
      ludusaviStore.setSelectedGame(target);
      syncSelectedGameCache(target);
    } else {
      const firstGame = result.games[0]?.name ?? "";
      log("debug", `Defaulting selected game to ${firstGame}`);
      ludusaviStore.setSelectedGame(firstGame);
      syncSelectedGameCache(firstGame);
    }

    return true;
  };

  const refreshGames = async () => {
    log("info", "Manual refresh triggered");
    setBusyLabel("Refreshing games");
    try {
      const installedAppIds = await getInstalledAppIdsString();
      const result = await refreshGamesCall(true, installedAppIds);
      if (isRpcStatus(result)) {
        logRpcStatus(result, "refresh");
        notify(
          ludusaviStore,
          "failures_errors",
          "SDH-Ludusavi refresh failed",
          result.message || "Failed to refresh games",
          <FaExclamationTriangle />
        );
      } else if (applyRefreshResult(result)) {
        ludusaviStore.setInstalledAppIds(installedAppIds);
        notify(
          ludusaviStore,
          "refresh_status",
          "SDH-Ludusavi",
          "Ludusavi game status refreshed",
          <IoMdRefresh />
        );
        const operationStatus = await getOperationStatus();
        const recentLogs = await getRecentLogs();
        if (isMounted.current) {
          setOperation(operationStatus);
          setLogs(recentLogs);
        }
      }
    } catch (error) {
      log("error", `Manual refresh failed: ${error}`);
      notify(
        ludusaviStore,
        "failures_errors",
        "SDH-Ludusavi refresh failed",
        error instanceof Error ? error.message : String(error),
        <FaExclamationTriangle />
      );
    } finally {
      if (isMounted.current) {
        setBusyLabel(null);
      }
    }
  };

  const showLudusaviLogs = async () => {
    log("info", "Showing Ludusavi logs");
    try {
      const result = await getLudusaviLogs();
      const logs =
        typeof result === "string" ? result : result.message || `Failed to fetch logs: ${result.status}`;
      showModal(<LudusaviLogModal logs={logs} />);
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
      log("debug", `Fetching plugin logs (cached=${logs.length})`, "logs");
      const currentLogs = await getRecentLogs();
      if (isMounted.current) {
        setLogs(currentLogs);
      }
      showModal(<LogModal logs={currentLogs} />);
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

  const {
    onGameChange,
    toggleAutoSync,
    toggleAutomaticUpdateChecks,
    toggleNotificationSetting,
    toggleUpdateChannel
  } = settingsController;

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
    notify(
      ludusaviStore,
      "manual_operations",
      `SDH-Ludusavi ${label}`,
      `${label} started for ${selectedGame}`,
      icon
    );
    try {
      const result = await operationCall(selectedGame);
      log("info", `Force ${label} completed: ${JSON.stringify(result)}`, label, selectedGame);
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      const category = result.status === "failed" ? "failures_errors" : "manual_operations";
      notify(
        ludusaviStore,
        category,
        `SDH-Ludusavi ${label}`,
        summarizeOperationResult(result, label),
        resultIcon
      );
      const refreshed = await refreshGamesCall(false);
      const operationStatus = await getOperationStatus();
      const recentLogs = await getRecentLogs();

      applyRefreshResult(refreshed);
      if (isMounted.current) {
        setOperation(operationStatus);
        setLogs(recentLogs);
      }
    } catch (error) {
      log("error", `Force ${label} failed: ${error}`, label, selectedGame);
      notify(
        ludusaviStore,
        "failures_errors",
        `SDH-Ludusavi ${label} failed`,
        error instanceof Error ? error.message : String(error),
        <FaExclamationTriangle />
      );
    } finally {
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
        onGameChange={onGameChange}
        onForceBackup={() => void runForceOperation("Backup", forceBackupCall)}
        onForceRestore={() => void runForceOperation("Restore", forceRestoreCall)}
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
      />

      <PluginUpdateSection
        currentVersion={versions.sdh_ludusavi ?? "Unknown"}
        updateChannel={settings.update_channel}
        automaticUpdateChecks={settings.automatic_update_checks}
        onToggleUpdateChannel={toggleUpdateChannel}
        onToggleAutomaticUpdateChecks={toggleAutomaticUpdateChecks}
      />

      <VersionsSection versions={versions} />
    </div>
  );
}
