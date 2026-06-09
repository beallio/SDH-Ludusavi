import re
from pathlib import Path


def fix_file(file_path):
    path = Path(file_path)
    content = path.read_text()

    # 3. Remove the function definition BEFORE replacing usages
    content = re.sub(
        r"def _sanitize_name\(name: str \| None\) -> str:\n    if not name:\n        return \"\"\n    return \" \"\.join\(name\.split\(\)\)\n*",
        "",
        content,
    )

    # 1. Replace usages
    content = content.replace("_sanitize_name(", "sanitize_game_name(")

    # 2. Add import near the top
    import_line = "from sdh_ludusavi.game_names import sanitize_game_name\n"
    if "from sdh_ludusavi.game_names" not in content:
        lines = content.splitlines(keepends=True)
        last_import_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("import ") or line.startswith("from "):
                last_import_idx = i
        lines.insert(last_import_idx + 1, import_line)
        content = "".join(lines)

    path.write_text(content)


fix_file("py_modules/sdh_ludusavi/lifecycle.py")
fix_file("py_modules/sdh_ludusavi/registry.py")
fix_file("py_modules/sdh_ludusavi/service.py")
