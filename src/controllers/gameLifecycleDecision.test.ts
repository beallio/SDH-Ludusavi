import { describe, it, expect } from "vitest";
import { evaluateStartCheck, evaluateStartRestore, evaluateStartConflictResolution, evaluatePreGameQuiescence, evaluateExitCheck, evaluateExitBackup, evaluateExitHandoff, getStartCleanup, getExitCleanup, SILENT_SKIPPED_REASONS } from "./gameLifecycleDecision";
import type { StartState, ExitState } from "./gameLifecycleDecision";

describe("gameLifecycleDecision", () => {
  it("keeps game_sync_disabled out of silent skip reasons", () => {
    expect(SILENT_SKIPPED_REASONS).not.toContain("game_sync_disabled");
  });

  it("keeps coordinator contention visible for start checks", () => {
    const decision = evaluateStartCheck(
      {
        name: "Test Game",
        appID: "123",
        tracked: true,
        autoSyncEnabled: true,
        paused: true,
        watchActive: true,
        retainPreGameWatch: false,
      },
      { status: "skipped", reason: "operation_running" },
    );

    expect(decision.commands).toEqual([
      {
        type: "completeStatus",
        result: { status: "skipped", reason: "operation_running" },
      },
      {
        type: "notifyFailure",
        result: { status: "skipped", reason: "operation_running" },
      },
    ]);
    expect(decision.stateUpdates).toEqual({ retainPreGameWatch: false });
  });

  it("keeps coordinator contention visible for exit checks", () => {
    const decision = evaluateExitCheck(
      {
        name: "Test Game",
        appID: "123",
        tracked: true,
        autoSyncEnabled: true,
        watchActive: true,
        handoffTransferred: false,
      },
      { status: "skipped", reason: "operation_running" },
    );

    expect(decision.commands).toEqual([
      {
        type: "completeStatus",
        result: { status: "skipped", reason: "operation_running" },
      },
      {
        type: "notifyFailure",
        result: { status: "skipped", reason: "operation_running" },
      },
    ]);
  });

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

    it("keeps coordinator contention visible for the start restore action", () => {
      const result = { status: "skipped" as const, game: "Test Game", reason: "operation_running" };
      const decision = evaluateStartRestore(baseState, result);

      expect(decision.commands).toEqual([
        { type: "completeStatus", result },
        { type: "notifyFailure", result },
      ]);
      expect(decision.stateUpdates).toEqual({ retainPreGameWatch: false });
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

    it("keeps coordinator contention visible for the keep-local conflict action", () => {
      const result = { status: "skipped" as const, game: "Test Game", reason: "operation_running" };
      const decision = evaluateStartConflictResolution(baseState, "keep_local", result);

      expect(decision.commands).toEqual([
        { type: "completeStatus", result },
        { type: "notifyFailure", result },
      ]);
      expect(decision.stateUpdates).toEqual({ retainPreGameWatch: false });
    });

    it("keeps coordinator contention visible for the restore-backup conflict action", () => {
      const result = { status: "skipped" as const, game: "Test Game", reason: "operation_running" };
      const decision = evaluateStartConflictResolution(baseState, "restore_backup", result);

      expect(decision.commands).toEqual([
        { type: "completeStatus", result },
        { type: "notifyFailure", result },
      ]);
      expect(decision.stateUpdates).toEqual({ retainPreGameWatch: false });
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

    it("preserves a successful backup result for post-game status dwell", () => {
      const result = { status: "backed_up" as const, game: "Test Game" };

      const decision = evaluateExitBackup(baseState, result);

      expect(decision.commands).toEqual([{ type: "completeStatus", result }]);
      expect(decision.nextRpc).toBe("handoff");
    });

    it("keeps coordinator contention visible for the exit backup action", () => {
      const result = { status: "skipped" as const, game: "Test Game", reason: "operation_running" };

      expect(evaluateExitBackup(baseState, result).commands).toEqual([
        { type: "completeStatus", result },
        { type: "notifyFailure", result },
      ]);
    });

    it("publishes uploading when the post-game handoff reports buffered peer activity", () => {
      const backupResult = { status: "backed_up" as const, game: "Test Game" };

      const decision = evaluateExitHandoff(
        baseState,
        { status: "uploading" },
        backupResult,
        null,
      );

      expect(decision).toEqual({
        commands: [{ type: "publishStatus", status: "syncthing_uploading" }],
        stateUpdates: { handoffTransferred: true },
      });
    });

    it.each([
      { status: "unavailable" as const, reason: "initialization_failed" },
      { status: "stale" as const },
    ])("does not complete an already completed backup again for $status handoff", (handoff) => {
      const result = { status: "backed_up" as const, game: "Test Game" };

      const decision = evaluateExitHandoff(baseState, handoff, result, null);

      expect(decision.commands).toEqual([]);
    });
    
    it("evaluates cleanup: cancels watch if not transferred", () => {
      const cleanup = getExitCleanup(baseState);
      expect(cleanup).toContainEqual({ type: "cancelWatch", reason: "exit_handler_cleanup" });
      expect(cleanup).toContainEqual({ type: "syncHistory" });
    });
  });
});
