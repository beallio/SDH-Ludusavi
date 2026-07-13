with open("src/controllers/gameLifecycleController.tsx", "r") as f:
    lines = f.readlines()

out = []
seen = False
for line in lines:
    if "import { createPauseLease, type PauseLeaseHandle } from" in line:
        if not seen:
            seen = True
            out.append(line)
        else:
            continue
    else:
        out.append(line)

with open("src/controllers/gameLifecycleController.tsx", "w") as f:
    f.writelines(out)
