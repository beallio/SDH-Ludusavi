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

    import hashlib

    mtimes = [config_file.stat().st_mtime_ns]
    expected_hash_str = ",".join(str(m) for m in mtimes)
    expected_hash = int.from_bytes(
        hashlib.sha256(expected_hash_str.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )
    assert config_mtime == expected_hash
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


def test_composite_mtime_config_cache_manifest(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("backup:\n  path: /non/existent/path\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_client.config_path.return_value = str(config_file)

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter._cached_config_path = None

    # Base mtime
    hash1 = adapter.get_config_mtime_ns()

    # 1. Modify cache.yaml
    cache_file = tmp_path / "cache.yaml"
    cache_file.write_text("some cache content")
    hash2 = adapter.get_config_mtime_ns()
    assert hash2 != hash1

    # 2. Modify manifest.yaml
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("some manifest content")
    hash3 = adapter.get_config_mtime_ns()
    assert hash3 != hash2
    assert hash3 != hash1


def test_get_config_mtime_ns_stat_syscall_count(tmp_path: Path) -> None:
    from unittest.mock import patch

    config_file = tmp_path / "config.yaml"
    config_file.write_text("backup:\n  path: /non/existent/path\n", encoding="utf-8")

    # Create cache.yaml and manifest.yaml so they exist and are checked
    cache_file = tmp_path / "cache.yaml"
    cache_file.write_text("cache")
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("manifest")

    mock_client = MagicMock()
    mock_client.config_path.return_value = str(config_file)

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter._cached_config_path = None

    # Patch Path.stat to count calls
    original_stat = Path.stat
    stat_calls = []

    def mock_stat(self, *args, **kwargs):
        stat_calls.append(self)
        return original_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", mock_stat):
        adapter.get_config_mtime_ns()

    # Check that each sibling file was stat'ed exactly once (Path.resolve may also stat config_file)
    paths_stated = [str(p) for p in stat_calls]
    assert paths_stated.count(str(cache_file)) == 1
    assert paths_stated.count(str(manifest_file)) == 1


def test_get_config_mtime_ns_resolves_symlinks(tmp_path: Path) -> None:
    # Target directory where the real config and sibling files reside
    real_dir = tmp_path / "real-config"
    real_dir.mkdir()
    config_file = real_dir / "config.yaml"
    config_file.write_text("settings")
    cache_file = real_dir / "cache.yaml"
    cache_file.write_text("cache")
    manifest_file = real_dir / "manifest.yaml"
    manifest_file.write_text("manifest")

    # Another directory containing a symlink to the real config file
    symlink_dir = tmp_path / "symlink-dir"
    symlink_dir.mkdir()
    symlink_file = symlink_dir / "config.yaml"

    # Create the symlink
    symlink_file.symlink_to(config_file)

    mock_client = MagicMock()
    mock_client.config_path.return_value = str(symlink_file)

    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._client = mock_client
    adapter._cached_config_path = None

    # Retrieve mtime hash
    config_mtime = adapter.get_config_mtime_ns()

    # The expected hash is computed using real files because the symlink is resolved
    import hashlib

    mtimes = [
        config_file.stat().st_mtime_ns,
        cache_file.stat().st_mtime_ns,
        manifest_file.stat().st_mtime_ns,
    ]
    mtimes.sort()
    expected_hash_str = ",".join(str(m) for m in mtimes)
    expected_hash = int.from_bytes(
        hashlib.sha256(expected_hash_str.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )
    assert config_mtime == expected_hash
