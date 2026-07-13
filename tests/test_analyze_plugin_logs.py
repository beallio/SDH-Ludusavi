from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def load_analyze_module():
    spec = importlib.util.spec_from_file_location(
        "analyze_plugin_logs", "scripts/analyze_plugin_logs.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIXTURES_DIR = Path("tests/fixtures/plugin_logs")


def test_analyze_clean_log() -> None:
    res = subprocess.run(
        [sys.executable, "scripts/analyze_plugin_logs.py", str(FIXTURES_DIR / "clean.log")],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "launch_gate.resume_before_resolution" not in res.stdout
    assert "launch_gate.backend_match_after_untracked_start" not in res.stdout
    assert "syncthing.watch_ttl_expired" not in res.stdout


def test_analyze_cold_tracking_conflict() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--format",
            "json",
            str(FIXTURES_DIR / "cold-tracking-conflict.log"),
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(res.stdout)
    assert any(
        f["rule_id"] == "launch_gate.backend_match_after_untracked_start" for f in data["findings"]
    )


def test_analyze_watchdog_resume_before_resolution() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--format",
            "json",
            str(FIXTURES_DIR / "watchdog-resume-before-resolution.log"),
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(res.stdout)
    assert any(f["rule_id"] == "launch_gate.resume_before_resolution" for f in data["findings"])


def test_analyze_syncthing_ttl_expiry() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--format",
            "json",
            str(FIXTURES_DIR / "syncthing-ttl-expiry.log"),
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(res.stdout)
    assert any(f["rule_id"] == "syncthing.watch_ttl_expired" for f in data["findings"])


def test_analyze_strict_returns_1() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--strict",
            str(FIXTURES_DIR / "watchdog-resume-before-resolution.log"),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1


def test_analyze_json_and_text_match() -> None:
    json_res = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--format",
            "json",
            str(FIXTURES_DIR / "watchdog-resume-before-resolution.log"),
        ],
        capture_output=True,
        text=True,
    )
    text_res = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            str(FIXTURES_DIR / "watchdog-resume-before-resolution.log"),
        ],
        capture_output=True,
        text=True,
    )

    assert "launch_gate.resume_before_resolution" in text_res.stdout
    data = json.loads(json_res.stdout)
    assert len(data["findings"]) > 0


def test_analyze_malformed_lines_handled() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--format",
            "json",
            str(FIXTURES_DIR / "clean.log"),
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(res.stdout)
    # Shouldn't crash on unparseable lines
    assert "parse_failures" in data["stats"]
