with open("src/controllers/gameLifecycleController.test.ts", "r") as f:
    content = f.read()

content = content.replace(
    "pauseGameProcess: vi.fn(),",
    "pauseGameProcess: vi.fn(),\\n      renewGameProcessPause: vi.fn(),",
)

with open("src/controllers/gameLifecycleController.test.ts", "w") as f:
    f.write(content)
