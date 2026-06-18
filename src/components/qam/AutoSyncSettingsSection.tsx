import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

import type { Settings } from "../../types";
import { SpinnerButton } from "./SpinnerButton";

type AutoSyncSettingsSectionProps = {
  settings: Settings;
  isBusy: boolean;
  refreshLoading: boolean;
  onToggleAutoSync: (enabled: boolean) => void;
  onToggleDebugLogging: (enabled: boolean) => void;
  onRefreshGames: () => void;
};

export function AutoSyncSettingsSection({
  settings,
  isBusy,
  refreshLoading,
  onToggleAutoSync,
  onToggleDebugLogging,
  onRefreshGames
}: AutoSyncSettingsSectionProps) {
  return (
    <PanelSection title="GLOBAL">
      <PanelSectionRow>
        <ToggleField
          label="Automatic Sync"
          description="Runs Ludusavi automatically when configured games start or exit."
          bottomSeparator="none"
          checked={settings.auto_sync_enabled}
          disabled={isBusy}
          onChange={(enabled: boolean) => onToggleAutoSync(enabled)}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <ToggleField
          label="Debug Logging"
          description="Enables verbose logging for troubleshooting."
          bottomSeparator="none"
          checked={settings.debug_logging}
          disabled={isBusy}
          onChange={(enabled: boolean) => onToggleDebugLogging(enabled)}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <SpinnerButton
          layout="below"
          highlightOnFocus={true}
          disabled={isBusy}
          loading={refreshLoading}
          onClick={onRefreshGames}
        >
          Refresh Games
        </SpinnerButton>
      </PanelSectionRow>
    </PanelSection>
  );
}
