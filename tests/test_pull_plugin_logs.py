from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def load_pull_module():
    spec = importlib.util.spec_from_file_location("pull_plugin_logs", "scripts/pull_plugin_logs.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pull_rejects_unsafe_tokens() -> None:
    module = load_pull_module()
    for token in ["host name", "../plugin", "a/b", "steamdeck; rm -rf /", "", "-foo"]:
        with pytest.raises(ValueError, match="Invalid token"):
            module.validate_token(token)

    assert module.validate_token("steamdeck") == "steamdeck"
    assert module.validate_token("SDH-Ludusavi") == "SDH-Ludusavi"


def test_pull_args_and_destination(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_pull_module()

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "2026-07-12 09.55.50.log\nolder.log.save\nignored.txt\n"
    monkeypatch.setattr(subprocess, "run", mock_run)

    dest = tmp_path / "logs"
    module.pull_logs("steamdeck", "SDH-Ludusavi", dest)

    assert dest.exists()
    assert mock_run.call_count == 2

    ssh_args = mock_run.call_args_list[0][0][0]
    assert ssh_args == [
        "ssh",
        "steamdeck",
        "ls",
        "-1",
        "/home/deck/homebrew/logs/SDH-Ludusavi/",
    ]

    scp_args = mock_run.call_args_list[1][0][0]
    assert scp_args == [
        "scp",
        "-p",
        "steamdeck:/home/deck/homebrew/logs/SDH-Ludusavi/2026-07-12 09.55.50.log",
        "steamdeck:/home/deck/homebrew/logs/SDH-Ludusavi/older.log.save",
        str(dest),
    ]
