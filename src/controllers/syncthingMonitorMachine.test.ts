import { describe, it, expect } from "vitest";
import {
  createInitialWatchState,
  transition,
  isTerminal,
  canCleanup,
  handoffOutcome,
  mapSyncthingFailureReason,
  WatchPhase
} from "./syncthingMonitorMachine";

describe("SyncthingMonitorMachine", () => {
  describe("createInitialWatchState", () => {
    it.each<WatchPhase>(["pre_game", "post_game"])("creates initial state for %s", (phase) => {
      const state = createInitialWatchState(phase);
      expect(state).toEqual({
        phase,
        step: "allocating",
        initialized: false,
        publicationEnabled: false,
        activityObserved: false,
        mutationObserved: false,
        completionObserved: false,
        settledCount: 0,
        lastProcessedTimestamp: null,
        latestStatus: "idle",
        handoffActivated: false,
        detectionGraceMs: 30000,
        unavailableReason: "initialization_failed",
      });
    });
  });

  describe("transitions", () => {
    describe("watch_allocated", () => {
      it("ignores if not allocating", () => {
        let state = createInitialWatchState("post_game");
        state = { ...state, step: "watching" };
        const res = transition(state, { type: "watch_allocated", detectionGraceMs: 10000 });
        expect(res.state).toEqual(state);
        expect(res.effects).toEqual({
          publish: null,
          resolveReadiness: null,
          stopWatch: false,
          clearPendingTimer: false,
          schedulePendingTimer: false,
          nextPoll: "none",
        });
      });

      it("transitions to watching and enables publication for pre_game", () => {
        const state = createInitialWatchState("pre_game");
        const res = transition(state, { type: "watch_allocated", detectionGraceMs: 10000 });
        expect(res.state.step).toBe("watching");
        expect(res.state.detectionGraceMs).toBe(10000);
        expect(res.state.publicationEnabled).toBe(true);
      });

      it.each([undefined, NaN, 0, -1])("clamps invalid detectionGraceMs %s to 30000", (val) => {
        const state = createInitialWatchState("post_game");
        const res = transition(state, { type: "watch_allocated", detectionGraceMs: val as any });
        expect(res.state.detectionGraceMs).toBe(30000);
        expect(res.state.publicationEnabled).toBe(false);
      });
    });

    describe("watch_allocation_failed", () => {
      it("transitions to cancelled and resolves unavailable", () => {
        const state = createInitialWatchState("pre_game");
        const res = transition(state, { type: "watch_allocation_failed", reason: "api_unavailable" });
        expect(res.state.step).toBe("cancelled");
        expect(res.state.unavailableReason).toBe("api_unavailable");
        expect(res.effects.resolveReadiness).toBe("unavailable");
      });

      it.each([
        ["not_configured", "not_configured"],
        ["api_unavailable", "api_unavailable"],
        ["folder_not_found", "folder_not_found"],
        ["folder_not_shared", "folder_not_shared"],
        ["no_connected_peers", "no_connected_peers"],
        ["unknown_reason", "initialization_failed"],
        [undefined, "initialization_failed"]
      ])("maps actionable reason %s to %s", (input, expected) => {
        const state = createInitialWatchState("post_game");
        const res = transition(state, { type: "watch_allocation_failed", reason: input });
        expect(res.state.unavailableReason).toBe(expected);
      });
    });

    describe("cancel", () => {
      it("is idempotent", () => {
        const state = createInitialWatchState("post_game");
        const r1 = transition(state, { type: "cancel" });
        expect(r1.state.step).toBe("cancelled");
        expect(r1.state.publicationEnabled).toBe(false);
        const r2 = transition(r1.state, { type: "cancel" });
        expect(r2.state).toEqual(r1.state);
        expect(r2.effects.stopWatch).toBe(false);
      });

      it("preserves completionObserved", () => {
        let state = createInitialWatchState("post_game");
        state = { ...state, step: "complete", completionObserved: true };
        const res = transition(state, { type: "cancel" });
        expect(res.state.step).toBe("cancelled");
        expect(res.state.completionObserved).toBe(true);
      });
    });

    describe("sample", () => {
      it("retries on null sample", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const };
        const res = transition(state, { type: "sample", sample: null });
        expect(res.state).toEqual(state);
        expect(res.effects.nextPoll).toBe("retry");
      });

      it("retries on invalid sample when not initialized", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: NaN, folder_state: "unknown" } as any });
        expect(res.effects.nextPoll).toBe("retry");
        expect(res.state.initialized).toBe(false);
      });

      it("initializes and processes valid sample", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: 1, folder_state: "idle", uploading: true, downloading: false, update_in_progress: false, status: "idle", settled: false } });
        expect(res.state.initialized).toBe(true);
        expect(res.state.lastProcessedTimestamp).toBe(1);
        expect(res.state.activityObserved).toBe(true);
        expect(res.state.latestStatus).toBe("uploading");
        expect(res.effects.resolveReadiness).toBe("ready");
      });

      it("does not publish a transfer status for an idle sample", () => {
        const state = {
          ...createInitialWatchState("pre_game"),
          step: "watching" as const,
          initialized: true,
          publicationEnabled: true,
        };
        const res = transition(state, {
          type: "sample",
          sample: {
            timestamp_unix: 1,
            folder_state: "idle",
            uploading: false,
            downloading: false,
            update_in_progress: false,
            status: "IDLE",
            settled: true,
          },
        });

        expect(res.state.latestStatus).toBe("idle");
        expect(res.state.activityObserved).toBe(false);
        expect(res.effects.publish).toBeNull();
      });

      it("ignores duplicate timestamp when initialized", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, lastProcessedTimestamp: 1 };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: 1 } as any });
        expect(res.effects.nextPoll).toBe("active");
        expect(res.state.lastProcessedTimestamp).toBe(1);
      });
      
      it("ignores invalid timestamp when initialized", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, lastProcessedTimestamp: 1 };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: NaN } as any });
        expect(res.effects.nextPoll).toBe("active");
        expect(res.state.lastProcessedTimestamp).toBe(1);
      });

      it("processes valid sample with unknown folder state after initialization", () => {
        const state = { 
          ...createInitialWatchState("post_game"), 
          step: "watching" as const, 
          initialized: true, 
          activityObserved: true, 
          mutationObserved: true,
          settledCount: 2, 
          lastProcessedTimestamp: 10 
        };
        const res = transition(state, { 
          type: "sample", 
          sample: { 
            timestamp_unix: 11, 
            folder_state: "unknown", 
            uploading: false, 
            downloading: false, 
            update_in_progress: false, 
            settled: true, 
            status: "IDLE" 
          } as any 
        });
        expect(res.state.settledCount).toBe(3);
        expect(res.state.completionObserved).toBe(true);
        expect(res.state.step).toBe("complete");
        expect(res.state.lastProcessedTimestamp).toBe(11);
      });

      it("maintains rank monotonicity for post_game", () => {
        let state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, publicationEnabled: true, activityObserved: true, latestStatus: "uploading" as const };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: 2, uploading: false, downloading: true, update_in_progress: false, status: "idle", settled: false } as any });
        // downloading is same rank as uploading (1), so latestStatus doesn't change from uploading
        expect(res.state.latestStatus).toBe("uploading");
        expect(res.effects.publish).toBeNull();
      });

      it("concurrent upload and download goes to uploading for post_game", () => {
        let state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, publicationEnabled: true, latestStatus: "idle" as const };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: 2, uploading: true, downloading: true, update_in_progress: false, status: "idle", settled: false } as any });
        expect(res.state.latestStatus).toBe("uploading");
        expect(res.effects.publish).toEqual({ status: "syncthing_uploading", source: "context" });
      });

      it("resets settledCount on interleaved activity", () => {
        let state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, activityObserved: true, settledCount: 2 };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: 2, uploading: true, downloading: false, update_in_progress: false, status: "idle", settled: false } as any });
        expect(res.state.settledCount).toBe(0);
      });
      
      it("completes on settledCount >= 3", () => {
        let state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, activityObserved: true, mutationObserved: true, settledCount: 2 };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: 2, uploading: false, downloading: false, update_in_progress: false, status: "idle", settled: true } as any });
        expect(res.state.settledCount).toBe(3);
        expect(res.state.step).toBe("complete");
        expect(res.state.completionObserved).toBe(true);
        expect(res.effects.stopWatch).toBe(true);
      });

      it("completes post-game via mutation without uploading", () => {
        let state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, publicationEnabled: true, handoffActivated: true };
        
        let res = transition(state, { type: "sample", sample: { timestamp_unix: 1, status: "SCANNING", settled: false, uploading: false, downloading: false, update_in_progress: false, folder_state: "scanning" } as any });
        expect(res.state.mutationObserved).toBe(true);
        expect(res.state.activityObserved).toBe(false);

        res = transition(res.state, { type: "sample", sample: { timestamp_unix: 2, status: "IDLE", settled: true, uploading: false, downloading: false, update_in_progress: false, folder_state: "idle" } as any });
        res = transition(res.state, { type: "sample", sample: { timestamp_unix: 3, status: "IDLE", settled: true, uploading: false, downloading: false, update_in_progress: false, folder_state: "idle" } as any });
        res = transition(res.state, { type: "sample", sample: { timestamp_unix: 4, status: "IDLE", settled: true, uploading: false, downloading: false, update_in_progress: false, folder_state: "idle" } as any });

        expect(res.state.step).toBe("complete");
        expect(res.state.completionObserved).toBe(true);
        expect(res.effects.publish).toEqual({ status: "syncthing_complete", source: "context" });
        expect(res.effects.stopWatch).toBe(true);
      });

      it("does not increment settledCount before mutationObserved in post-game", () => {
        let state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true };
        const res = transition(state, { type: "sample", sample: { timestamp_unix: 1, status: "IDLE", settled: true, uploading: false, downloading: false, update_in_progress: false, folder_state: "idle" } as any });
        expect(res.state.settledCount).toBe(0);
      });
    });

    describe("poll_failed", () => {
      it("resolves unavailable if not initialized", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const };
        const res = transition(state, { type: "poll_failed", reason: "api_unavailable" });
        expect(res.state.step).toBe("cancelled");
        expect(res.effects.resolveReadiness).toBe("unavailable");
      });
      
      it("publishes error if publicationEnabled and post_game", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, publicationEnabled: true };
        const res = transition(state, { type: "poll_failed", reason: "api_unavailable" });
        expect(res.effects.publish).toEqual({ status: "syncthing_unavailable", source: "rpc_result" });
      });
    });

    describe("handoff events", () => {
      it("handoff_confirmed enables publication and schedules timer if pending", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const };
        const res = transition(state, { type: "handoff_confirmed" });
        expect(res.state.handoffActivated).toBe(true);
        expect(res.state.publicationEnabled).toBe(true);
        expect(res.effects.schedulePendingTimer).toBe(true);
      });

      it("handoff_finished activates handoff", () => {
        const state = createInitialWatchState("post_game");
        const res = transition(state, { type: "handoff_finished" });
        expect(res.state.handoffActivated).toBe(true);
      });
    });

    describe("pending_activity_timeout", () => {
      it("cancels and publishes if guarded correctly", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, publicationEnabled: true, activityObserved: false };
        const res = transition(state, { type: "pending_activity_timeout" });
        expect(res.state.step).toBe("cancelled");
        expect(res.state.publicationEnabled).toBe(false);
        expect(res.effects.publish).toEqual({ status: "has_backup", source: "timeout" });
      });

      it("cancels and publishes even if mutationObserved is true (timeout backstop)", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, publicationEnabled: true, activityObserved: false, mutationObserved: true };
        const res = transition(state, { type: "pending_activity_timeout" });
        expect(res.state.step).toBe("cancelled");
        expect(res.state.publicationEnabled).toBe(false);
        expect(res.effects.publish).toEqual({ status: "has_backup", source: "timeout" });
        expect(res.effects.stopWatch).toBe(true);
      });
      
      it("ignores if not publicationEnabled", () => {
        const state = { ...createInitialWatchState("post_game"), step: "watching" as const, initialized: true, publicationEnabled: false, activityObserved: false };
        const res = transition(state, { type: "pending_activity_timeout" });
        expect(res.state).toEqual(state);
      });
    });
  });

  describe("isTerminal", () => {
    it.each([
      ["allocating", false],
      ["watching", false],
      ["complete", true],
      ["cancelled", true],
    ])("%s -> %s", (step, expected) => {
      expect(isTerminal({ step } as any)).toBe(expected);
    });
  });

  describe("canCleanup", () => {
    // 2x2x2 matrix: phase(pre/post), handoffActivated(t/f), superseded(t/f) for a terminal state
    const terminal = { step: "cancelled" } as any;
    const nonTerminal = { step: "watching" } as any;
    
    it("returns false if not terminal", () => {
      expect(canCleanup({ ...nonTerminal, phase: "post_game", handoffActivated: false }, false)).toBe(false);
    });

    it("returns true for pre_game if terminal", () => {
      expect(canCleanup({ ...terminal, phase: "pre_game", handoffActivated: false }, false)).toBe(true);
    });

    it("returns true for post_game if terminal and superseded", () => {
      expect(canCleanup({ ...terminal, phase: "post_game", handoffActivated: false }, true)).toBe(true);
    });
    
    it("returns true for post_game if terminal and handoffActivated", () => {
      expect(canCleanup({ ...terminal, phase: "post_game", handoffActivated: true }, false)).toBe(true);
    });
    
    it("returns false for post_game if terminal and not superseded and not handoffActivated", () => {
      expect(canCleanup({ ...terminal, phase: "post_game", handoffActivated: false }, false)).toBe(false);
    });
  });

  describe("handoffOutcome", () => {
    it("complete", () => {
      expect(handoffOutcome({ latestStatus: "complete" } as any)).toBe("complete");
    });
    it("uploading", () => {
      expect(handoffOutcome({ latestStatus: "idle", activityObserved: true } as any)).toBe("uploading");
    });
    it("pending", () => {
      expect(handoffOutcome({ latestStatus: "idle", activityObserved: false } as any)).toBe("pending");
    });
  });

  describe("mapSyncthingFailureReason", () => {
    it("maps reasons", () => {
      expect(mapSyncthingFailureReason("no_connected_peers")).toBe("syncthing_no_peers");
      expect(mapSyncthingFailureReason("folder_not_found")).toBe("syncthing_folder_not_found");
      expect(mapSyncthingFailureReason("folder_not_shared")).toBe("syncthing_folder_not_found");
      expect(mapSyncthingFailureReason("api_unavailable")).toBe("syncthing_unavailable");
      expect(mapSyncthingFailureReason("unknown")).toBeNull();
      expect(mapSyncthingFailureReason(undefined)).toBeNull();
    });
  });
});
