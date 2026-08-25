import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type PluginDefinition = {
  onDismount(): void;
};

type PluginFactory = () => PluginDefinition;

type StyleElementFake = {
  textContent: string | null;
  parentNode: HeadFake | null;
};

type HeadFake = {
  appendChild(node: StyleElementFake): StyleElementFake;
  removeChild(node: StyleElementFake): StyleElementFake;
};

const mocks = vi.hoisted(() => ({
  pluginFactory: undefined as PluginFactory | undefined,
  lifecycleController: {
    dispose: vi.fn<() => Promise<void>>(),
    start: vi.fn(),
  },
  runtime: {
    dispose: vi.fn(),
    settings: { applySettings: vi.fn() },
    statusSurface: {},
  },
  startupHydration: { dispose: vi.fn(), ready: Promise.resolve() },
  updatePoller: { dispose: vi.fn(), start: vi.fn() },
  log: vi.fn(),
  logUiEvent: vi.fn(),
}));

vi.mock("@decky/api", () => ({
  definePlugin: (factory: PluginFactory) => {
    mocks.pluginFactory = factory;
    return {};
  },
  toaster: { toast: vi.fn() },
}));

vi.mock("@decky/ui", () => ({ showModal: vi.fn() }));
vi.mock("react-icons/fa", () => ({ FaExclamationTriangle: () => null }));
vi.mock("react/jsx-runtime", () => ({ jsx: vi.fn(), jsxs: vi.fn(), Fragment: Symbol("Fragment") }));

vi.mock("./api/ludusaviRpc", () => ({
  backupGameOnExitCall: vi.fn(),
  checkForPluginUpdateCall: vi.fn(),
  checkGameExitCall: vi.fn(),
  checkGameStartCall: vi.fn(),
  getGameHistoryCall: vi.fn(),
  getSettings: vi.fn(),
  getSyncthingActivityCall: vi.fn(),
  getUpdateCheckContextCall: vi.fn(),
  markUpdateNotifiedCall: vi.fn(),
  pauseGameProcessCall: vi.fn(),
  refreshGamesCall: vi.fn(),
  renewGameProcessPauseCall: vi.fn(),
  resolveGameStartConflictCall: vi.fn(),
  restoreGameOnStartCall: vi.fn(),
  resumeGameProcessCall: vi.fn(),
  startSyncthingActivityWatchCall: vi.fn(),
  stopSyncthingActivityWatchCall: vi.fn(),
}));
vi.mock("./components/qam/LudusaviContent", () => ({ LudusaviContent: () => null }));
vi.mock("./controllers/gameLifecycleController", () => ({
  createGameLifecycleController: () => mocks.lifecycleController,
}));
vi.mock("./runtime/pluginRuntime", () => ({ createPluginRuntime: () => mocks.runtime }));
vi.mock("./runtime/startupHydration", () => ({
  createStartupHydration: () => mocks.startupHydration,
}));
vi.mock("./runtime/updatePoller", () => ({ createUpdatePoller: () => mocks.updatePoller }));
vi.mock("./state/ludusaviState", () => ({
  LudusaviStateProvider: () => null,
  createLudusaviStateStore: () => ({
    applyRefreshResult: vi.fn(),
    getSnapshot: () => ({ settings: null }),
    hydrateDisplayedGame: vi.fn(),
    markTrackingFailed: vi.fn(),
  }),
}));
vi.mock("./utils/logging", () => ({ log: mocks.log, logUiEvent: mocks.logUiEvent }));
vi.mock("./utils/rpc", () => ({ isRpcStatus: vi.fn() }));
vi.mock("./utils/steam", () => ({ getInstalledAppIdsString: vi.fn() }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

async function loadPlugin(): Promise<PluginDefinition> {
  vi.resetModules();
  mocks.pluginFactory = undefined;
  await import("./index");
  const pluginFactory = mocks.pluginFactory as PluginFactory | undefined;
  if (!pluginFactory) {
    throw new Error("definePlugin did not receive the plugin factory");
  }
  return pluginFactory();
}

describe("plugin dismount", () => {
  let head: HeadFake;
  let style: StyleElementFake;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.lifecycleController.dispose.mockResolvedValue(undefined);
    style = { textContent: "", parentNode: null };
    head = {
      appendChild(node) {
        node.parentNode = head;
        return node;
      },
      removeChild: vi.fn((node: StyleElementFake) => {
        node.parentNode = null;
        return node;
      }),
    };
    vi.stubGlobal("document", {
      createElement: vi.fn(() => style),
      head,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("defers runtime and stylesheet cleanup while lease release is pending", async () => {
    const lifecycleDispose = deferred<void>();
    mocks.lifecycleController.dispose.mockReturnValue(lifecycleDispose.promise);
    const plugin = await loadPlugin();

    plugin.onDismount();

    expect(mocks.runtime.dispose).not.toHaveBeenCalled();
    expect(head.removeChild).not.toHaveBeenCalled();
  });

  it("cleans up once when lease release resolves before the timeout", async () => {
    const lifecycleDispose = deferred<void>();
    mocks.lifecycleController.dispose.mockReturnValue(lifecycleDispose.promise);
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
    const plugin = await loadPlugin();

    plugin.onDismount();
    lifecycleDispose.resolve();
    await Promise.resolve();

    expect(clearTimeoutSpy).toHaveBeenCalledOnce();
    expect(mocks.runtime.dispose).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledWith(style);
  });

  it("logs and cleans up once when lease release rejects", async () => {
    const lifecycleDispose = deferred<void>();
    mocks.lifecycleController.dispose.mockReturnValue(lifecycleDispose.promise);
    const plugin = await loadPlugin();

    plugin.onDismount();
    lifecycleDispose.reject(new Error("lease release failed"));
    await Promise.resolve();

    expect(mocks.log).toHaveBeenCalledWith(
      "error",
      expect.stringContaining("lease release failed"),
    );
    expect(mocks.runtime.dispose).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledWith(style);
  });

  it("uses the 2000 ms timeout when lease release never resolves", async () => {
    const lifecycleDispose = deferred<void>();
    mocks.lifecycleController.dispose.mockReturnValue(lifecycleDispose.promise);
    const plugin = await loadPlugin();

    plugin.onDismount();
    await vi.advanceTimersByTimeAsync(2000);

    expect(mocks.log).toHaveBeenCalledWith(
      "warning",
      expect.stringContaining("2000 ms"),
    );
    expect(mocks.runtime.dispose).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledWith(style);
  });

  it("does not clean up twice when lease release resolves after the timeout", async () => {
    const lifecycleDispose = deferred<void>();
    mocks.lifecycleController.dispose.mockReturnValue(lifecycleDispose.promise);
    const plugin = await loadPlugin();

    plugin.onDismount();
    await vi.advanceTimersByTimeAsync(2000);
    lifecycleDispose.resolve();
    await Promise.resolve();

    expect(mocks.runtime.dispose).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledOnce();
    expect(head.removeChild).toHaveBeenCalledWith(style);
  });
});
