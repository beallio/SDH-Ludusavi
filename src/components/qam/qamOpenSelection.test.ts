import { describe, it, expect } from "vitest";
import { resolveQamOpenSelection } from "./qamOpenSelection";

describe("resolveQamOpenSelection", () => {
  it("returns wait when not visible", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: false,
        pendingSelection: true,
        gameCount: 1,
        operationInProgress: false,
      })
    ).toBe("wait");
  });

  it("returns wait when no pending selection", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: true,
        pendingSelection: false,
        gameCount: 1,
        operationInProgress: false,
      })
    ).toBe("wait");
  });

  it("returns wait when no games are present", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: true,
        pendingSelection: true,
        gameCount: 0,
        operationInProgress: false,
      })
    ).toBe("wait");
  });

  it("returns consume when operation is in progress", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: true,
        pendingSelection: true,
        gameCount: 1,
        operationInProgress: true,
      })
    ).toBe("consume");
  });

  it("returns select when visible, pending, games exist, and no operation in progress", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: true,
        pendingSelection: true,
        gameCount: 1,
        operationInProgress: false,
      })
    ).toBe("select");
  });
});
