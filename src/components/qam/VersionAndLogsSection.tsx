import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";

import type { Versions } from "../../types";

type VersionAndLogsSectionProps = {
  versions: Versions;
  onShowPluginLogs: () => void;
  onShowLudusaviLogs: () => void;
};

export function VersionAndLogsSection({
  versions,
  onShowPluginLogs,
  onShowLudusaviLogs
}: VersionAndLogsSectionProps) {
  return (
    <>
      <PanelSection title="Logs">
        <PanelSectionRow>
          <ButtonItem layout="below" bottomSeparator="none" onClick={onShowPluginLogs}>
            View Logs
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" bottomSeparator="standard" onClick={onShowLudusaviLogs}>
            View Ludusavi Logs
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

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
    </>
  );
}
