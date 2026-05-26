from pathlib import Path
import inspect
from unittest.mock import MagicMock

import pyludusavi

from sdh_ludusavi import ludusavi
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
    import pytest

    mock_client = MagicMock()
    mock_client.config_path.return_value = "/non/existent/path"

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter._cached_config_path = None

    # First call caches the path but stat fails
    with pytest.raises(Exception):
        adapter.get_config_mtime_ns()
    assert mock_client.config_path.call_count == 1
    assert adapter._cached_config_path == "/non/existent/path"

    # Second call should still use the cached path and not re-call config_path()
    with pytest.raises(Exception):
        adapter.get_config_mtime_ns()
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


def test_pyludusavi_adapter_caches_aliases_by_config_mtime() -> None:
    mock_client = MagicMock()
    mock_client.config_show.return_value.data = {
        "customGames": [{"name": "Shortcut Name", "alias": "The Witcher 3: Wild Hunt"}]
    }

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter.get_config_mtime_ns = MagicMock(return_value=100)

    first_aliases = adapter.get_aliases()
    first_aliases["Shortcut Name"] = "mutated"
    second_aliases = adapter.get_aliases()

    assert second_aliases == {"Shortcut Name": "The Witcher 3: Wild Hunt"}
    assert mock_client.config_show.call_count == 1


def test_pyludusavi_adapter_reloads_aliases_when_config_mtime_changes() -> None:
    mock_client = MagicMock()
    first_response = MagicMock()
    first_response.data = {"customGames": [{"name": "Shortcut Name", "alias": "Old Title"}]}
    second_response = MagicMock()
    second_response.data = {"customGames": [{"name": "Shortcut Name", "alias": "New Title"}]}
    mock_client.config_show.side_effect = [first_response, second_response]

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter.get_config_mtime_ns = MagicMock(side_effect=[100, 101])

    assert adapter.get_aliases() == {"Shortcut Name": "Old Title"}
    assert adapter.get_aliases() == {"Shortcut Name": "New Title"}
    assert mock_client.config_show.call_count == 2


def test_pyludusavi_adapter_does_not_reuse_alias_cache_when_mtime_unavailable() -> None:
    mock_client = MagicMock()
    mock_client.config_show.return_value.data = {
        "customGames": [{"name": "Shortcut Name", "alias": "The Witcher 3: Wild Hunt"}]
    }

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter.get_config_mtime_ns = MagicMock(side_effect=RuntimeError("mtime unavailable"))

    assert adapter.get_aliases() == {"Shortcut Name": "The Witcher 3: Wild Hunt"}
    assert adapter.get_aliases() == {"Shortcut Name": "The Witcher 3: Wild Hunt"}
    assert mock_client.config_show.call_count == 2


def test_pyludusavi_adapter_lazy_alias_lock_initialization_is_guarded() -> None:
    source = Path(ludusavi.__file__).read_text(encoding="utf-8")
    get_aliases_source = inspect.getsource(PyludusaviAdapter.get_aliases)

    assert "_ALIASES_INIT_LOCK = threading.Lock()" in source
    assert "with _ALIASES_INIT_LOCK:" in get_aliases_source


def test_pyludusavi_adapter_does_not_return_stale_aliases_after_known_config_change() -> None:
    mock_client = MagicMock()
    first_response = MagicMock()
    first_response.data = {"customGames": [{"name": "Shortcut Name", "alias": "Old Title"}]}
    mock_client.config_show.side_effect = [first_response, pyludusavi.LudusaviError("failed")]

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter.get_config_mtime_ns = MagicMock(side_effect=[100, 101])

    assert adapter.get_aliases() == {"Shortcut Name": "Old Title"}
    assert adapter.get_aliases() == {}
