import { log } from "../utils/logging";
import { registerAppLifetimeNotification, getRouterRunningApps, getRouterMainRunningApp, asRecord } from "../utils/steamRuntime";
import {
  getMainRunningSession,
  sessionFromAppOverview,
} from "../utils/steam";
import type { AppLifetimeNotification, RunningSession } from "../types";

export interface SteamLifecycleObserver {
  onAppStart: (session: RunningSession, instanceId?: number) => Promise<void>;
  onAppExit: (session: RunningSession) => Promise<void>;
}

export function createSteamLifecycleSource(observer: SteamLifecycleObserver) {
  const activeSessions = new Map<number, RunningSession>();
  let fallbackIntervalID: number | null = null;
  let fallbackPreviousAppID: string | null = null;
  let fallbackPreviousAppName: string | null = null;
  let lifecycleRegistration: unknown = null;

  const findRunningSessionByAppID = (appID: string): RunningSession | null => {
    const runningApps = getRouterRunningApps();
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

    return getMainRunningSession();
  };

  const handleLifetimeNotification = (notification: AppLifetimeNotification) => {
    try {
      const session = resolveLifetimeSession(notification);
      if (!session?.name) {
        log(
          "warning",
          `Could not resolve app lifetime notification: ${JSON.stringify(notification)}`,
          "lifecycle",
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
            session.name,
          );
          return;
        }

        if (activeSessions.has(notification.nInstanceID)) {
          log(
            "debug",
            `Duplicate app start ignored for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name,
          );
          return;
        }

        activeSessions.set(notification.nInstanceID, session);
        void observer.onAppStart(session, notification.nInstanceID);
        return;
      }

      activeSessions.delete(notification.nInstanceID);
      const startupSession = activeSessions.get(-1);
      if (startupSession?.appID === session.appID) {
        activeSessions.delete(-1);
      }
      void observer.onAppExit(session);
    } catch (err) {
      console.error("SDH-Ludusavi: app lifetime notification failed", err);
    }
  };

  const checkMainApp = () => {
    try {
      const mainApp = asRecord(getRouterMainRunningApp());
      const currentAppID = mainApp?.appid ? String(mainApp.appid) : null;
      const currentAppName = mainApp?.display_name ? String(mainApp.display_name) : null;

      if (currentAppID !== fallbackPreviousAppID) {
        if (fallbackPreviousAppID && fallbackPreviousAppName) {
          void observer.onAppExit({ appID: fallbackPreviousAppID, name: fallbackPreviousAppName });
        }
        if (currentAppID && currentAppName) {
          void observer.onAppStart({ appID: currentAppID, name: currentAppName });
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
    void observer.onAppStart(session);
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

  function start() {
    const reg = registerAppLifetimeNotification((notificationUnknown: unknown) => {
      const notification = notificationUnknown as AppLifetimeNotification;
      handleLifetimeNotification(notification);
    });
    if (reg) {
      lifecycleRegistration = reg;
      reconcileStartupSession();
    } else {
      startFallbackPolling();
    }
  }

  function dispose() {
    unregisterLifecycleNotifications();
    if (fallbackIntervalID !== null) {
      window.clearInterval(fallbackIntervalID);
      fallbackIntervalID = null;
    }
    activeSessions.clear();
  }

  return {
    start,
    dispose,
  };
}
