import re
from pathlib import Path

# 1. Update src/utils/steam.ts
steam_ts_path = Path("src/utils/steam.ts")
steam_ts_content = steam_ts_path.read_text()

import_stmt = """import {
  getSteamClientApps,
  getRouterMainRunningApp,
  getAppStore,
  getCollectionStoreApps,
  getGamepadMainWindow
} from "./steamRuntime";\n"""
if "getSteamClientApps" not in steam_ts_content:
    steam_ts_content = steam_ts_content.replace(
        'import { log } from "./logging";', 'import { log } from "./logging";\n' + import_stmt
    )

steam_ts_content = re.sub(
    r"const steamClient = \(globalThis as any\)\.SteamClient \?\? \(window as any\)\.SteamClient;\s*if \(\!steamClient\?\.Apps\?\.GetInstalledApps\) {\s*return undefined;\s*}\s*const appsResult = steamClient\.Apps\.GetInstalledApps\(\);",
    r"const apps = getSteamClientApps();\n    if (!apps?.GetInstalledApps) return undefined;\n    const appsResult = apps.GetInstalledApps();",
    steam_ts_content,
    flags=re.DOTALL,
)

steam_ts_content = re.sub(
    r"const session = sessionFromAppOverview\(\(Router as any\)\.MainRunningApp\);",
    r"const session = sessionFromAppOverview(getRouterMainRunningApp());",
    steam_ts_content,
)

steam_ts_content = re.sub(
    r"return \(Router as any\)\.WindowStore\?\.GamepadUIMainWindowInstance\?\.BrowserWindow \?\? null;",
    r"return getGamepadMainWindow();",
    steam_ts_content,
)

steam_ts_content = re.sub(
    r"const appStore = \(globalThis as any\)\.appStore \?\? \(window as any\)\.appStore;",
    r"const appStore = getAppStore();",
    steam_ts_content,
)

steam_ts_content = re.sub(
    r"const collectionApps = \(globalThis as any\)\.collectionStore\?\.allGamesCollection\?\.allApps\s*\?\? \(window as any\)\.collectionStore\?\.allGamesCollection\?\.allApps;",
    r"const collectionApps = getCollectionStoreApps();",
    steam_ts_content,
    flags=re.DOTALL,
)
steam_ts_path.write_text(steam_ts_content)

# 2. Update src/ludusaviLauncher.ts
launcher_path = Path("src/ludusaviLauncher.ts")
launcher_content = launcher_path.read_text()
if "getSteamClientApps" not in launcher_content:
    launcher_content = launcher_content.replace(
        'import { SteamClientGlobal, AppStoreGlobal, SteamGameId } from "./types/steam-globals";',
        'import { SteamClientGlobal, AppStoreGlobal, SteamGameId } from "./types/steam-globals";\nimport { getSteamClientApps } from "./utils/steamRuntime";',
    )
launcher_content = re.sub(
    r"function getSteamClient\(\): SteamClientGlobal \{\s*const client = \(globalThis as any\)\.SteamClient \?\? \(window as any\)\.SteamClient;\s*if \(\!client\?\.Apps\) \{\s*throw new Error\(\"SteamClient\.Apps is unavailable in this frontend context\.\"\);\s*\}\s*return client as SteamClientGlobal;\s*\}",
    r"function getSteamClient(): SteamClientGlobal {\n  const apps = getSteamClientApps();\n  if (!apps) {\n    throw new Error(\"SteamClient.Apps is unavailable in this frontend context.\");\n  }\n  return { Apps: apps } as any;\n}",
    launcher_content,
    flags=re.DOTALL,
)
launcher_path.write_text(launcher_content)

# 3. Update src/shortcutArtwork.ts
shortcut_path = Path("src/shortcutArtwork.ts")
shortcut_content = shortcut_path.read_text()
if "getSteamClientApps" not in shortcut_content:
    shortcut_content = shortcut_content.replace(
        'import { log } from "./utils/logging";',
        'import { log } from "./utils/logging";\nimport { getSteamClientApps } from "./utils/steamRuntime";',
    )
shortcut_content = re.sub(
    r"function getSteamClient\(\): SteamClientGlobal \{\s*const client = \(globalThis as any\)\.SteamClient \?\? \(window as any\)\.SteamClient;\s*if \(\!client\?\.Apps\) \{\s*throw new Error\(\"SteamClient\.Apps is unavailable in this frontend context\.\"\);\s*\}\s*return client as SteamClientGlobal;\s*\}",
    r"function getSteamClient(): SteamClientGlobal {\n  const apps = getSteamClientApps();\n  if (!apps) {\n    throw new Error(\"SteamClient.Apps is unavailable in this frontend context.\");\n  }\n  return { Apps: apps } as any;\n}",
    shortcut_content,
    flags=re.DOTALL,
)
shortcut_path.write_text(shortcut_content)

# 4. Update src/surfaces/autoSyncStatusSurface.tsx
status_path = Path("src/surfaces/autoSyncStatusSurface.tsx")
status_content = status_path.read_text()
if "createBrowserView" not in status_content:
    status_content = status_content.replace(
        'import { log } from "../utils/logging";',
        'import { log } from "../utils/logging";\nimport { createBrowserView, getSteamClientApps } from "../utils/steamRuntime";',
    )
status_content = re.sub(
    r"const steamClient = \(globalThis as any\)\.SteamClient \?\? \(window as any\)\.SteamClient;\s*const view = steamClient\?\.BrowserView\?\.Create\(\);",
    r"const view = createBrowserView();",
    status_content,
    flags=re.DOTALL,
)
status_content = re.sub(
    r"const steamClient = \(globalThis as any\)\.SteamClient \?\? \(window as any\)\.SteamClient;\s*steamClient\?\.BrowserView\?\.Destroy\(browserViewOwner\);",
    r"// No need to fetch SteamClient since we use the owner or global\n      if (browserViewOwner?.Destroy) { browserViewOwner.Destroy(); } else { (globalThis as any).SteamClient?.BrowserView?.Destroy?.(browserViewOwner); }",
    status_content,
    flags=re.DOTALL,
)
status_path.write_text(status_content)

# 5. Update src/controllers/gameLifecycleController.tsx
lifecycle_path = Path("src/controllers/gameLifecycleController.tsx")
if lifecycle_path.exists():
    lifecycle_content = lifecycle_path.read_text()
    if "registerAppLifetimeNotification" not in lifecycle_content:
        lifecycle_content = lifecycle_content.replace(
            'import { log } from "../utils/logging";',
            'import { log } from "../utils/logging";\nimport { registerAppLifetimeNotification } from "../utils/steamRuntime";',
        )
    lifecycle_content = re.sub(
        r"const steamClient = \(globalThis as any\)\.SteamClient \?\? \(window as any\)\.SteamClient;\s*if \(!steamClient\?\.GameSessions\?\.RegisterForAppLifetimeNotifications\) \{\s*log\(\"warning\", \"SteamClient\.GameSessions is unavailable; lifecycle hooks disabled\.\", \"lifecycle\"\);\s*return;\s*\}\s*this\.appLifetimeRegistration = steamClient\.GameSessions\.RegisterForAppLifetimeNotifications\(",
        r"const reg = registerAppLifetimeNotification(",
        lifecycle_content,
        flags=re.DOTALL,
    )
    lifecycle_content = re.sub(
        r"\(app\) => \{\s*this\.onAppLifetimeNotification\(app\);\s*\}\s*\);\s*log\(\"info\", \"Started game lifecycle hooks\", \"lifecycle\"\);",
        r"(app) => {\n        this.onAppLifetimeNotification(app);\n      }\n    );\n    if (reg) {\n      this.appLifetimeRegistration = reg;\n      log(\"info\", \"Started game lifecycle hooks\", \"lifecycle\");\n    } else {\n      log(\"warning\", \"SteamClient.GameSessions is unavailable; lifecycle hooks disabled.\", \"lifecycle\");\n    }",
        lifecycle_content,
        flags=re.DOTALL,
    )
    lifecycle_path.write_text(lifecycle_content)

print("Applied steam runtime boundaries")
