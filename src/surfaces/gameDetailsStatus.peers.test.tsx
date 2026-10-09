import { act, cloneElement, createContext, createElement, forwardRef, memo, useContext, useImperativeHandle, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { parseHTML } from "linkedom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createReactTreePatcher } from "../../node_modules/@decky/ui/src/utils/react/treepatcher";
import { findInReactTree } from "../../node_modules/@decky/ui/src/utils/react/react";

const routeMock = vi.hoisted(() => {
  // These real Decky utilities require Steam's browser globals at import time.
  // Their hook-stubbing helpers are not used: React mounts every fixture normally.
  vi.stubGlobal("window", { SP_REACT: {
    __SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED: { ReactCurrentDispatcher: { current: {} } },
  } });
  return { addPatch: vi.fn((_: string, patch: unknown) => patch), removePatch: vi.fn() };
});
vi.mock("@decky/api", () => ({ routerHook: routeMock }));
vi.mock("@decky/ui", () => ({}));
vi.mock("../utils/logging", () => ({ log: vi.fn() }));
vi.mock("../utils/steam", () => ({ normalize: (name: string) => name.toLowerCase(), sessionFromAppOverview: () => null }));
vi.mock("../utils/steamRuntime", () => ({ getAppDetailsForAppID: () => null, getAppOverviewForAppID: () => null, getGamepadMainWindow: () => null, subscribeToAppDetails: () => () => {} }));
import { createLudusaviStateStore } from "../state/ludusaviState";
import { createAutoSyncStatusSurface } from "./autoSyncStatusSurface";
import { createGameDetailsStatusSurface } from "./gameDetailsStatus";

type DispatcherProps = { appID: string; revision: string; renderFunc: (args: { params: { appid: string } }) => ReactNode };
type Route = { path: string; children: ReactElement<DispatcherProps> };
type RoutePatch = (route: Route) => Route;
type BodyProps = { overview: { appid: number }; details: { nPlaytimeForever: number }; revision: string };
let root: Root;
let host: HTMLElement;
let nextInstance: number;
const cleanup: Array<() => void> = [];

beforeEach(() => {
  vi.clearAllMocks();
  const dom = parseHTML("<html><body><main></main></body></html>");
  vi.stubGlobal("window", dom.window); vi.stubGlobal("document", dom.document);
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = dom.document.querySelector("main") as HTMLElement;
  root = createRoot(host);
  nextInstance = 0;
});
afterEach(async () => {
  await act(async () => root.unmount());
  cleanup.splice(0).forEach(dispose => dispose());
  const retained = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
  if (retained?.removalTimer != null) clearTimeout(retained.removalTimer);
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRoutePatch");
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRegistry");
  vi.unstubAllGlobals();
});
const render = async (element: ReactElement) => { await act(async () => root.render(element)); };
function createSurface() {
  const store = createLudusaviStateStore();
  const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
  const status = createAutoSyncStatusSurface(view, store);
  const surface = createGameDetailsStatusSurface(store, status);
  cleanup.push(() => { surface.dispose(); status.dispose(); });
  return { store, view, status, patch: routeMock.addPatch.mock.calls.at(-1)?.[1] as RoutePatch };
}
function NativeDispatcher({ appID, revision, renderFunc }: DispatcherProps) {
  const [instance] = useState(() => ++nextInstance);
  return createElement("article", { "data-instance": instance },
    createElement("output", { "data-revision": true }, revision), renderFunc({ params: { appid: appID } }));
}
function createNativeRoute() {
  const context = createContext<unknown>(null);
  const Body = memo(function Body({ details, revision }: BodyProps) {
    const header = useContext(context);
    return createElement("div", { className: "peer-inner-container" }, [
      createElement("output", { key: "playtime", "data-playtime": true }, details.nPlaytimeForever),
      createElement("span", { key: "revision", "data-body-revision": true }, revision),
      typeof header === "function" ? createElement(header as () => ReactNode, { key: "header" }) : null,
    ]);
  });
  const nativeHeader = () => createElement("span", { "data-native-header": true }, "Native header");
  return (revision = "first", appID = "100", header: unknown = nativeHeader): Route => ({
    path: "/library/app/:appid",
    // Decky supplies a new forwarding function to the first route patch on every replay.
    children: createElement((props: DispatcherProps) => createElement(NativeDispatcher, props), {
      appID, revision,
      renderFunc: ({ params }) => createElement(context.Provider, { value: header }, {
        ...createElement(Body, { overview: { appid: Number(params.appid) }, details: { nPlaytimeForever: -999 }, revision }),
      }),
    }),
  });
}
function createPeerPatch(): RoutePatch {
  // Use Decky's real two-stage patcher. The selected component must render the
  // native insertion container; copying overview onto an SDH wrapper is not enough.
  const patchRenderedBody = createReactTreePatcher([
    tree => findInReactTree(tree, node => node?.props?.children?.props?.overview)?.props?.children,
  ], (_args, output) => {
    const container = findInReactTree(output, node => node?.props?.className === "peer-inner-container");
    if (container) container.props.children.push(createElement("span", { key: "stats", "data-hltb-stats": true }, "Real peer insertion"));
    return output;
  });
  return route => {
    const child = route.children;
    return { ...route, children: cloneElement(child, {
      renderFunc: (args: Parameters<DispatcherProps["renderFunc"]>[0]) => {
        const rendered = child.props.renderFunc(args) as ReactElement<{ children: ReactElement<BodyProps> }>;
        // Steam's production elements are mutable; React's development elements are frozen.
        const result = { ...rendered, props: { ...rendered.props, children: { ...rendered.props.children } } };
        // PlayTime's direct Provider-child access must still update the native body.
        result.props.children.props.details.nPlaytimeForever = 42;
        return patchRenderedBody([args], result);
      },
    }) };
  };
}

it.each(["sdh-first", "peer-first"])("renders HLTB insertion and PlayTime updates in %s order", async order => {
  const { patch } = createSurface();
  const native = createNativeRoute()();
  const peer = createPeerPatch();
  const route = order === "sdh-first" ? peer(patch(native)) : patch(peer(native));
  await render(route.children);
  expect(host.querySelector("[data-hltb-stats]")?.textContent).toBe("Real peer insertion");
  expect(host.querySelector("[data-playtime]")?.textContent).toBe("42");
  expect(host.querySelector("[data-native-header]")?.textContent).toBe("Native header");
});

it("preserves mounted dispatcher state while using fresh peer callbacks and native props", async () => {
  const { patch, status, store, view } = createSurface();
  const native = createNativeRoute();
  const peer = createPeerPatch();
  await render(peer(patch(native())).children);
  const instance = host.querySelector("article");
  await act(async () => status.publish("backing_up", { source: "lifecycle_exit", lifecycle: "lifecycle_exit", appID: "100", generation: 1, gameName: "Fixture", tracked: true }));
  const observation = store.getSnapshot().autoSyncObservations["100"];
  for (const revision of ["second", "third"]) {
    await render(peer(patch(native(revision))).children);
    expect(host.querySelector("article")).toBe(instance);
    expect(host.querySelector("[data-revision]")?.textContent).toBe(revision);
    expect(host.querySelector("[data-body-revision]")?.textContent).toBe(revision);
    expect(host.querySelector("[data-hltb-stats]")?.textContent).toBe("Real peer insertion");
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
    expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);
  }
  await render(peer(patch(native("other game", "101"))).children);
  expect(host.querySelector("article")).toBe(instance);
  expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));
  await render(peer(patch(native("return", "100"))).children);
  expect(host.querySelector("article")).toBe(instance);
  expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
  expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);
});

it("keeps the native provider child readable with an unsupported header value", async () => {
  const { patch, status, view } = createSurface();
  await render(createPeerPatch()(patch(createNativeRoute()("unsupported", "100", null))).children);
  expect(host.querySelector("[data-hltb-stats]")?.textContent).toBe("Real peer insertion");
  await act(async () => status.publish("backing_up", { source: "lifecycle_exit", lifecycle: "lifecycle_exit", appID: "100", generation: 1, gameName: "Fixture", tracked: true }));
  expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
});

it("forwards native refs and reseeds the delegated type on an explicit route-key change", async () => {
  const { patch } = createSurface();
  type Handle = { instance: number };
  const Native = forwardRef<Handle, DispatcherProps>(function Native({ revision, renderFunc, appID }, ref) {
    const [instance] = useState(() => ++nextInstance);
    useImperativeHandle(ref, () => ({ instance }), [instance]);
    return createElement("output", { "data-ref-native": true }, revision, renderFunc({ params: { appid: appID } }));
  });
  const Replacement = forwardRef<Handle, DispatcherProps>(function Replacement({ revision }, ref) {
    const [instance] = useState(() => ++nextInstance);
    useImperativeHandle(ref, () => ({ instance }), [instance]);
    return createElement("output", { "data-replacement-native": true }, `Replacement: ${revision}`);
  });
  const refs = [vi.fn(), vi.fn()];
  const route = (key: string, ref: typeof refs[number], revision: string, type = Native): Route => ({
    path: "/library/app/:appid", children: createElement(type, {
      key, ref, revision, appID: "100", renderFunc: () => createElement("span", null, "Native body"),
    }),
  });
  await render(patch(route("first", refs[0], "first")).children);
  const first = refs[0].mock.calls.at(-1)?.[0] as Handle;
  await render(patch(route("first", refs[1], "second")).children);
  expect(refs[0]).toHaveBeenLastCalledWith(null);
  expect(refs[1]).toHaveBeenLastCalledWith(first);
  expect(host.querySelector("[data-ref-native]")?.textContent).toBe("secondNative body");
  await render(patch(route("second", refs[1], "new key", Replacement)).children);
  expect((refs[1].mock.calls.at(-1)?.[0] as Handle).instance).not.toBe(first.instance);
  expect(host.querySelector("[data-replacement-native]")?.textContent).toBe("Replacement: new key");
  expect(host.querySelector("[data-ref-native]")).toBeNull();
});

it("adopts the replacement route on a manual Home and return without redrawing the open page", async () => {
  const native = createNativeRoute();
  await render(native().children);
  const openPage = host.querySelector("article");
  const priorPatch = vi.fn(route => route);
  globalThis.__sdhLudusaviGameDetailsStatusRoutePatch = {
    version: 0, patch: priorPatch, installedPatch: priorPatch, removalTimer: null,
  };
  const { patch, status, view, store } = createSurface();
  await act(async () => status.publish("backing_up", {
    source: "lifecycle_exit", lifecycle: "lifecycle_exit", appID: "100",
    generation: 1, gameName: "Fixture", tracked: true,
  }));
  const observation = store.getSnapshot().autoSyncObservations["100"];
  expect(host.querySelector("article")).toBe(openPage);
  expect(host.querySelector("[data-hltb-stats]")).toBeNull();
  expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));
  await render(createElement("main", null, "Home"));
  await render(createPeerPatch()(patch(native())).children);
  expect(host.querySelector("[data-hltb-stats]")?.textContent).toBe("Real peer insertion");
  expect(host.querySelector("[data-playtime]")?.textContent).toBe("42");
  expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
  expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);
});
