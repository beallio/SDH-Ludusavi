import { callable } from "@decky/api";

const logCall = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");

export type LogLevel = "info" | "debug" | "warning" | "error";
export type LogFieldValue = string | number | boolean | null | undefined;
export type LogFields = Record<string, LogFieldValue>;

function writeConsole(level: LogLevel, message: string) {
  if (level === "debug") {
    console.debug(message);
  } else if (level === "info") {
    console.info(message);
  } else if (level === "warning") {
    console.warn(message);
  } else {
    console.error(message);
  }
}

export const log = (
  level: LogLevel,
  message: string,
  operation?: string,
  gameName?: string
) => {
  const prefix = `SDH-Ludusavi${operation ? `:${operation}` : ""}${gameName ? ` [${gameName}]` : ""}`;
  const fullMsg = `${prefix}: ${message}`;

  writeConsole(level, fullMsg);

  try {
    void Promise.resolve(logCall(level, message, operation, gameName)).catch((error) => {
      console.error("SDH-Ludusavi: logging RPC failed", error);
    });
  } catch (error) {
    console.error("SDH-Ludusavi: logging RPC failed", error);
  }
};

function formatFieldValue(value: Exclude<LogFieldValue, undefined>): string {
  return typeof value === "string" ? JSON.stringify(value) : String(value);
}

export function logUiEvent(
  event: string,
  fields: LogFields = {},
  level: LogLevel = "debug",
  operation = "ui",
  gameName?: string,
) {
  const details = Object.entries(fields)
    .filter((entry): entry is [string, Exclude<LogFieldValue, undefined>] => entry[1] !== undefined)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${formatFieldValue(value)}`)
    .join(" ");
  log(level, details ? `${event}: ${details}` : event, operation, gameName);
}
