import { describe, expect, it, vi } from "vitest";

const routeMock = vi.hoisted(() => ({
  addPatch: vi.fn((_: string, patch: unknown) => patch),
  removePatch: vi.fn(),
}));

vi.mock("@decky/api", () => ({ routerHook: routeMock }));
vi.mock("@decky/ui", () => ({}));
vi.mock("../ludusaviLauncher", () => ({}));
vi.mock("../utils/steam", () => ({ normalize: (name: string) => name.toLowerCase() }));
vi.mock("../utils/steamRuntime", () => ({
  getAppDetailsForAppID: vi.fn(() => null),
  getAppOverviewForAppID: vi.fn(() => null),
  subscribeToAppDetails: vi.fn(() => () => {}),
}));

import { createLudusaviStateStore } from "../state/ludusaviState";
import { createGameDetailsStatusSurface } from "./gameDetailsStatus";

describe("game details route adapter", () => {
  it("only wraps the verified route shape and removes its exact patch", () => {
    const surface = createGameDetailsStatusSurface(
      createLudusaviStateStore(),
      { registerDetailsOwner: vi.fn() } as any,
    );
    const patch = routeMock.addPatch.mock.calls[0][1] as (route: any) => any;
    const unsupported = { children: { renderFunc: () => "native page" } };

    expect(patch(unsupported).children.renderFunc()).toBe("native page");
    expect(patch({ children: {} })).toEqual({ children: {} });

    surface.dispose();
    expect(routeMock.removePatch).toHaveBeenCalledWith("/library/app/:appid", patch);
  });
});
