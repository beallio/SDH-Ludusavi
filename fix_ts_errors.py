from pathlib import Path

# 1. Fix pluginUpdateController.tsx
controller_path = Path("src/controllers/pluginUpdateController.tsx")
content = controller_path.read_text()
content = content.replace(
    'import { toaster } from "@decky/ui";', 'import { toaster } from "@decky/api";'
)
controller_path.write_text(content)

# 2. Fix PluginUpdateSection.tsx
section_path = Path("src/components/PluginUpdateSection.tsx")
content = section_path.read_text()
content = content.replace(
    'checkForUpdates({ force: true, notify: true, source: "manual" })', "checkNow()"
)
section_path.write_text(content)

print("Fixed typescript errors")
