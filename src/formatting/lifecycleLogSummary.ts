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
    if (typeof resPayload.files === "number" || typeof resPayload.files === "string") {
      summary.files = resPayload.files;
    }
    if (typeof resPayload.registry === "number" || typeof resPayload.registry === "string") {
      summary.registry = resPayload.registry;
    }
    if (typeof resPayload.bytes === "number" || typeof resPayload.bytes === "string") {
      summary.bytes = resPayload.bytes;
    }
    if (typeof resPayload.game === "number" || typeof resPayload.game === "string") {
      summary.game = resPayload.game;
    }
  }
  
  return JSON.stringify(summary);
}
