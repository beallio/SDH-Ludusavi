import re
from pathlib import Path

content = Path("tests/test_updater_service.py").read_text()

# Replace service instantiation
replacement = """    import json
    import threading
    from sdh_ludusavi.updater import PluginUpdater
    import datetime
    import time
    class MockClient:
        pass
    service = PluginUpdater(
        state_lock=threading.RLock(),
        save_callback=lambda: None,
        log_callback=lambda l, m: None,
        release_client=MockClient(),
        version_resolver=lambda: "0.2.0",
        now=lambda: datetime.datetime.now(datetime.timezone.utc),
        monotonic=time.monotonic
    )
    settings_data = json.loads(settings_file.read_text()) if settings_file.read_text() else {}
    cache_data = json.loads(cache_file.read_text()) if cache_file.read_text() else {}
    service.load_state(settings_data, cache_data)"""

content = re.sub(
    r"    store = JsonSettingsStore\(settings_file\)\n    service = SDHLudusaviService\(settings_store=store, cache_path=cache_file\)",
    replacement,
    content,
)

content = content.replace(
    "from sdh_ludusavi.service import SDHLudusaviService",
    "from sdh_ludusavi.updater import PluginUpdater",
)
content = content.replace("service._save_state()", "service._save_callback()")

Path("tests/test_updater_service.py").write_text(content)
print("Updated test_updater_service.py")
