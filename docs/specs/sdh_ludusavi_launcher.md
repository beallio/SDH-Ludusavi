# Feature Spec: Launch Ludusavi via Hidden Reusable Steam Shortcut

## Objective

Implement a Decky plugin feature that launches **Ludusavi** from a button labeled:

> Launch

The button must appear inside a dedicated panel labeled:

> Ludusavi

The `Ludusavi` panel must be placed **above the Logs panel** in the plugin UI.

The launch mechanism should use the same general approach as SDH-QuickLaunch:

1. Create a reusable Steam non-Steam shortcut.
2. Hide that shortcut from the Steam library if the runtime supports it.
3. Save the shortcut app ID in plugin configuration.
4. Reuse the shortcut on later launches.
5. Before each launch, rewrite the shortcut executable, launch options, display name, and compatibility tool.
6. Ask Steam to launch the shortcut through `SteamClient.Apps.RunGame`.

This feature is for **one fixed application only: Ludusavi**.

The Ludusavi command will be supplied by the host plugin integrating this feature. The feature should not discover Ludusavi itself.

---

## Non-Goals

This feature must not:

- Add a visible Ludusavi shortcut to the Steam library.
- Create a new shortcut every time the button is pressed.
- Search for Ludusavi installations.
- Parse `.desktop` files.
- Manage multiple applications.
- Provide a general-purpose command launcher UI.
- Launch Ludusavi directly from the Python backend.
- Require the user to manually configure a Steam shortcut ID.
- Require explicit QAM dismissal for correctness.

---

## User-Facing Behavior

### Panel Placement

The plugin UI must include a separate panel labeled:

```text
Ludusavi
```

This panel must be placed **above the Logs panel**.

Example UI order:

```text
Ludusavi
Logs
```

If the plugin already contains multiple panels, insert the `Ludusavi` panel immediately before the existing `Logs` panel.

### Button

Inside the `Ludusavi` panel, add a button labeled:

```text
Launch
```

When pressed, the plugin should launch Ludusavi using the hidden reusable Steam shortcut.

### Expected UX

On first launch:

1. The user opens the plugin UI.
2. The user sees a `Ludusavi` panel above the `Logs` panel.
3. The user presses `Launch`.
4. The plugin creates a hidden reusable Steam shortcut.
5. The plugin saves the Steam shortcut app ID.
6. The plugin rewrites the shortcut to point to Ludusavi.
7. The plugin launches Ludusavi through Steam.

On later launches:

1. The user presses `Launch`.
2. The plugin reads the saved shortcut app ID.
3. The plugin validates that the shortcut still exists.
4. If it exists, the plugin reuses it.
5. If it does not exist, the plugin creates a new hidden shortcut and saves the new ID.
6. The plugin rewrites the shortcut to point to Ludusavi.
7. The plugin launches Ludusavi through Steam.

---

## QAM Behavior After Launch

When the user presses `Launch`, the plugin should:

1. Disable the launch button temporarily or show a transient `Launching Ludusavi...` status.
2. Ensure the hidden reusable Steam shortcut exists.
3. Rewrite the shortcut to point to Ludusavi.
4. Call `SteamClient.Apps.RunGame(...)`.

The feature should not require explicit QAM dismissal for correctness.

The plugin may optionally attempt to close or dismiss the QAM after dispatching the launch request, but this must be treated as **best-effort** because Steam and Decky UI internals can vary across SteamOS and Decky versions.

Failure to close the QAM must not be treated as a launch failure.

The required behavior is:

```text
User opens QAM
  -> user opens plugin panel
  -> user presses "Launch"
  -> plugin calls SteamClient.Apps.RunGame(...)
  -> Steam begins launching Ludusavi
  -> QAM transition/focus behavior is handled by Steam/Gaming Mode
```

---

## Inputs Provided by Host Plugin

The integrating plugin must provide the Ludusavi launch command.

Use this internal model:

```ts
export type LudusaviLaunchCommand = {
  commandPath: string;
  args?: string[];
  compatTool?: string;
};
```

Example Flatpak-based command:

```ts
const ludusaviCommand: LudusaviLaunchCommand = {
  commandPath: "/usr/bin/flatpak",
  args: ["run", "com.github.mtkennerly.ludusavi"],
  compatTool: "",
};
```

Example native binary command:

```ts
const ludusaviCommand: LudusaviLaunchCommand = {
  commandPath: "/home/deck/.local/bin/ludusavi",
  args: [],
  compatTool: "",
};
```

The feature must not hardcode the command path unless the host plugin explicitly chooses to do so.

---

## Persistent Configuration

The feature must persist the reusable Steam shortcut app ID.

Store this value:

```ts
launcherShortcutAppId: number
```

Do not persist only the Steam game ID.

Reason:

* Shortcut mutation APIs use the Steam shortcut **app ID**.
* `RunGame()` requires the Steam **game ID**.
* The game ID should be resolved from the app ID immediately before launching.

Recommended config shape:

```json
{
  "ludusaviLauncherShortcutAppId": 123456789
}
```

The config should live in the Decky plugin settings directory.

---

## Backend Requirements

The Python backend must expose methods for reading, writing, and clearing the saved shortcut app ID.

### Required Methods

```python
async def get_ludusavi_launcher_shortcut_id(self) -> int
```

Returns the saved shortcut app ID, or `-1` if none exists.

```python
async def set_ludusavi_launcher_shortcut_id(self, app_id: int) -> bool
```

Persists the shortcut app ID.

```python
async def clear_ludusavi_launcher_shortcut_id(self) -> bool
```

Removes the saved shortcut app ID from config.

---

## Frontend Requirements

### Constants

Use a stable hidden shortcut name.

```ts
const LUDUSAVI_SHORTCUT_NAME = "[Plugin] Ludusavi Launcher";
const LUDUSAVI_RUNNING_NAME = "[Plugin] Ludusavi";
const PLACEHOLDER_EXE = "/usr/bin/ifyouseethisyoufoundabug";
```

The placeholder executable is only used during initial shortcut creation. It will be replaced before launching Ludusavi.

---

## Type Definitions

```ts
export type LudusaviLaunchCommand = {
  commandPath: string;
  args?: string[];
  compatTool?: string;
};

export type LauncherShortcutState = {
  appId: number;
  gameId: string;
};
```

---

## Steam Helper Implementation

Create a frontend helper module, for example:

```text
src/ludusaviLauncher.ts
```

### Required Helper Functions

```ts
import { ServerAPI } from "decky-frontend-lib";

export type LudusaviLaunchCommand = {
  commandPath: string;
  args?: string[];
  compatTool?: string;
};

export type LauncherShortcutState = {
  appId: number;
  gameId: string;
};

const LUDUSAVI_SHORTCUT_NAME = "[Plugin] Ludusavi Launcher";
const LUDUSAVI_RUNNING_NAME = "[Plugin] Ludusavi";
const PLACEHOLDER_EXE = "/usr/bin/ifyouseethisyoufoundabug";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function quoteExe(path: string): string {
  const trimmed = path.trim();

  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    return trimmed;
  }

  return `"${trimmed.replaceAll('"', '\\"')}"`;
}

function escapeLaunchArg(arg: string): string {
  if (/^[A-Za-z0-9_./:=@%+-]+$/.test(arg)) {
    return arg;
  }

  return `"${arg.replaceAll('"', '\\"')}"`;
}

function buildLaunchOptions(args?: string[]): string {
  if (!args || args.length === 0) {
    return "";
  }

  return args.map(escapeLaunchArg).join(" ");
}

async function getSavedShortcutAppId(serverAPI: ServerAPI): Promise<number> {
  const result = await serverAPI.callPluginMethod<{}, number>(
    "get_ludusavi_launcher_shortcut_id",
    {}
  );

  if (!result.success || typeof result.result !== "number") {
    return -1;
  }

  return result.result;
}

async function saveShortcutAppId(
  serverAPI: ServerAPI,
  appId: number
): Promise<void> {
  await serverAPI.callPluginMethod("set_ludusavi_launcher_shortcut_id", {
    app_id: appId,
  });
}

function getGameIdFromAppId(appId: number): string | null {
  const store = getAppStore();
  const overview = store.GetAppOverviewByAppID(appId);

  if (!overview || !overview.m_gameid) {
    return null;
  }

  return overview.m_gameid;
}

async function hideShortcutIfSupported(
  appId: number,
  gameId: string
): Promise<void> {
  const steamClient = getSteamClient();

  try {
    if (typeof steamClient.Apps.SetAppHidden === "function") {
      steamClient.Apps.SetAppHidden(gameId, true);
      return;
    }

    if (typeof steamClient.Apps.SetShortcutHidden === "function") {
      steamClient.Apps.SetShortcutHidden(appId, true);
      return;
    }

    if (typeof steamClient.Apps.SetHidden === "function") {
      steamClient.Apps.SetHidden(gameId, true);
      return;
    }

    console.warn("No supported SteamClient hide method found.");
  } catch (err) {
    console.warn("Failed to hide Ludusavi launcher shortcut:", err);
  }
}

async function createHiddenLudusaviShortcut(
  serverAPI: ServerAPI
): Promise<LauncherShortcutState> {
  const steamClient = getSteamClient();
  const appId: number = await steamClient.Apps.AddShortcut(
    LUDUSAVI_SHORTCUT_NAME,
    PLACEHOLDER_EXE,
    "",
    ""
  );

  await saveShortcutAppId(serverAPI, appId);

  await sleep(500);

  const gameId = getGameIdFromAppId(appId);

  if (!gameId) {
    throw new Error(
      `Created Ludusavi launcher shortcut ${appId}, but could not resolve game ID.`
    );
  }

  await hideShortcutIfSupported(appId, gameId);

  return {
    appId,
    gameId,
  };
}

async function ensureLudusaviShortcut(
  serverAPI: ServerAPI
): Promise<LauncherShortcutState> {
  const savedAppId = await getSavedShortcutAppId(serverAPI);

  if (savedAppId > 0) {
    const gameId = getGameIdFromAppId(savedAppId);

    if (gameId) {
      await hideShortcutIfSupported(savedAppId, gameId);

      return {
        appId: savedAppId,
        gameId,
      };
    }

    console.warn(
      `Saved Ludusavi launcher shortcut ${savedAppId} no longer exists. Recreating.`
    );
  }

  return await createHiddenLudusaviShortcut(serverAPI);
}

export async function launchLudusavi(
  serverAPI: ServerAPI,
  command: LudusaviLaunchCommand
): Promise<void> {
  if (!command.commandPath || !command.commandPath.trim()) {
    throw new Error("Ludusavi commandPath is required.");
  }

  const { appId } = await ensureLudusaviShortcut(serverAPI);

  const launchOptions = buildLaunchOptions(command.args);
  const exe = quoteExe(command.commandPath);
  const compatTool = command.compatTool ?? "";

  const steamClient = getSteamClient();

  steamClient.Apps.SetShortcutName(appId, LUDUSAVI_RUNNING_NAME);
  steamClient.Apps.SetShortcutExe(appId, exe);
  steamClient.Apps.SetShortcutLaunchOptions(appId, launchOptions);
  steamClient.Apps.SpecifyCompatTool(appId, compatTool);

  await sleep(500);

  const refreshedGameId = getGameIdFromAppId(appId);

  if (!refreshedGameId) {
    throw new Error(`Could not resolve game ID for Ludusavi shortcut ${appId}.`);
  }

  await hideShortcutIfSupported(appId, refreshedGameId);

  steamClient.Apps.RunGame(refreshedGameId, "", -1, 100);
}
```

---

## Steam Frontend Globals

This feature relies on Steam Deck frontend globals that exist at runtime in the Steam/Decky browser context:

- `SteamClient`
- `appStore`

These are not ordinary imports from `decky-frontend-lib` / `@decky/api` / `@decky/ui`.

The implementation must provide local TypeScript ambient declarations for only the subset of these globals used by this feature. Do not scatter `// @ts-ignore` throughout the launcher code.

Create:

```text
src/types/steam-globals.d.ts
```

with declarations similar to:

```ts
export {};

declare global {
  const SteamClient: SteamClientGlobal | undefined;
  const appStore: AppStoreGlobal | undefined;

  interface Window {
    SteamClient?: SteamClientGlobal;
    appStore?: AppStoreGlobal;
  }
}

type SteamGameId = string;

interface SteamClientGlobal {
  Apps: {
    AddShortcut(
      name: string,
      exe: string,
      startDir: string,
      launchOptions: string
    ): number | Promise<number>;

    SetShortcutName(appId: number, name: string): void;
    SetShortcutExe(appId: number, exe: string): void;
    SetShortcutLaunchOptions(appId: number, launchOptions: string): void;
    SpecifyCompatTool(appId: number, compatTool: string): void;

    RunGame(
      gameId: SteamGameId,
      launchOptions: string,
      unknownA: number,
      unknownB: number
    ): void;

    SetAppHidden?: (gameId: SteamGameId, hidden: boolean) => void;
    SetShortcutHidden?: (appId: number, hidden: boolean) => void;
    SetHidden?: (gameId: SteamGameId, hidden: boolean) => void;
  };
}

interface AppStoreGlobal {
  GetAppOverviewByAppID(appId: number): SteamAppOverview | null | undefined;
}

interface SteamAppOverview {
  m_gameid?: SteamGameId;
}
```

Then use runtime guards before touching the globals:

```ts
function getSteamClient(): SteamClientGlobal {
  const client = globalThis.SteamClient ?? window.SteamClient;

  if (!client?.Apps) {
    throw new Error("SteamClient.Apps is unavailable in this frontend context.");
  }

  return client;
}

function getAppStore(): AppStoreGlobal {
  const store = globalThis.appStore ?? window.appStore;

  if (!store?.GetAppOverviewByAppID) {
    throw new Error("appStore.GetAppOverviewByAppID is unavailable in this frontend context.");
  }

  return store;
}
```

Then the launcher code should use:

```ts
const steamClient = getSteamClient();
const store = getAppStore();

const overview = store.GetAppOverviewByAppID(appId);
steamClient.Apps.RunGame(overview.m_gameid, "", -1, 100);
```

---

## Two-Era Game Launch Gate

Tracked game launches use different gate mechanisms before and after Steam creates the
application scope:

- **Era 1 (pre-scope):** The App-started notification identifies the bootstrap PID before
  it has forked. The backend sends `SIGSTOP`, verifies that every
  `/proc/<pid>/task/*/stat` reports state `T`, verifies that every
  `/proc/<pid>/task/*/children` file is empty, and holds that PID stopped while conflict
  resolution runs. This is a complete gate because no process tree exists yet.
- **Era 2 (post-scope):** If the PID is already in an exact
  `app-steam-app<id>-<pid>.scope`, the backend freezes and verifies that cgroup before it
  sends `SIGCONT` to the bootstrap PID. The cgroup freeze covers processes that join the
  scope later.

The application scope cannot be created while the bootstrap PID is stopped: Steam's
reaper must run before it can fork the runtime and create the scope. Waiting for the scope
while holding `SIGSTOP` is therefore a deadlock, not a timeout-tuning problem. The
pre-scope path must make one discovery attempt and retain the `SIGSTOP` gate when discovery
reports that the exact scope is not ready.

### SIGSTOP delivery timing

`os.kill(pid, SIGSTOP)` returns when the signal has been queued, before the target
necessarily reaches stopped state `T`. Steam Deck measurements on 2026-07-15 observed
delivery in 0.16-0.87ms, including a child under continuous `fsync` I/O load. The era-1
gate therefore polls process state for up to a named 100ms production bound. The transition
normally converges; if it does not, acquisition fails closed and reports the last observed
state. The bound is a generous tunable default based on device evidence, not proof that
scheduler sleep cannot overshoot under load.

This state wait is categorically different from waiting for the Steam app scope. `SIGSTOP`
**causes** the state-`T` transition, so waiting for delivery normally converges. `SIGSTOP`
**prevents** the stopped reaper from creating the Steam scope, so retrying scope discovery
would restore the original deadlock. The pre-scope path performs exactly one discovery
attempt.

Only uppercase `T` is accepted. Lowercase `t` is a ptrace stop that the plugin does not own;
a tracer can suppress or reinject the pending stop signal. Every thread must report `T`, not
just the thread-group leader, because a sibling that is still running could fork during the
delivery window. Synthetic `/proc` fixtures model state transitions deterministically but
cannot reproduce kernel scheduling, so Linux integration tests also stop real single- and
multi-threaded child processes and verify the production `/proc` waiter.

The pre-scope safety checks have deliberate limits:

- `/proc/<pid>/task/*/children` exposes first-level children only. A child that double-forks
  and exits inside the sub-millisecond delivery window could reparent a grandchild out of
  view. The all-task child scan remains a fail-closed best-effort check; this accepted edge
  does not justify weakening it.
- A plugin-owned freezeable cgroup was considered and rejected. Steam relocates the reaper
  into `app-steam-app<id>-<pid>.scope` moments later, so a plugin cgroup would conflict with
  Steam's placement.
- Stop-only leases retain `(pid, owner uid, start ticks)` and re-verify that identity for
  verification, renewal, and `SIGCONT` release. A full pidfd migration remains separate
  work. In particular, PID reuse between initial identity capture and the first `SIGSTOP`
  is a pre-existing signalling hole not addressed by this gate-delivery fix.

Device evidence from three launches on 2026-07-14 shows that scope creation follows
`SIGCONT`, not App-started:

| Launch | App started | SIGCONT (gate gives up) | Scope created | After app-start | After SIGCONT |
|---|---|---|---|---|---|
| 19:45 (pid 4099) | 57.346 | 57.349 (~3ms hold) | 57.356 | +10ms | +7ms |
| 22:13 (pid 5334) | 10.435 | 10.937 (~502ms hold) | 10.991 | +556ms | +54ms |
| 22:21 (pid 6074) | 19.498 | 19.999 (~501ms hold) | 20.052 | +554ms | +53ms |

Both gate types use renewable leases. Immediately before a conflict choice restores files
into the game's save directory, the backend must verify that the exact lease is unexpired
and that its gate is still held. A missing, mismatched, expired, resumed, or thawed gate
fails closed with `gate_lost`; keeping the local save does not require this restore-side
check because that path copies saves outward.
