import re
from pathlib import Path

test_file = Path("tests/test_frontend_static.py")
content = test_file.read_text()


def replacer(match):
    return 'comp = Path("src/components/PluginUpdateSection.tsx").read_text(encoding="utf-8") + "\\n" + Path("src/controllers/pluginUpdateController.tsx").read_text(encoding="utf-8")'


content = re.sub(
    r'comp_path = Path\("src/components/PluginUpdateSection\.tsx"\)\n\s+assert comp_path\.exists\(\)(, ".*?")?\n\s+comp = comp_path\.read_text\(encoding="utf-8"\)',
    replacer,
    content,
)

content = re.sub(
    r'comp = Path\("src/components/PluginUpdateSection\.tsx"\)\.read_text\(encoding="utf-8"\)',
    replacer,
    content,
)


def replacer_path(match):
    return 'content = Path("src/components/PluginUpdateSection.tsx").read_text(encoding="utf-8") + "\\n" + Path("src/controllers/pluginUpdateController.tsx").read_text(encoding="utf-8")'


content = re.sub(
    r'path = Path\("src/components/PluginUpdateSection\.tsx"\)\n\s+assert path\.exists\(\), "src/components/PluginUpdateSection\.tsx does not exist"\n\s+content = path\.read_text\(encoding="utf-8"\)',
    replacer_path,
    content,
)

test_file.write_text(content)
print("Patched test_frontend_static.py")
