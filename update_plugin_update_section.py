with open("src/components/PluginUpdateSection.tsx", "r") as f:
    content = f.read()

import_hook = 'import { usePluginUpdateController } from "../controllers/pluginUpdateController";'
if import_hook not in content:
    content = content.replace("import {", f"{import_hook}\nimport {{", 1)

import_types = 'import { PluginUpdateCandidate } from "../types";'

start_index = content.find("export function PluginUpdateSection({")
end_index = content.find('const isLocalBuild = effectiveCurrentVersion.includes("+");')

replacement = """export function PluginUpdateSection({
  currentVersion,
  updateChannel,
  automaticUpdateChecks,
  onToggleUpdateChannel,
  onToggleAutomaticUpdateChecks,
  onInstallVersionConfirmed
}: PluginUpdateSectionProps) {
  const {
    effectiveCurrentVersion,
    candidate,
    checkResult,
    errorMessage: errorMsg,
    isChecking,
    isInstalling,
    isHandoffPending,
    installedReleasePublishedAt,
    checkNow,
    install: handleInstall,
  } = usePluginUpdateController({
    currentVersion,
    updateChannel,
    automaticUpdateChecks,
    onInstallVersionConfirmed,
  });

  const handleToggleChannel = (checked: boolean) => {
    if (checked) {
      showModal(
        <ConfirmModal
          strTitle="Enable Development Releases?"
          onOK={() => onToggleUpdateChannel(true)}
        >
          <div style={{ fontSize: "14px", color: "#cbd5e1" }}>
            Includes prerelease builds intended for testing. These builds may contain regressions.
          </div>
        </ConfirmModal>
      );
    } else {
      onToggleUpdateChannel(false);
    }
  };

  const handleInstallClick = (targetCandidate: PluginUpdateCandidate) => {
    if (targetCandidate.action === "downgrade_to_stable") {
      showModal(
        <ConfirmModal
          strTitle="Revert to Stable?"
          onOK={() => handleInstall(targetCandidate)}
        >
          <div style={{ fontSize: "14px", color: "#cbd5e1" }}>
            Are you sure you want to revert to stable v{targetCandidate.version}? This is a downgrade and could result in data loss or configuration issues.
          </div>
        </ConfirmModal>
      );
    } else {
      void handleInstall(targetCandidate);
    }
  };

  """

if start_index != -1 and end_index != -1:
    content = content[:start_index] + replacement + content[end_index:]

with open("src/components/PluginUpdateSection.tsx", "w") as f:
    f.write(content)

print("Updated PluginUpdateSection.tsx")
