import type { LifecycleCheckResult, OperationResult } from "../types";

export function summarizeLifecycleResult(result: LifecycleCheckResult | OperationResult): string {
  const summary: Record<string, unknown> = {
    status: result.status,
  };

  if ("operation" in result && result.operation) {
    summary.operation = result.operation;
  }

  if ("reason" in result && result.reason) {
    summary.reason = sanitizeFreeformField(result.reason);
  }

  if ("message" in result && typeof result.message === "string") {
    summary.message = sanitizeFreeformField(result.message.substring(0, 150));
  }

  if ("game" in result && result.game) {
    summary.game = sanitizeFreeformField(result.game);
  }

  if ("result" in result && result.result) {
    const payload = result.result;
    if (payload.overall) {
      if (typeof payload.overall.totalGames === "number" && Number.isFinite(payload.overall.totalGames)) {
        summary.totalGames = payload.overall.totalGames;
      }
      if (typeof payload.overall.totalBytes === "number" && Number.isFinite(payload.overall.totalBytes)) {
        summary.totalBytes = payload.overall.totalBytes;
      }
      if (typeof payload.overall.processedGames === "number" && Number.isFinite(payload.overall.processedGames)) {
        summary.processedGames = payload.overall.processedGames;
      }
      if (typeof payload.overall.processedBytes === "number" && Number.isFinite(payload.overall.processedBytes)) {
        summary.processedBytes = payload.overall.processedBytes;
      }
    }
  }

  return JSON.stringify(summary);
}

function sanitizeFreeformField(text: string): string {
  return text
    .replace(/(?:\/[a-zA-Z0-9_.-]+){2,}/g, "[PATH]")
    .slice(0, 150);
}
