import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

import type { NotificationSettings, Settings } from "../../types";

type NotificationSettingsSectionProps = {
  settings: Settings;
  isBusy: boolean;
  onToggleNotificationSetting: (key: keyof NotificationSettings, enabled: boolean) => void;
};

export function NotificationSettingsSection({
  settings,
  isBusy,
  onToggleNotificationSetting
}: NotificationSettingsSectionProps) {
  return (
    <PanelSection title="Notifications">
      <PanelSectionRow>
        <ToggleField
          label="All Notifications"
          description="Enables or silences all SDH-Ludusavi toast notifications."
          bottomSeparator="standard"
          checked={settings.notifications.enabled}
          disabled={isBusy}
          onChange={(enabled: boolean) => onToggleNotificationSetting("enabled", enabled)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Manual Operations"
          description="Shows toasts for Force Backup and Force Restore results."
          bottomSeparator="standard"
          checked={settings.notifications.manual_operations}
          disabled={!settings.notifications.enabled || isBusy}
          onChange={(enabled: boolean) => onToggleNotificationSetting("manual_operations", enabled)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Refresh Status"
          description="Shows toasts when the game list refresh completes or fails."
          bottomSeparator="standard"
          checked={settings.notifications.refresh_status}
          disabled={!settings.notifications.enabled || isBusy}
          onChange={(enabled: boolean) => onToggleNotificationSetting("refresh_status", enabled)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Failures and Errors"
          description="Shows warning toasts when sync or Ludusavi operations fail."
          bottomSeparator="none"
          checked={settings.notifications.failures_errors}
          disabled={!settings.notifications.enabled || isBusy}
          onChange={(enabled: boolean) => onToggleNotificationSetting("failures_errors", enabled)}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
