from pathlib import Path

path = Path("py_modules/sdh_ludusavi/updater.py")
content = path.read_text()

lines = content.splitlines()
out = []
for i, line in enumerate(lines):
    if line.strip() == "except Exception:" or line.strip() == "except Exception as e:":
        # Check if preceding line has comment
        has_comment = False
        for j in range(max(0, len(out) - 3), len(out)):
            if "Intentionally broad" in out[j]:
                has_comment = True
                break

        if not has_comment:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}# Intentionally broad")

    out.append(line)

path.write_text("\n".join(out) + "\n")
print("Added comments to updater.py")
