import type { OperationStatus } from "../types";

export function createContentLoadCoordinator(): {
  initPromise: Promise<OperationStatus> | null;
  metadataPromise: Promise<void> | null;
} {
  return {
    initPromise: null,
    metadataPromise: null,
  };
}
