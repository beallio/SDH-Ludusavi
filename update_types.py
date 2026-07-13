import re

with open("src/types/index.ts", "r") as f:
    content = f.read()

# Replace:
# export type PauseGameProcessResult =
#   | { status: "paused"; pid: number }
#   | { status: "failed"; pid?: number; message: string };

content = re.sub(
    r'export type PauseGameProcessResult =[\s\S]*?\| \{ status: "failed"; pid\?: number; message: string \};',
    """export type PauseGameProcessResult =
  | { status: "paused"; pid: number; lease_id: string; lease_ttl_seconds: number }
  | { status: "failed"; pid?: number; message: string };

export type RenewGameProcessPauseResult =
  | { status: "renewed"; pid: number; lease_ttl_seconds: number }
  | { status: "failed"; pid?: number; message: string };""",
    content,
)

with open("src/types/index.ts", "w") as f:
    f.write(content)
