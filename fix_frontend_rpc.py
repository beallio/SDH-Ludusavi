import re
from pathlib import Path

# 1. Update src/types/index.ts
types_path = Path("src/types/index.ts")
types_content = types_path.read_text()

new_types = """
export type PendingUpdateInstall = {
  version: string;
  tag: string;
  channel: UpdateChannel;
  published_at: string;
  requested_at: string;
  handoff_confirmed_at?: string;
  update_trace_id?: string | null;
};

export type UpdateCheckContext = {
  update_channel: UpdateChannel;
  automatic_update_checks: boolean;
  installed_version: string;
  effective_installed_version: string;
  last_checked_at: string | null;
  last_checked_channel: UpdateChannel | null;
  last_available_tag: string | null;
  last_notified_tag: string | null;
  installed_release_tag: string | null;
  installed_release_published_at: string | null;
  pending_update_install: PendingUpdateInstall | null;
  rate_limited_until: string | null;
};

export type UpdateInstallRequest = PluginUpdateCandidate & { updateTraceId: string };
"""

if "export type PendingUpdateInstall" not in types_content:
    # Append right before the end
    types_content += "\n" + new_types.strip() + "\n"
    types_path.write_text(types_content)

# 2. Update src/api/ludusaviRpc.ts
rpc_path = Path("src/api/ludusaviRpc.ts")
rpc_content = rpc_path.read_text()

if "UpdateCheckContext" not in rpc_content:
    rpc_content = rpc_content.replace(
        '} from "../types";',
        '  PluginUpdateCandidate,\n  UpdateCheckContext,\n  UpdateCheckResult\n} from "../types";',
    )

new_rpcs = """
export const checkForPluginUpdateCall = callable<[currentVersion: string, force: boolean], UpdateCheckResult>("check_for_plugin_update");
export const revalidatePluginUpdateCall = callable<[candidate: PluginUpdateCandidate], UpdateCheckResult>("revalidate_plugin_update");
export const recordUpdateInstallRequestedCall = callable<[candidate: PluginUpdateCandidate], UpdateCheckResult>("record_update_install_requested");
export const confirmUpdateInstallHandoffCall = callable<[version: string], UpdateCheckResult>("confirm_update_install_handoff");
export const clearPendingUpdateInstallCall = callable<[version: string], UpdateCheckResult>("clear_pending_update_install");
export const getUpdateCheckContextCall = callable<[], UpdateCheckContext>("get_update_check_context");
"""

if "checkForPluginUpdateCall" not in rpc_content:
    rpc_content += "\n" + new_rpcs.strip() + "\n"
    rpc_path.write_text(rpc_content)

# 3. Update src/components/PluginUpdateSection.tsx
section_path = Path("src/components/PluginUpdateSection.tsx")
section_content = section_path.read_text()

# Remove local declarations
section_content = re.sub(r"const checkForPluginUpdateCall = callable.*?;\n", "", section_content)
section_content = re.sub(r"const revalidatePluginUpdateCall = callable.*?;\n", "", section_content)
section_content = re.sub(
    r"const recordUpdateInstallRequestedCall = callable.*?;\n", "", section_content
)
section_content = re.sub(
    r"const confirmUpdateInstallHandoffCall = callable.*?;\n", "", section_content
)
section_content = re.sub(
    r"const clearPendingUpdateInstallCall = callable.*?;\n", "", section_content
)
section_content = re.sub(r"const getUpdateCheckContextCall = callable.*?;\n", "", section_content)

# Add import
if "checkForPluginUpdateCall" not in section_content:
    import_stmt = """import {
  checkForPluginUpdateCall,
  revalidatePluginUpdateCall,
  recordUpdateInstallRequestedCall,
  confirmUpdateInstallHandoffCall,
  clearPendingUpdateInstallCall,
  getUpdateCheckContextCall
} from "../api/ludusaviRpc";\n"""

    # insert after the other imports
    lines = section_content.splitlines(keepends=True)
    last_import_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("import "):
            last_import_idx = i
    lines.insert(last_import_idx + 1, import_stmt)
    section_content = "".join(lines)

section_path.write_text(section_content)
print("Applied RPC fixes")
