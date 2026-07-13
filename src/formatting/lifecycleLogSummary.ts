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
    let msg = result.message.substring(0, 150);
    // Redact paths
    msg = msg.replace(/(?:\/[a-zA-Z0-9_.-]+){2,}/g, "[PATH]");
    summary.message = msg;
  }

  if ("result" in result && result.result && typeof result.result === "object") {
    const resPayload = result.result as Record<string, any>;
    if (typeof resPayload.files === "number") {
      summary.files = resPayload.files;
    }
    if (typeof resPayload.registry === "number") {
      summary.registry = resPayload.registry;
    }
    if (typeof resPayload.bytes === "number") {
      summary.bytes = resPayload.bytes;
    }
    if (typeof resPayload.game === "string") {
      summary.game = resPayload.game;
    }
  }
  
  return JSON.stringify(summary);
}
