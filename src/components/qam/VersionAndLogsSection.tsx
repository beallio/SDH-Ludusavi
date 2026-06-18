import { ButtonItem, Field, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

import type { Versions } from "../../types";

type VersionAndLogsSectionProps = {
  versions: Versions;
  onShowPluginLogs: () => void;
  onShowLudusaviLogs: () => void;
};

type LogsSectionProps = Pick<VersionAndLogsSectionProps, "onShowPluginLogs" | "onShowLudusaviLogs"> & {
  debugLogging: boolean;
  isBusy: boolean;
  onToggleDebugLogging: (enabled: boolean) => void;
};

type VersionsSectionProps = Pick<VersionAndLogsSectionProps, "versions">;

export function LogsSection({
  onShowPluginLogs,
  onShowLudusaviLogs,
  debugLogging,
  isBusy,
  onToggleDebugLogging
}: LogsSectionProps) {
  return (
    <PanelSection title="Logs">
      <PanelSectionRow>
        <ButtonItem layout="below" bottomSeparator="none" onClick={onShowPluginLogs}>
          View Logs
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" bottomSeparator="none" onClick={onShowLudusaviLogs}>
          View Ludusavi Logs
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Debug Logging"
          description="Enables verbose logging for troubleshooting."
          bottomSeparator="standard"
          checked={debugLogging}
          disabled={isBusy}
          onChange={(enabled: boolean) => onToggleDebugLogging(enabled)}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

export function VersionsSection({ versions }: VersionsSectionProps) {
  return (
    <PanelSection title="Versions">
      <PanelSectionRow>
        <Field highlightOnFocus={true} focusable={true} childrenLayout="below" padding="standard" bottomSeparator="none">
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: "7px",
              minWidth: 0,
              textAlign: "left",
              fontSize: "14px",
              color: "#cbd5e1",
              paddingLeft: "10px"
            }}
          >
            <div>SDH-Ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>
            <div>Ludusavi: {versions.ludusavi ?? versions.message ?? "Unknown"}</div>
            <div>pyludusavi: {versions.pyludusavi ?? "Unknown"}</div>
            <div>Decky: {versions.decky ?? "Unknown"}</div>
          </div>
        </Field>
      </PanelSectionRow>
    </PanelSection>
  );
}
