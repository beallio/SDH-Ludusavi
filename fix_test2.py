import re
from pathlib import Path

content = Path("tests/test_updater_service.py").read_text()

# Replace any occurrence of the faulty read_text logic
content = re.sub(
    r"settings_data = json\.loads\(settings_file\.read_text\(\)\) if settings_file\.read_text\(\) else \{\}",
    "settings_data = json.loads(settings_file.read_text()) if settings_file.exists() and settings_file.read_text() else {}",
    content,
)

content = re.sub(
    r"cache_data = json\.loads\(cache_file\.read_text\(\)\) if cache_file\.read_text\(\) else \{\}",
    "cache_data = json.loads(cache_file.read_text()) if cache_file.exists() and cache_file.read_text() else {}",
    content,
)

# And fix any leftover bugs in the tests (like service._save_state vs service._save_callback)
content = content.replace("service._save_state()", "service._save_callback()")
# Wait, set_update_channel is set_channel
content = content.replace("service.set_update_channel", "service.set_channel")
content = content.replace("service.set_automatic_update_checks", "service.set_automatic_checks")

Path("tests/test_updater_service.py").write_text(content)
print("Fixed test_updater_service.py")
