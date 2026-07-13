import ast
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock

from pyludusavi import LudusaviError
from sdh_ludusavi.ludusavi import PyludusaviAdapter
from sdh_ludusavi.service import SDHLudusaviService
from sdh_ludusavi.persistence import JsonSettingsStore


def test_no_bare_except_and_broad_except_comment_check():
    """
    Enforce that:
    1. There are no bare `except:` blocks at all.
    2. Every `except Exception` block has a comment containing "Intentionally broad"
       within the 1-3 lines preceding the 'except' keyword.
    """
    dir_path = Path("py_modules/sdh_ludusavi")
    files_to_check = sorted(list(dir_path.glob("*.py")))

    for filepath in files_to_check:
        assert filepath.exists(), f"{filepath} does not exist"
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
        lines = source.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # 1. Check for bare except:
                if node.type is None:
                    pytest.fail(f"Forbidden bare `except:` found at {filepath}:{node.lineno}")

                # Identify if Exception is caught (directly, as Name, or in a Tuple)
                is_exception_caught = False
                if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    is_exception_caught = True
                elif isinstance(node.type, ast.Tuple):
                    for elt in node.type.elts:
                        if isinstance(elt, ast.Name) and elt.id == "Exception":
                            is_exception_caught = True

                if is_exception_caught:
                    comment_found = False
                    start_idx = node.lineno - 1

                    # Search up to 3 lines before start_idx
                    for i in range(1, 4):
                        check_idx = start_idx - i
                        if check_idx >= 0:
                            line = lines[check_idx].strip()
                            if line.startswith("#") and "Intentionally broad" in line:
                                comment_found = True
                                break

                    assert comment_found, (
                        f"Broad except at {filepath}:{node.lineno} does not have a "
                        f"'Intentionally broad' comment in the 1-3 preceding lines."
                    )


def test_get_config_mtime_ns_raise_exc_absent():
    """
    Ensure get_config_mtime_ns does not use `raise exc` and instead uses `raise`.
    """
    filepath = Path("py_modules/sdh_ludusavi/ludusavi.py")
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)

    function_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_config_mtime_ns":
            function_node = node
            break

    assert function_node is not None, "get_config_mtime_ns not found in ludusavi.py"

    for subnode in ast.walk(function_node):
        if isinstance(subnode, ast.Raise):
            if subnode.exc is not None:
                if isinstance(subnode.exc, ast.Name) and subnode.exc.id == "exc":
                    pytest.fail(
                        "Found 'raise exc' instead of a bare 'raise' in get_config_mtime_ns"
                    )


# --- ADAPTER NARROWED EXCEPTION TESTS ---


def test_get_aliases_handles_ludusavi_error_and_returns_empty():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    mock_client.config_show.side_effect = LudusaviError("mock error")
    adapter._client = mock_client

    assert adapter.get_aliases() == {}


def test_get_aliases_propagates_unrelated_exception():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    mock_client.config_show.side_effect = RuntimeError("programming error")
    adapter._client = mock_client

    with pytest.raises(RuntimeError, match="programming error"):
        adapter.get_aliases()


def test_compare_recency_handles_ludusavi_error_and_returns_ambiguous():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    # first backups_list succeeds
    mock_response = MagicMock()
    mock_response.data = {"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}}
    mock_client.backups_list.return_value = mock_response

    # restore (preview) raises LudusaviError
    mock_client.restore.side_effect = LudusaviError("CLI error")
    adapter._client = mock_client

    assert adapter.compare_recency("Hades") == "ambiguous"


def test_compare_recency_propagates_unrelated_exception():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = {"games": {"Hades": {"backups": [{"when": "2026-05-10T00:00:00Z"}]}}}
    mock_client.backups_list.return_value = mock_response

    # restore succeeds but parsing data raises an unexpected error
    mock_client.restore.return_value.data = None  # None.get will raise AttributeError
    adapter._client = mock_client

    with pytest.raises(AttributeError):
        adapter.compare_recency("Hades")


def test_get_conflict_metadata_handles_ludusavi_error_and_preserves_partial_data():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()

    # Phase 1: backups_list fails with LudusaviError
    mock_client.backups_list.side_effect = LudusaviError("backups_list failed")

    # Phase 2: backup (preview) succeeds
    mock_preview = MagicMock()
    mock_preview.data = {
        "games": {"Hades": {"files": {"save": {"originalPath": "/tmp/nonexistent-file-path-xyz"}}}}
    }
    mock_client.backup.return_value = mock_preview

    adapter._client = mock_client

    # Should complete without throwing, returning empty/partial metadata since files don't exist
    metadata = adapter.get_conflict_metadata("Hades")
    assert "backupModifiedAt" not in metadata
    assert "backupPath" not in metadata


def test_get_conflict_metadata_propagates_unrelated_exception():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    mock_client.backups_list.side_effect = RuntimeError("Unrelated RuntimeError")
    adapter._client = mock_client

    with pytest.raises(RuntimeError, match="Unrelated RuntimeError"):
        adapter.get_conflict_metadata("Hades")


def test_get_conflict_metadata_preserves_backup_metadata_on_local_value_error(monkeypatch):
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    backups_response = MagicMock()
    backups_response.data = {
        "games": {
            "Hades": {
                "backups": [{"when": "2026-07-12T07:37:15Z"}],
                "backupPath": "/backup/Hades",
            }
        }
    }
    preview_response = MagicMock()
    preview_response.data = {"games": {"Hades": {"files": {"/save.sav": {}}}}}
    mock_client.backups_list.return_value = backups_response
    mock_client.backup.return_value = preview_response
    adapter._client = mock_client

    mock_path = MagicMock()
    mock_path.is_absolute.return_value = True
    mock_path.stat.side_effect = ValueError("malformed path")
    monkeypatch.setattr("sdh_ludusavi.ludusavi.Path", lambda _raw_path: mock_path)

    metadata = adapter.get_conflict_metadata("Hades")

    assert metadata["backupModifiedAt"] == "2026-07-12T07:37:15Z"
    assert metadata["backupPath"] == "/backup/Hades"
    assert "localModifiedAt" not in metadata


def test_get_conflict_metadata_propagates_unexpected_stat_exception(monkeypatch):
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    backups_response = MagicMock()
    backups_response.data = {"games": {}}
    preview_response = MagicMock()
    preview_response.data = {"games": {"Hades": {"files": {"/save.sav": {}}}}}
    mock_client.backups_list.return_value = backups_response
    mock_client.backup.return_value = preview_response
    adapter._client = mock_client

    mock_path = MagicMock()
    mock_path.is_absolute.return_value = True
    mock_path.stat.side_effect = RuntimeError("unexpected stat failure")
    monkeypatch.setattr("sdh_ludusavi.ludusavi.Path", lambda _raw_path: mock_path)

    with pytest.raises(RuntimeError, match="unexpected stat failure"):
        adapter.get_conflict_metadata("Hades")


def test_get_diagnostics_handles_ludusavi_error_and_keeps_backup_path_unknown():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    mock_client.command_prefix = []
    mock_client.config_path.return_value = "/config/path"
    mock_client.config_show.side_effect = LudusaviError("command failure")
    adapter._client = mock_client

    diagnostics = adapter.get_diagnostics()
    assert diagnostics["backupPath"] == "unknown"


def test_get_diagnostics_propagates_unrelated_exception():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    mock_client.command_prefix = []
    mock_client.config_path.return_value = "/config/path"
    mock_client.config_show.side_effect = ZeroDivisionError()
    adapter._client = mock_client

    with pytest.raises(ZeroDivisionError):
        adapter.get_diagnostics()


def test_get_config_mtime_ns_narrowed_propagation():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._cached_config_path = None
    mock_client = MagicMock()
    mock_client.config_path.side_effect = ValueError("unsupported configuration")
    adapter._client = mock_client

    # ValueError is not OSError or RuntimeError, so it should propagate normally without log message
    with pytest.raises(ValueError, match="unsupported configuration"):
        adapter.get_config_mtime_ns()


# --- SERVICE COERCION & SERVICE NARROWED EXCEPTION TESTS ---


def test_load_state_skips_malformed_cached_game_entries(tmp_path):
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    # Save a cache containing one valid game and one malformed game
    # (needs_first_backup is missing or is of wrong type, etc.)
    cache_data = {
        "games": [
            {
                "name": "Hades",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "steam_id": "1145360",
                "error": None,
            },
            {
                # missing name key to force KeyError during coercion
                "configured": True,
                "has_backup": False,
                "needs_first_backup": True,
            },
        ]
    }
    cache_file.write_text(json.dumps(cache_data), encoding="utf-8")

    service = SDHLudusaviService(
        adapter=MagicMock(),
        settings_store=JsonSettingsStore(settings_file),
        cache_path=cache_file,
    )

    # Hades should be loaded, the malformed entry should be skipped because of coercion failure
    assert "Hades" in service._registry._games
    assert len(service._registry._games) == 1


def test_refresh_games_logs_and_drops_malformed_entries(tmp_path):
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    mock_adapter = MagicMock()
    # return lists of raw status mappings: one valid, one malformed (not a mapping), one missing name
    mock_adapter.refresh_statuses.return_value = [
        {"name": "Hades", "configured": True, "has_backup": True, "needs_first_backup": False},
        "not a dictionary",
        {"configured": True},
    ]

    service = SDHLudusaviService(
        adapter=mock_adapter,
        settings_store=JsonSettingsStore(settings_file),
        cache_path=cache_file,
    )

    # Force a refresh
    result = service.refresh_games(force=True)
    games_list = result["games"]

    # Hades should be present
    assert len(games_list) == 1
    assert games_list[0]["name"] == "Hades"


def test_post_operation_refresh_failure_logs_warning_and_returns_backup_result(tmp_path):
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    mock_adapter = MagicMock()
    mock_adapter.backup.return_value = {"ok": True}
    # refresh_statuses fails
    mock_adapter.refresh_statuses.side_effect = LudusaviError("refresh failed")

    # initialize service with one game in cache so match_game passes
    cache_data = {
        "games": [
            {
                "name": "Hades",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "steam_id": "1145360",
                "error": None,
            }
        ]
    }
    cache_file.write_text(json.dumps(cache_data), encoding="utf-8")

    service = SDHLudusaviService(
        adapter=mock_adapter,
        settings_store=JsonSettingsStore(settings_file),
        cache_path=cache_file,
    )

    # Try manual backup
    result = service.force_backup("Hades")
    assert result["status"] == "backed_up"
    assert result["result"] == {"ok": True}

    # Assert that the post-operation warning log was generated and recorded
    logs = service.get_recent_logs()
    warning_logs = [
        entry
        for entry in logs
        if entry["level"] == "warning"
        and "Post-operation status refresh failed" in entry["message"]
    ]
    assert len(warning_logs) == 1
    assert "refresh failed" in warning_logs[0]["message"]


def test_get_aliases_catches_config_shape_errors():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    mock_client = MagicMock()
    # mock config_show to return invalid shape (e.g. data is None, triggering AttributeError)
    mock_response = MagicMock()
    mock_response.data = None
    mock_client.config_show.return_value = mock_response
    adapter._client = mock_client

    # Should catch AttributeError and return {}
    assert adapter.get_aliases() == {}


def test_get_config_mtime_ns_catches_and_raises_ludusavi_error():
    adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    adapter._cached_config_path = None
    mock_client = MagicMock()
    mock_client.config_path.side_effect = LudusaviError("mock ludusavi error")
    adapter._client = mock_client

    # Should catch LudusaviError, log at debug, and re-raise it
    with pytest.raises(LudusaviError, match="mock ludusavi error"):
        adapter.get_config_mtime_ns()
