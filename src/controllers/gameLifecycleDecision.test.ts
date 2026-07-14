import { describe, it, expect } from "vitest";
import { evaluateStartCheck, evaluateStartConflictResolution, evaluatePreGameQuiescence, evaluateExitCheck, getStartCleanup, getExitCleanup } from "./gameLifecycleDecision";
import type { StartState, ExitState } from "./gameLifecycleDecision";

describe("gameLifecycleDecision", () => {
  describe("Start", () => {
    const baseState: StartState = {
      name: "Test Game",
      appID: "123",
      tracked: true,
      autoSyncEnabled: true,
      paused: true,
      watchActive: true,
      retainPreGameWatch: false,
      instanceID: 100,
    };

    it("evaluates check: silent skip", () => {
      const decision = evaluateStartCheck(baseState, { status: "skipped", reason: "auto_sync_disabled" });
      expect(decision.commands).toEqual([{ type: "hideStatus", resultStatus: "skipped" }]);
      expect(decision.nextRpc).toBeUndefined();
    });

    it("evaluates check: restore needed", () => {
      const decision = evaluateStartCheck(baseState, { status: "needed", operation: "restore" });
      expect(decision.commands).toEqual([{ type: "publishStatus", status: "restoring" }]);
      expect(decision.nextRpc).toBe("restore");
    });

    it("evaluates check: restore needed but not paused", () => {
      const decision = evaluateStartCheck({ ...baseState, paused: false }, { status: "needed", operation: "restore" });
      expect(decision.commands).toContainEqual(expect.objectContaining({ type: "completeStatus" }));
      expect(decision.commands).toContainEqual(expect.objectContaining({ type: "notifyFailure" }));
    });

    it("maps an interrupted active pre-game transfer to one safe failure", () => {
      const decision = evaluatePreGameQuiescence({ status: "timeout", activityObserved: true });
      expect(decision).toEqual({
        commands: [
          { type: "publishStatus", status: "error" },
          {
            type: "notifyFailure",
            fallbackMessage: "Launch verification could not safely complete after incoming save activity.",
          },
        ],
        abort: true,
      });
    });

    it("maps conflict dismissal to the explicit unresolved result", () => {
      const decision = evaluateStartConflictResolution(baseState, null);
      expect(decision.commands).toEqual([
        {
          type: "completeStatus",
          result: { status: "skipped", game: "Test Game", reason: "conflict_unresolved" },
        },
      ]);
    });
    
    it("evaluates cleanup: leaves no paused process or unowned watch", () => {
      const cleanup = getStartCleanup(baseState);
      expect(cleanup).toContainEqual({ type: "resumeProcess", instanceID: 100 });
      expect(cleanup).toContainEqual({ type: "cancelWatch", reason: "start_handler_cleanup" });
      expect(cleanup).toContainEqual({ type: "syncHistory" });
    });
  });

  describe("Exit", () => {
    const baseState: ExitState = {
      name: "Test Game",
      appID: "123",
      tracked: true,
      autoSyncEnabled: true,
      watchActive: true,
      handoffTransferred: false,
    };

    it("evaluates check: backup needed", () => {
      const decision = evaluateExitCheck(baseState, { status: "needed", operation: "backup" });
      expect(decision.commands).toEqual([{ type: "publishStatus", status: "backing_up" }]);
      expect(decision.nextRpc).toBe("backup");
    });
    
    it("evaluates cleanup: cancels watch if not transferred", () => {
      const cleanup = getExitCleanup(baseState);
      expect(cleanup).toContainEqual({ type: "cancelWatch", reason: "exit_handler_cleanup" });
      expect(cleanup).toContainEqual({ type: "syncHistory" });
    });
  });
});
