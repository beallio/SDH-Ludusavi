import {
  showModal,
  Router
} from "@decky/ui";
import {
  definePlugin,
  toaster,
  useQuickAccessVisible
} from "@decky/api";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FaSave, FaDownload, FaExclamationTriangle } from "react-icons/fa";
import { IoMdRefresh } from "react-icons/io";

import {
  backupGameOnExitCall,
  checkGameExitCall,
  checkGameStartCall,
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
  pauseGameProcessCall,
  refreshGamesCall,
  resolveGameStartConflictCall,
  restoreGameOnStartCall,
  resumeGameProcessCall
} from "./api/ludusaviRpc";

import {
  NotificationCategory,
  Settings,
  GameStatus,
  RefreshResult,
  OperationStatus,
  OperationResult,
  ConflictResolution,
  LifecycleCheckResult,
  AppLifetimeNotification,
  RunningSession,
  RpcStatus,
  RpcResult,
  LogEntry
} from "./types";
import { LogModal, LudusaviLogModal } from "./components/LogModal";
import { ConflictResolutionModal } from "./components/modals/ConflictResolutionModal";
import { PluginUpdateSection } from "./components/PluginUpdateSection";
import { AutoSyncSettingsSection } from "./components/qam/AutoSyncSettingsSection";
import { GameSettingsSection } from "./components/qam/GameSettingsSection";
import { LudusaviLauncherSection } from "./components/qam/LudusaviLauncherSection";
import { NotificationSettingsSection } from "./components/qam/NotificationSettingsSection";
import { QamStyles } from "./components/qam/QamStyles";
import { LogsSection, VersionsSection } from "./components/qam/VersionAndLogsSection";
import { summarizeOperationResult } from "./formatting/operationText";
import { log } from "./utils/logging";
import {
  LudusaviStateProvider,
  LudusaviStateStore,
  createLudusaviStateStore,
  defaultSettings,
  useLudusaviState,
  useLudusaviStateStore
} from "./state/ludusaviState";
import {
  applySettingsGlobal,
  clearLastQueuedSelectedGame,
  createSettingsMutationController,
  getSettingsQueueBusy,
  resetSettingsMutationController,
  setActiveSettingsStore,
  subscribeQueue,
  syncLastQueuedSelectedGame
} from "./settings/settingsMutationController";
import {
  completeAutoSyncStatus,
  hideAutoSyncStatus,
  publishAutoSyncStatus,
  resetAutoSyncStatusSurface
} from "./surfaces/autoSyncStatusSurface";
import {
  getInstalledAppIdsString,
  sessionFromAppOverview,
  getMainRunningSession,
  captureSteamUiGameContext,
  getPreferredSteamGameSession,
  findGameForRunningSession,
  logCurrentGameSelection,
  logCurrentGameNoMatch,
  resetQuickAccessScroll
} from "./utils/steam";




async function syncGlobalHistory(store: LudusaviStateStore) {
  try {
    const historyRes = await getGameHistoryCall();
    if (!isRpcStatus(historyRes)) {
      store.setGameHistory(historyRes);
    }
  } catch (err) {
    log("error", `Failed to sync global history: ${err}`);
  }
}




const EMPTY_GAMES: readonly GameStatus[] = Object.freeze([]);

function PluginIcon() {
  return (
    <svg
      viewBox="0 0 1536 1536"
      role="img"
      aria-label="SDH-Ludusavi"
      fill="currentColor"
      width="1em"
      height="1em"
      style={{ display: "block" }}
    >
      <circle cx="191" cy="192" r="71" />
      <circle cx="192" cy="478" r="71" />
      <rect x="120" y="708" width="144" height="707" rx="72" ry="72" />
      <rect x="120" y="1265" width="1332" height="150" rx="75" ry="75" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M496 216H1256C1304.6 216 1344 255.4 1344 304V1064C1344 1112.6 1304.6 1152 1256 1152H496C447.4 1152 408 1112.6 408 1064V304C408 255.4 447.4 216 496 216ZM552 360V1008H1200V360H552Z"
      />
      <circle cx="719" cy="527" r="71" />
      <circle cx="1031" cy="528" r="71" />
      <circle cx="719" cy="840" r="71" />
      <circle cx="1031" cy="840" r="71" />
    </svg>
  );
}






function showConflictResolutionModal(
  conflict: LifecycleCheckResult
): Promise<ConflictResolution | null> {
  return new Promise((resolve) => {
    let settled = false;
    const settle = (resolution: ConflictResolution | null) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(resolution);
    };
    showModal(
      <ConflictResolutionModal
        conflict={conflict}
        onChoose={(resolution) => settle(resolution)}
        onDismiss={() => settle(null)}
      />
    );
  });
}

function notify(
  store: LudusaviStateStore,
  category: NotificationCategory,
  title: string,
  body: string,
  logo?: any
) {
  log("debug", `notify call: category=${category}, title=${title}, body=${body}`, "autosync_status");
  if (!store.shouldShowNotification(category)) {
    log("debug", "notify skipped: disabled by settings", "autosync_status");
    return;
  }
  try {
    const toastObj = { 
      title, 
      body, 
      duration: 3000,
      ...(logo ? { logo } : {})
    };
    toaster.toast(toastObj);
    log("debug", "notify successful: toast dispatched", "autosync_status");
  } catch (err) {
    log("error", `notify failed: ${err}`, "autosync_status");
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

const dropdownStyleEl = document.createElement("style");
dropdownStyleEl.textContent = `
  /*
   * Temporary SteamOS workaround for the QAM dropdown long-name regression.
   * Scoped to prevent broad wildcard descendant side effects on Decky icons.
   * This workaround should be removed via git revert 9b3f9022319c8f628c2a78927f464bbb8d7bfb56 when SteamOS no longer requires it.
   */
  .sdh-ludusavi-game-dropdown {
    width: 100%;
    max-width: 100% !important;
    min-width: 0 !important;
  }
  .sdh-ludusavi-game-dropdown button {
    max-width: 100% !important;
    width: 100% !important;
    min-width: 0 !important;
  }
  .sdh-ludusavi-game-dropdown [class*="DropdownField" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownControl" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownButton" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownMenu" i],
  .sdh-ludusavi-game-dropdown [class*="dropdown" i],
  .sdh-ludusavi-game-dropdown [class*="button" i],
  .sdh-ludusavi-game-dropdown [focusable="true"],
  .sdh-ludusavi-game-dropdown [role="button"],
  .sdh-ludusavi-game-dropdown div {
    max-width: 100% !important;
    min-width: 0 !important;
  }
  .sdh-ludusavi-game-dropdown [class*="DropdownField" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownControl" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownButton" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownMenu" i],
  .sdh-ludusavi-game-dropdown [class*="dropdown" i],
  .sdh-ludusavi-game-dropdown [class*="button" i],
  .sdh-ludusavi-game-dropdown [focusable="true"],
  .sdh-ludusavi-game-dropdown [role="button"] {
    width: 100% !important;
  }
  .sdh-ludusavi-game-dropdown-value {
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    display: inline-block !important;
  }
  .sdh-ludusavi-game-dropdown svg,
  .sdh-ludusavi-game-dropdown [class*="icon" i],
  .sdh-ludusavi-game-dropdown [class*="chevron" i],
  .sdh-ludusavi-game-dropdown [class*="arrow" i] {
    flex-shrink: 0 !important;
    min-width: fit-content !important;
    max-width: none !important;
  }
`;

let activeInitPromise: Promise<OperationStatus> | null = null;
let activeMetadataPromise: Promise<void> | null = null;

function Content() {
  const ludusaviState = useLudusaviState();
  const ludusaviStore = useLudusaviStateStore();
  const isQuickAccessVisible = useQuickAccessVisible();
  const qamContentRef = useRef<HTMLDivElement | null>(null);
  const wasQuickAccessVisible = useRef(false);
  const pendingCurrentGameSelection = useRef(false);
  const isMounted = useRef(true);
  const styleElement = useMemo(
    () => <QamStyles cssText={dropdownStyleEl.textContent} />,
    []
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
    [ludusaviStore]
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
          setBusyLabel((prev) => prev === "Updating settings" ? null : prev);
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
        window.setTimeout(() => resetQuickAccessScroll(qamContentRef.current, `qam_open_retry_${delay}`), delay);
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

    const cacheCurrentResult = isWarmed && !installedAppIdsChanged ? await isGameCacheCurrentCall(installedAppIds) : false;

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

  const applyRefreshResult = (result: RpcResult<RefreshResult>, preferredGame?: string): boolean => {
    if (isRpcStatus(result)) {
      logRpcStatus(result, "refresh");
      return false;
    }

    if (result.dependency_error) {
      log("error", `Ludusavi refresh failed: ${result.dependency_error}`, "refresh");
      notify(ludusaviStore, "failures_errors", "SDH-Ludusavi refresh failed", result.dependency_error, <FaExclamationTriangle />);
      return false;
    }

    log("debug", `Applying refresh result (${result.games.length} games, ${Object.keys(result.aliases || {}).length} aliases)`);
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
        notify(ludusaviStore, "refresh_status", "SDH-Ludusavi", "Ludusavi game status refreshed", <IoMdRefresh />);
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
      const logs = typeof result === "string" ? result : result.message || `Failed to fetch logs: ${result.status}`;
      showModal(<LudusaviLogModal logs={logs} />);
    } catch (error) {
      log("error", `Failed to fetch Ludusavi logs: ${error}`);
      notify(ludusaviStore, "failures_errors", "SDH-Ludusavi", "Failed to fetch Ludusavi logs", <FaExclamationTriangle />);
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
      notify(ludusaviStore, "failures_errors", "SDH-Ludusavi", "Failed to fetch plugin logs", <FaExclamationTriangle />);
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
    notify(ludusaviStore, "manual_operations", `SDH-Ludusavi ${label}`, `${label} started for ${selectedGame}`, icon);
    try {
      const result = await operationCall(selectedGame);
      log("info", `Force ${label} completed: ${JSON.stringify(result)}`, label, selectedGame);
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      const category = result.status === "failed" ? "failures_errors" : "manual_operations";
      notify(ludusaviStore, category, `SDH-Ludusavi ${label}`, summarizeOperationResult(result, label), resultIcon);
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
      notify(ludusaviStore, "failures_errors", `SDH-Ludusavi ${label} failed`, error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
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
};

export default definePlugin(() => {
  console.log("SDH-Ludusavi plugin initializing");

  if (!dropdownStyleEl.parentNode) {
    document.head.appendChild(dropdownStyleEl);
  }

  const ludusaviStore = createLudusaviStateStore();
  setActiveSettingsStore(ludusaviStore, (title, body) => {
    notify(ludusaviStore, "failures_errors", title, body, <FaExclamationTriangle />);
  });
  const activeSessions = new Map<number, RunningSession>();
  let fallbackIntervalID: number | null = null;
  let fallbackPreviousAppID: string | null = null;
  let fallbackPreviousAppName: string | null = null;
  let lifecycleRegistration: unknown = null;

  const isTracked = (name: string, appID: string) => {
    return ludusaviStore.isTracked(
      name,
      appID,
      (reason, detail) => {
        if (reason === "appId") {
          log("debug", `Match found via AppID: ${detail}`);
        } else if (reason === "exact") {
          log("debug", `Match found via exact name: ${detail}`);
        } else if (reason === "substring") {
          log("debug", `Match found via substring: ${detail}`);
        }
      },
      (normalizedInput) => {
        log("debug", `No match for ${name} (${appID}) [normalized: ${normalizedInput}]`);
      }
    );
  };

  function shouldPublishAutoSyncStatusBeforeRpc(store: LudusaviStateStore, tracked: boolean) {
    return store.shouldPublishAutoSyncStatusBeforeRpc(tracked);
  }

  const handleAppStart = async (name: string, appID: string, instanceID?: number) => {
    const tracked = isTracked(name, appID);
    log("info", `App started: ${name} (${appID}) tracked=${tracked}`);
    let paused = false;
    
    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_start",
        gameName: name,
        appID,
        tracked
      });
    }

    try {
      const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
      const shouldPauseLaunch =
        autoSyncEnabled &&
        tracked &&
        typeof instanceID === "number" &&
        instanceID > 1;

      if (shouldPauseLaunch) {
        const pauseResult = await pauseGameProcessCall(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
          paused = true;
        }
      }

      log("info", `Calling check_game_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameStartCall(name, appID);
      log("info", `check_game_start result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      // Show result toast for all outcomes (restored, failed, conflict, or skipped)
      // unless auto-sync is completely disabled, another operation is running,
      // or the game simply isn't managed by Ludusavi (unmatched or ignored).
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        hideAutoSyncStatus({
          source: "hide",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        return;
      }

      if (checkResult.status === "needed" && checkResult.operation === "restore") {
        if (!paused) {
          const result: OperationResult = {
            status: "failed",
            game: name,
            message: "Launch gate unavailable; restore skipped while game is loading."
          };
          completeAutoSyncStatus(result, { gameName: name, appID, tracked });
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
          return;
        }
        publishAutoSyncStatus("restoring", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked
        });
        log("info", `Calling restore_game_on_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
        const result = await restoreGameOnStartCall(name, appID);
        log("info", `restore_game_on_start result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      if (checkResult.status === "conflict") {
        publishAutoSyncStatus("conflict", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        if (!paused) {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", "Launch gate unavailable; conflict resolution skipped while game is loading.", <FaExclamationTriangle />);
          return;
        }
        const resolution = await showConflictResolutionModal(checkResult);
        if (!resolution) {
          completeAutoSyncStatus({ status: "skipped", game: name, reason: "conflict_unresolved" }, { gameName: name, appID, tracked });
          return;
        }
        const result = await resolveGameStartConflictCall(checkResult.game ?? name, appID, resolution);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"), <FaExclamationTriangle />);
      }
    } catch (err) {
      log("error", `App start handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed"
      });
    } finally {
      if (paused && typeof instanceID === "number") {
        try {
          await resumeGameProcessCall(instanceID);
        } catch (err) {
          log("error", `Failed to resume game process ${instanceID}: ${err}`, "lifecycle", name);
        }
      }
      await syncGlobalHistory(ludusaviStore);
    }
  };

  const handleAppExit = async (name: string, appID: string) => {
    const tracked = isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);
    
    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_exit",
        gameName: name,
        appID,
        tracked
      });
    }
    
    try {
      log("info", `Calling check_game_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameExitCall(name, appID);
      log("info", `check_game_exit result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        hideAutoSyncStatus({
          source: "hide",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        return;
      }

      if (checkResult.status === "needed" && checkResult.operation === "backup") {
        publishAutoSyncStatus("backing_up", {
          source: "lifecycle_exit",
          gameName: name,
          appID,
          tracked
        });
        log("info", `Calling backup_game_on_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
        const result = await backupGameOnExitCall(name, appID);
        log("info", `backup_game_on_exit result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"), <FaExclamationTriangle />);
      }
    } catch (err) {
      log("error", `App exit handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed"
      });
    } finally {
      await syncGlobalHistory(ludusaviStore);
    }
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
        void handleAppStart(session.name, session.appID, notification.nInstanceID);
        return;
      }

      activeSessions.delete(notification.nInstanceID);
      const startupSession = activeSessions.get(-1);
      if (startupSession?.appID === session.appID) {
        activeSessions.delete(-1);
      }
      void handleAppExit(session.name, session.appID);
    } catch (err) {
      console.error("SDH-Ludusavi: app lifetime notification failed", err);
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
      console.error("SDH-Ludusavi: watcher loop failed", err);
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
    name: "SDH-Ludusavi",
    titleView: <div className="sdh-ludusavi-title">SDH-Ludusavi</div>,
    content: (
      <LudusaviStateProvider store={ludusaviStore}>
        <Content />
      </LudusaviStateProvider>
    ),
    icon: <PluginIcon />,
    alwaysRender: true,
    onDismount() {
      unregisterLifecycleNotifications();
      if (fallbackIntervalID !== null) {
        window.clearInterval(fallbackIntervalID);
      }
      activeSessions.clear();
      resetAutoSyncStatusSurface();

      if (dropdownStyleEl.parentNode) {
        dropdownStyleEl.parentNode.removeChild(dropdownStyleEl);
      }

      resetSettingsMutationController();
      activeInitPromise = null;
      activeMetadataPromise = null;

      console.log("SDH-Ludusavi unloading");
    },
  };
});
