import { callable } from "@decky/api";

const logCall = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");

export const log = (
  level: "info" | "debug" | "warning" | "error",
  message: string,
  operation?: string,
  gameName?: string
) => {
  const prefix = `SDH-Ludusavi${operation ? `:${operation}` : ""}${gameName ? ` [${gameName}]` : ""}`;
  const fullMsg = `${prefix}: ${message}`;
  
  console.log(fullMsg);

  void logCall(level, message, operation, gameName);
};
