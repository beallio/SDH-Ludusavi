import { callable } from "@decky/api";

const logCall = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");

declare global {
  interface Window {
    DeckyBackend?: {
      callable: (method: string) => (...args: any[]) => Promise<any>;
      call?: (method: string, ...args: any[]) => Promise<any>;
    };
  }
}

const EXPECTED_PLUGIN_NAME = "SDH-Ludusavi";
export const INSTALL_TYPE_UPDATE = 2;
export const INSTALL_TYPE_DOWNGRADE = 3;

export function isDeckyInstallerAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.DeckyBackend === "object" &&
    window.DeckyBackend !== null &&
    (typeof window.DeckyBackend.callable === "function" ||
      typeof window.DeckyBackend.call === "function")
  );
}

export async function invokeDeckyInstaller(
  url: string,
  version: string,
  sha256: string,
  installType: typeof INSTALL_TYPE_UPDATE | typeof INSTALL_TYPE_DOWNGRADE,
  traceId?: string
): Promise<any> {
  const start = performance.now();
  const backend = window.DeckyBackend;
  if (!backend) {
    throw new Error("Decky Loader backend is not available in this environment.");
  }

  const shaPrefix = sha256.slice(0, 8);
  const elapsed = Math.round(performance.now() - start);

  if (typeof backend.callable === "function") {
    // installer_api: "callable"
    try {
      void logCall("info", `handoff_start: trace_id=${traceId || "none"}, version=${version}, sha256_prefix=${shaPrefix}, installer_api="callable", elapsed_ms=${elapsed}`, "update");
    } catch (_) {}
    const installFn = backend.callable("utilities/install_plugin");
    return await installFn(url, EXPECTED_PLUGIN_NAME, version, sha256, installType);
  } else if (typeof backend.call === "function") {
    // installer_api: "call"
    try {
      void logCall("info", `handoff_start: trace_id=${traceId || "none"}, version=${version}, sha256_prefix=${shaPrefix}, installer_api="call", elapsed_ms=${elapsed}`, "update");
    } catch (_) {}
    return await backend.call("utilities/install_plugin", url, EXPECTED_PLUGIN_NAME, version, sha256, installType);
  } else {
    throw new Error("Decky Loader backend has no compatible RPC interface.");
  }
}
