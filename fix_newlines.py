with open("src/controllers/gameLifecycleController.tsx", "r") as f:
    content = f.read()

content = content.replace("\\n", "\n")

with open("src/controllers/gameLifecycleController.tsx", "w") as f:
    f.write(content)
