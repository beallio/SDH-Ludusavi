from __future__ import annotations
import os
from unittest.mock import patch
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


def test_env_variable_logging_redaction(tmp_path):
    state_file = tmp_path / "state.json"

    # Mock environment with sensitive and path-heavy variables
    mock_env = {
        "LANG": "en_US.UTF-8",
        "DECKY_VERSION": "3.0.0",
        "DECKY_TOKEN": "secret-token",
        "HOME": "/home/deck",
        "DECKY_PLUGIN_RUNTIME_DIR": "/tmp/decky-runtime",
        "FLATPAK_ID": "com.github.mtkennerly.ludusavi",
        "SOME_OTHER_VAR": "value",
    }

    with patch.dict(os.environ, mock_env, clear=True):
        service = SDHLudusaviService(adapter=FakeAdapter(), state_path=state_file)

    # Check the log for environment variables
    # The log message starts with "Filtered environment variables:" (current)
    # or "Environment summary:" (proposed)
    env_log = next(
        (entry for entry in service.get_recent_logs() if "environment" in entry["message"].lower()),
        None,
    )
    assert env_log is not None

    log_content = env_log["message"]

    # SENSITIVE: DECKY_TOKEN should NOT be in the log
    assert "DECKY_TOKEN" not in log_content
    assert "secret-token" not in log_content

    # NOT ALLOWLISTED: HOME and SOME_OTHER_VAR should NOT be in the log
    assert "HOME" not in log_content
    assert "SOME_OTHER_VAR" not in log_content

    # REDACTED: DECKY_PLUGIN_RUNTIME_DIR should be redacted (e.g., "<set>")
    # Currently it is NOT redacted.
    assert "/tmp/decky-runtime" not in log_content
    assert "<set>" in log_content or "DECKY_PLUGIN_RUNTIME_DIR" not in log_content

    # ALLOWED: LANG, DECKY_VERSION, FLATPAK_ID should be there
    assert "LANG" in log_content
    assert "DECKY_VERSION" in log_content
    assert "FLATPAK_ID" in log_content
