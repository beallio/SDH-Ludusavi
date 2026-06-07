from __future__ import annotations

import pytest

from sdh_ludusavi.syncthing import config


def test_resolve_credentials_reports_missing_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYNCTHING_API_KEY", raising=False)
    monkeypatch.delenv("SYNCTHING_API_URL", raising=False)
    monkeypatch.setattr(config, "discover_syncthing_config", lambda explicit_config=None: None)
    monkeypatch.setattr(config, "candidate_config_files", lambda: [])

    with pytest.raises(config.SyncthingNotConfiguredError):
        config.resolve_api_credentials()
