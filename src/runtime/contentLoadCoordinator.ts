import type { OperationStatus } from "../types";

export function createContentLoadCoordinator(): {
  getInitPromise(): Promise<OperationStatus> | null;
  setInitPromise(p: Promise<OperationStatus> | null): void;
  getMetadataPromise(): Promise<void> | null;
  setMetadataPromise(p: Promise<void> | null): void;
  dispose(): void;
} {
  let activeInitPromise: Promise<OperationStatus> | null = null;
  let activeMetadataPromise: Promise<void> | null = null;

  return {
    getInitPromise() {
      return activeInitPromise;
    },
    setInitPromise(p) {
      activeInitPromise = p;
    },
    getMetadataPromise() {
      return activeMetadataPromise;
    },
    setMetadataPromise(p) {
      activeMetadataPromise = p;
    },
    dispose() {
      activeInitPromise = null;
      activeMetadataPromise = null;
    }
  };
}
