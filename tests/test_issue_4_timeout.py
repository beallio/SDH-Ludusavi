from __future__ import annotations
from unittest.mock import MagicMock
from pyludusavi.main import Ludusavi


def test_backup_default_timeout():
    # Mock executor
    mock_executor = MagicMock()
    mock_executor.execute.return_value = MagicMock()

    ludusavi = Ludusavi()
    ludusavi.executor = mock_executor

    # Call backup without timeout
    ludusavi.backup()

    # Verify execute was called with timeout=60
    # Currently it defaults to None in the code
    args, kwargs = mock_executor.execute.call_args
    assert kwargs.get("timeout") == 60


def test_restore_default_timeout():
    mock_executor = MagicMock()
    mock_executor.execute.return_value = MagicMock()

    ludusavi = Ludusavi()
    ludusavi.executor = mock_executor

    ludusavi.restore()

    args, kwargs = mock_executor.execute.call_args
    assert kwargs.get("timeout") == 60
