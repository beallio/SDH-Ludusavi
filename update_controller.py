import re

with open("src/controllers/gameLifecycleController.tsx", "r") as f:
    content = f.read()

# Add to LifecycleRpc:
content = re.sub(
    r"  resumeGameProcess: \(pid: number\) => Promise<RpcResult<ProcessSignalResult>>;",
    '  resumeGameProcess: (pid: number) => Promise<RpcResult<ProcessSignalResult>>;\\n  renewGameProcessPause: (pid: number, leaseId: string) => Promise<RpcResult<import("../types").RenewGameProcessPauseResult>>;',
    content,
)

content = content.replace(
    "import type {",
    'import { createPauseLease, type PauseLeaseHandle } from "./launchGateLease";\\nimport type {',
)

# Add PauseGameProcessResult to imports
content = content.replace(
    "ProcessSignalResult,", "ProcessSignalResult,\\n  PauseGameProcessResult,"
)

# Change pauseGameProcess signature
content = content.replace(
    "  pauseGameProcess: (pid: number) => Promise<RpcResult<ProcessSignalResult>>;",
    "  pauseGameProcess: (pid: number) => Promise<RpcResult<PauseGameProcessResult>>;",
)


# Modify handleAppStart
# Find:
"""
      const shouldPauseLaunch = autoSyncEnabled && tracked && typeof instanceID === "number" && instanceID > 1;
      if (shouldPauseLaunch) {
        const pauseResult = await pauseGameProcess(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") state.paused = true;
      }
"""

replacement = """      let pauseHandle: PauseLeaseHandle | undefined;
      const shouldPauseLaunch = autoSyncEnabled && tracked && typeof instanceID === "number" && instanceID > 1;
      if (shouldPauseLaunch) {
        const pauseResult = await pauseGameProcess(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
          state.paused = true;
          // type cast rpc because createPauseLease expects LudusaviRpc but LifecycleRpc has the needed methods
          pauseHandle = createPauseLease(rpc as any, instanceID, pauseResult.lease_id, { warn: (msg) => log("warn", msg), error: (msg, e) => log("error", msg + String(e)) });
        }
      }"""

content = content.replace(
    """      const shouldPauseLaunch = autoSyncEnabled && tracked && typeof instanceID === "number" && instanceID > 1;
      if (shouldPauseLaunch) {
        const pauseResult = await pauseGameProcess(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") state.paused = true;
      }""",
    replacement,
)

# In finally block:
# """        else if (cmd.type === "resumeProcess") {
#           try { await resumeGameProcess(cmd.instanceID); } catch (err) { log("error", `Failed to resume process: ${err}`); }
#         }"""
# change to:
# """        else if (cmd.type === "resumeProcess") {
#           if (pauseHandle) { await pauseHandle.release(); }
#           else { try { await resumeGameProcess(cmd.instanceID); } catch (err) { log("error", `Failed to resume process: ${err}`); } }
#         }"""

replacement_finally = """        else if (cmd.type === "resumeProcess") {
          if (pauseHandle) { await pauseHandle.release(); }
          else { try { await resumeGameProcess(cmd.instanceID); } catch (err) { log("error", `Failed to resume process: ${err}`); } }
        }"""

content = content.replace(
    """        else if (cmd.type === "resumeProcess") {
          try { await resumeGameProcess(cmd.instanceID); } catch (err) { log("error", `Failed to resume process: ${err}`); }
        }""",
    replacement_finally,
)

with open("src/controllers/gameLifecycleController.tsx", "w") as f:
    f.write(content)
