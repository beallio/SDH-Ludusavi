from pathlib import Path
from unittest.mock import MagicMock
from sdh_ludusavi.ludusavi import PyludusaviAdapter


def test_pyludusavi_adapter_caches_config_path(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("settings: {}")

    mock_client = MagicMock()
    mock_client.config_path.return_value = str(config_file)

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter._cached_config_path = None

    # First call should invoke client.config_path()
    mtime1 = adapter.get_config_mtime_ns()
    assert mtime1 is not None
    assert mock_client.config_path.call_count == 1
    assert adapter._cached_config_path == str(config_file)

    # Second call should use the cache
    mtime2 = adapter.get_config_mtime_ns()
    assert mtime2 == mtime1
    assert mock_client.config_path.call_count == 1


def test_pyludusavi_adapter_preserves_cached_path_on_stat_failure() -> None:
    mock_client = MagicMock()
    mock_client.config_path.return_value = "/non/existent/path"

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter._cached_config_path = None

    # First call caches the path but stat fails
    mtime1 = adapter.get_config_mtime_ns()
    assert mtime1 is None
    assert mock_client.config_path.call_count == 1
    assert adapter._cached_config_path == "/non/existent/path"

    # Second call should still use the cached path and not re-call config_path()
    mtime2 = adapter.get_config_mtime_ns()
    assert mtime2 is None
    assert mock_client.config_path.call_count == 1


def test_pyludusavi_adapter_reuses_diagnostic_first_load_probes(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("backup:\n  path: /home/deck/ludusavi-backups\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_client.command_prefix = ["flatpak", "run", "com.github.mtkennerly.ludusavi"]
    mock_client.version.return_value = "ludusavi 0.31.0"
    mock_client.config_path.return_value = str(config_file)
    mock_client.config_show.return_value.data = {"backup": {"path": "/home/deck/ludusavi-backups"}}

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter._cached_config_path = None

    diagnostics = adapter.get_diagnostics()
    versions = adapter.get_versions()
    config_mtime = adapter.get_config_mtime_ns()

    assert diagnostics["version"] == "0.31.0"
    assert versions["ludusavi"] == "0.31.0"
    assert config_mtime == config_file.stat().st_mtime_ns
    assert mock_client.version.call_count == 1
    assert mock_client.config_path.call_count == 1
