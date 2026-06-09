import re
from pathlib import Path

test_file = Path("tests/test_frontend_static.py")
content = test_file.read_text()


def replacer_comp_content(match):
    return 'comp_content = Path("src/components/PluginUpdateSection.tsx").read_text(encoding="utf-8") + "\\n" + Path("src/controllers/pluginUpdateController.tsx").read_text(encoding="utf-8")'


content = re.sub(
    r'comp_content = comp_path\.read_text\(encoding="utf-8"\)', replacer_comp_content, content
)

test_file.write_text(content)
print("Patched test_frontend_static.py for comp_content")
