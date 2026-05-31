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
  installType: typeof INSTALL_TYPE_UPDATE | typeof INSTALL_TYPE_DOWNGRADE
): Promise<any> {
  const backend = window.DeckyBackend;
  if (!backend) {
    throw new Error("Decky Loader backend is not available in this environment.");
  }

  if (typeof backend.callable === "function") {
    const installFn = backend.callable("utilities/install_plugin");
    return await installFn(EXPECTED_PLUGIN_NAME, url, version, sha256, installType);
  } else if (typeof backend.call === "function") {
    return await backend.call("utilities/install_plugin", EXPECTED_PLUGIN_NAME, url, version, sha256, installType);
  } else {
    throw new Error("Decky Loader backend has no compatible RPC interface.");
  }
}
