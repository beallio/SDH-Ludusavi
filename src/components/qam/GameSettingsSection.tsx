import {
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  SingleDropdownOption
} from "@decky/ui";
import type { ReactNode } from "react";

import type { GameOperationHistoryEntry, GameStatus } from "../../types";
import { formatDateMDY, formatTime12h } from "../../formatting/dateTime";
import { getLastOperationText } from "../../formatting/operationText";
import { SpinnerButton } from "./SpinnerButton";

const statusLabels: Record<GameStatus["status"], string> = {
  configured: "Configured",
  has_backup: "Backup ready",
  needs_first_backup: "Needs first backup",
  error: "Error"
};

type GameSettingsSectionProps = {
  isBusy: boolean;
  busyLabel: string | null;
  gamesDropdownOptions: SingleDropdownOption[];
  selectedGame: string;
  selectedStatus: GameStatus | null;
  selectedHistory: GameOperationHistoryEntry | null;
  onGameChange: (data: SingleDropdownOption | string | null | undefined) => void;
  onForceBackup: () => void;
  onForceRestore: () => void;
};

function CompactFieldLabel({ children }: { children: ReactNode }) {
  return <span style={{ fontSize: "14px" }}>{children}</span>;
}

export function GameSettingsSection({
  isBusy,
  busyLabel,
  gamesDropdownOptions,
  selectedGame,
  selectedStatus,
  selectedHistory,
  onGameChange,
  onForceBackup,
  onForceRestore
}: GameSettingsSectionProps) {
  return (
    <PanelSection title="GAME">
      <PanelSectionRow>
        <div className="sdh-ludusavi-game-dropdown" style={{ width: "100%" }}>
          <DropdownItem
            layout="below"
            menuLabel="Select Game"
            highlightOnFocus={true}
            focusable={true}
            bottomSeparator="none"
            disabled={isBusy}
            rgOptions={gamesDropdownOptions}
            selectedOption={selectedGame}
            onChange={onGameChange}
            renderButtonValue={(value: any) => (
              <span className="sdh-ludusavi-game-dropdown-value">{value}</span>
            )}
          />
        </div>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field
          highlightOnFocus={false}
          focusable={false}
          padding="standard"
          bottomSeparator="none"
          childrenLayout="below"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "6px", width: "100%" }}>
            {/* Status Row */}
            <div style={{ display: "flex", width: "100%", alignItems: "center", fontSize: "12px" }}>
              <span style={{ width: "110px", flexShrink: 0 }}>
                <CompactFieldLabel>Status:</CompactFieldLabel>
              </span>
              <div style={{ flexGrow: 1, color: "#cbd5e1", minWidth: 0, textAlign: "left" }}>
                {isBusy && busyLabel === "Loading" ? (
                  <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Loading game list...</span>
                ) : isBusy && busyLabel === "Refreshing games" ? (
                  <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Game refresh in progress...</span>
                ) : isBusy && busyLabel === "Backup running" ? (
                  <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Backup in progress...</span>
                ) : isBusy && busyLabel === "Restore running" ? (
                  <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Restore in progress...</span>
                ) : (
                  selectedStatus ? statusLabels[selectedStatus.status] : "No Ludusavi games found"
                )}
              </div>
            </div>

            {/* Last Operation Row */}
            {selectedHistory && !isBusy && (
              <div style={{ display: "flex", width: "100%", alignItems: "baseline", fontSize: "12px" }}>
                <span style={{ width: "110px", flexShrink: 0 }}>
                  <CompactFieldLabel>Last Operation:</CompactFieldLabel>
                </span>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    flexGrow: 1,
                    minWidth: 0,
                    textAlign: "left"
                  }}
                >
                  <div
                    style={{
                      color: selectedHistory.status === "failed" ? "#f87171" : "#cbd5e1",
                      whiteSpace: "normal",
                      wordBreak: "break-word"
                    }}
                  >
                    {getLastOperationText(
                      selectedHistory.status,
                      selectedHistory.reason,
                      selectedHistory.message
                    )}
                  </div>
                  {(() => {
                    if (!selectedHistory.timestamp) return null;
                    const parts = selectedHistory.timestamp.split(/[T ]/);
                    const timePart = parts[1]?.split(".")[0];
                    if (!timePart) return null;

                    return (
                      <div
                        style={{
                          fontSize: "12px",
                          opacity: 0.65,
                          marginTop: "2px",
                          fontVariantNumeric: "tabular-nums"
                        }}
                      >
                        ({formatDateMDY(selectedHistory.timestamp)} {formatTime12h(timePart)})
                      </div>
                    );
                  })()}
                </div>
              </div>
            )}
          </div>
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <SpinnerButton
          layout="below"
          highlightOnFocus={true}
          bottomSeparator="none"
          disabled={isBusy || !selectedStatus}
          loading={busyLabel === "Backup running"}
          onClick={onForceBackup}
        >
          Force Backup
        </SpinnerButton>
      </PanelSectionRow>

      <PanelSectionRow>
        <SpinnerButton
          layout="below"
          highlightOnFocus={true}
          disabled={isBusy || selectedStatus?.status !== "has_backup"}
          loading={busyLabel === "Restore running"}
          onClick={onForceRestore}
        >
          Force Restore
        </SpinnerButton>
      </PanelSectionRow>
    </PanelSection>
  );
}
