import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useState } from "react";

import { launchLudusavi, type LudusaviLaunchCommand } from "../../ludusaviLauncher";
import { log, logUiEvent } from "../../utils/logging";

type LudusaviLauncherSectionProps = {
  ludusaviCommand: LudusaviLaunchCommand | null;
  isLoading: boolean;
};

export function LudusaviLauncherSection({
  ludusaviCommand,
  isLoading
}: LudusaviLauncherSectionProps) {
  const [status, setStatus] = useState<string | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);

  async function onLaunch() {
    const startedAt = performance.now();
    logUiEvent(
      "ludusavi_launch_requested",
      { command_available: ludusaviCommand !== null },
      "info",
      "launcher",
    );
    try {
      setIsLaunching(true);
      setStatus("Launching Ludusavi...");

      if (!ludusaviCommand) {
        throw new Error("Ludusavi not found on system.");
      }

      await launchLudusavi(ludusaviCommand, { logger: log });

      setStatus("Ludusavi launch requested.");
      logUiEvent(
        "ludusavi_launch_completed",
        { elapsed_ms: Math.round(performance.now() - startedAt) },
        "info",
        "launcher",
      );
      // Best-effort clear status after 3s
      setTimeout(() => setStatus(null), 3000);
    } catch (err) {
      logUiEvent(
        "ludusavi_launch_failed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          message: err instanceof Error ? err.message : String(err),
        },
        "error",
        "launcher",
      );
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLaunching(false);
    }
  }

  return (
    <PanelSection title="Ludusavi">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={onLaunch}
          disabled={isLaunching || !ludusaviCommand}
        >
          Launch
        </ButtonItem>
      </PanelSectionRow>

      {status && (
        <PanelSectionRow>
          <div style={{ color: "#60a5fa", fontSize: "14px", fontWeight: "bold", padding: "0 4px" }}>
            {status}
          </div>
        </PanelSectionRow>
      )}

      {!ludusaviCommand && !isLaunching && !isLoading && (
        <PanelSectionRow>
          <div style={{ color: "#ef4444", fontSize: "12px", padding: "0 4px" }}>
            Ludusavi not found. Please install it via Flatpak or add to PATH.
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
