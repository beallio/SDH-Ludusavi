from pathlib import Path

# 1. Clean PluginUpdateSection.tsx
section_path = Path("src/components/PluginUpdateSection.tsx")
content = section_path.read_text()

# Remove unused imports and constants
lines = content.split("\n")
new_lines = []
skip = False
for i, line in enumerate(lines):
    if skip:
        if "}" in line and "from" in line:
            skip = False
        continue

    if line.startswith("import React, {"):
        line = 'import React from "react";'
    elif 'import { callable, toaster } from "@decky/api";' in line:
        line = 'import { callable } from "@decky/api";'
    elif (
        'import { PluginUpdateCandidate, UpdateCheckResult, UpdateChannel } from "../types";'
        in line
    ):
        line = 'import { PluginUpdateCandidate, UpdateChannel } from "../types";'
    elif "import {" in line and "checkForPluginUpdateCall" in lines[i + 1]:
        skip = True
        while i < len(lines) and '} from "../api/ludusaviRpc";' not in lines[i]:
            i += 1
        skip = False
        continue
    elif (
        "isDeckyInstallerAvailable," in line
        or "invokeDeckyInstaller," in line
        or "INSTALL_TYPE_UPDATE," in line
        or "INSTALL_TYPE_DOWNGRADE" in line
    ):
        if line.strip() == "INSTALL_TYPE_DOWNGRADE":
            continue
        continue
    elif line.startswith("function logUpdate"):
        skip = True
        continue
    elif line.startswith("function generateUpdateTraceId()"):
        skip = True
        continue
    elif line.startswith("interface InstalledOverride"):
        skip = True
        continue
    elif skip and line == "}":
        skip = False
        continue

    new_lines.append(line)

content = "\n".join(new_lines)
section_path.write_text(content)

# 2. Clean pluginUpdateController.tsx
controller_path = Path("src/controllers/pluginUpdateController.tsx")
content = controller_path.read_text()
lines = content.split("\n")
new_lines = []
for line in lines:
    if line.strip() == "isDeckyInstallerAvailable,":
        continue
    new_lines.append(line)

content = "\n".join(new_lines)
controller_path.write_text(content)

print("Cleaned up unused code")
