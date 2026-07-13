import type { LifecycleCheckResult, OperationResult } from "../types";

export function summarizeLifecycleResult(result: LifecycleCheckResult | OperationResult): string {
  const summary: Record<string, any> = {
    status: result.status,
  };

  if ("operation" in result && result.operation) {
    summary.operation = result.operation;
  }
  
  if ("reason" in result && result.reason) {
    summary.reason = result.reason;
  }
  
  if ("message" in result && typeof result.message === "string") {
    summary.message = result.message.substring(0, 150);
  }

  if ("result" in result && result.result && typeof result.result === "object") {
    const resPayload = result.result as Record<string, any>;
    if ("files" in resPayload) {
      summary.files = resPayload.files;
    }
    if ("registry" in resPayload) {
      summary.registry = resPayload.registry;
    }
    if ("bytes" in resPayload) {
      summary.bytes = resPayload.bytes;
    }
    if ("game" in resPayload) {
      summary.game = resPayload.game;
    }
  }
  
  return JSON.stringify(summary);
}
