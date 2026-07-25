import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Settings } from "../../types";

const { toggleProps } = vi.hoisted(() => ({
  toggleProps: [] as Array<Record<string, unknown>>,
}));

vi.mock("@decky/ui", () => ({
  PanelSection: ({ children }: { children: unknown }) => children,
  PanelSectionRow: ({ children }: { children: unknown }) => children,
  ToggleField: (props: Record<string, unknown>) => {
    toggleProps.push(props);
    return null;
  },
}));

vi.mock("react/jsx-dev-runtime", () => ({
  jsxDEV: (type: unknown, props: Record<string, unknown>) =>
    typeof type === "function"
      ? (type as (componentProps: Record<string, unknown>) => unknown)(props)
      : { type, props },
  Fragment: Symbol("Fragment"),
}));

import { NotificationSettingsSection } from "./NotificationSettingsSection";

const settings: Settings = {
  auto_sync_enabled: true,
  sync_disabled_games: [],
  selected_game: "",
  notifications: {
    enabled: true,
    auto_sync_progress: true,
    auto_sync_results: true,
    manual_operations: true,
    refresh_status: true,
    failures_errors: true,
    update_available: true,
  },
  update_channel: "stable",
  automatic_update_checks: true,
  debug_logging: false,
};

describe("NotificationSettingsSection", () => {
  beforeEach(() => {
    toggleProps.length = 0;
  });

  it("renders the plugin update toggle and delegates category changes", () => {
    const onToggleNotificationSetting = vi.fn();

    NotificationSettingsSection({
      settings,
      isBusy: false,
      onToggleNotificationSetting,
    });

    const updateToggle = toggleProps.find(({ label }) => label === "Plugin Updates");
    expect(updateToggle).toBeDefined();

    const onChange = updateToggle?.onChange as (enabled: boolean) => void;
    onChange(false);

    expect(onToggleNotificationSetting).toHaveBeenCalledWith("update_available", false);
  });
});
