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
        explicitSelectionPending: false,
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
        explicitSelectionPending: false,
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
        explicitSelectionPending: false,
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
        explicitSelectionPending: false,
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
        explicitSelectionPending: false,
      })
    ).toBe("select");
  });

  it("returns consume when an explicit selection is pending", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: true,
        pendingSelection: true,
        gameCount: 1,
        operationInProgress: false,
        explicitSelectionPending: true,
      })
    ).toBe("consume");
  });

  it("returns wait while hidden even when an explicit selection is pending", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: false,
        pendingSelection: true,
        gameCount: 1,
        operationInProgress: false,
        explicitSelectionPending: true,
      })
    ).toBe("wait");
  });

  it("returns consume before checking an operation in progress", () => {
    expect(
      resolveQamOpenSelection({
        isQuickAccessVisible: true,
        pendingSelection: true,
        gameCount: 1,
        operationInProgress: true,
        explicitSelectionPending: true,
      })
    ).toBe("consume");
  });
});
