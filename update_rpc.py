import re

with open("src/api/ludusaviRpc.ts", "r") as f:
    content = f.read()

# I need to add renewGameProcessPause:
new_rpc = """  async pauseGameProcess(pid: number): Promise<PauseGameProcessResult> {
    return (await this.serverAPI.callPluginMethod("pause_game_process", { pid }))
      .result as PauseGameProcessResult;
  }

  async renewGameProcessPause(pid: number, leaseId: string): Promise<RenewGameProcessPauseResult> {
    return (await this.serverAPI.callPluginMethod("renew_game_process_pause", { pid, lease_id: leaseId }))
      .result as RenewGameProcessPauseResult;
  }"""

content = re.sub(
    r'  async pauseGameProcess\(pid: number\): Promise<PauseGameProcessResult> \{\n    return \(await this\.serverAPI\.callPluginMethod\("pause_game_process", \{ pid \}\)\)\n      \.result as PauseGameProcessResult;\n  \}',
    new_rpc,
    content,
)

content = content.replace(
    "PauseGameProcessResult,", "PauseGameProcessResult, RenewGameProcessPauseResult,"
)

with open("src/api/ludusaviRpc.ts", "w") as f:
    f.write(content)
