from __future__ import annotations
from sdh_ludusavi.service import SDHLudusaviService


class FakeAdapter:
    def refresh_statuses(self):
        return []

    def compare_recency(self, name):
        return "local_current"

    def backup(self, name):
        return {"ok": True}

    def restore(self, name):
        return {"ok": True}

    def get_aliases(self):
        return {}

    def get_versions(self):
        return {"ludusavi": "0.0.0"}


def test_game_name_sanitization(tmp_path):
    state_file = tmp_path / "state.json"
    service = SDHLudusaviService(adapter=FakeAdapter(), state_path=state_file)

    malicious_name = "Hades\n[ERROR] Spoofed error"

    # Test set_selected_game
    service.set_selected_game(malicious_name)
    assert "\n" not in service._selected_game
    assert service._selected_game == "Hades [ERROR] Spoofed error"

    # Test backup logging
    service.force_backup(malicious_name)
    log_entry = service.get_recent_logs()[-1]
    assert "\n" not in log_entry["message"]
    assert "Hades [ERROR] Spoofed error" in log_entry["message"]
