with open("src/controllers/gameLifecycleController.tsx", "r") as f:
    content = f.read()

content = content.replace(
    "    try {\\n      let pauseHandle: PauseLeaseHandle | undefined;",
    "    let pauseHandle: PauseLeaseHandle | undefined;\\n    try {",
)

with open("src/controllers/gameLifecycleController.tsx", "w") as f:
    f.write(content)
