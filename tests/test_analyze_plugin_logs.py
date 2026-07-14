from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


FIXTURES_DIR = Path("tests/fixtures/plugin_logs")


def load_analyze_module():
    spec = importlib.util.spec_from_file_location(
        "analyze_plugin_logs", "scripts/analyze_plugin_logs.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_json_fixture(name: str) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--format",
            "json",
            str(FIXTURES_DIR / name),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_analyze_clean_log() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/analyze_plugin_logs.py", str(FIXTURES_DIR / "clean.log")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "launch_gate.resume_before_resolution" not in result.stdout
    assert "launch_gate.backend_match_after_untracked_start" not in result.stdout
    assert "syncthing.watch_ttl_expired" not in result.stdout


def test_analyze_cold_tracking_conflict() -> None:
    data = run_json_fixture("cold-tracking-conflict.log")
    assert any(
        finding["rule_id"] == "launch_gate.backend_match_after_untracked_start"
        for finding in data["findings"]
    )


def test_analyze_watchdog_resume_before_resolution() -> None:
    data = run_json_fixture("watchdog-resume-before-resolution.log")
    assert any(
        finding["rule_id"] == "launch_gate.resume_before_resolution" for finding in data["findings"]
    )


def test_analyze_syncthing_ttl_expiry() -> None:
    data = run_json_fixture("syncthing-ttl-expiry.log")
    assert any(finding["rule_id"] == "syncthing.watch_ttl_expired" for finding in data["findings"])


def test_analyze_integrated_real_syntax_log() -> None:
    data = run_json_fixture("integrated.log")
    rules = {finding["rule_id"] for finding in data["findings"]}
    assert "launch_gate.backend_match_after_untracked_start" in rules
    assert "launch_gate.resume_before_resolution" in rules
    assert "launch_gate.lease_expired" in rules
    assert "syncthing.watch_ttl_expired" in rules
    assert "diagnostics.oversized_or_raw_payload" in rules
    assert "diagnostics.error_or_traceback" in rules
    assert data["stats"]["levels"]["INFO"] > 0
    assert data["stats"]["levels"]["WARNING"] > 0
    assert data["stats"]["levels"]["ERROR"] == 2
    diagnostic_findings = [
        finding
        for finding in data["findings"]
        if finding["rule_id"] == "diagnostics.error_or_traceback"
    ]
    assert len(diagnostic_findings) == 1
    assert "Network timeout" in diagnostic_findings[0]["evidence"]


def test_analyzer_derives_findings_without_rule_name_sentinels() -> None:
    module = load_analyze_module()
    findings, stats = module.analyze_logs([FIXTURES_DIR / "integrated.log"])

    fixture_text = (FIXTURES_DIR / "integrated.log").read_text(encoding="utf-8")
    assert all(finding.rule_id not in fixture_text for finding in findings)
    assert stats.parse_failures == 0


def test_incident_deduplication_counts_repeated_watch_evidence(tmp_path: Path) -> None:
    log_path = tmp_path / "repeat.log"
    log_path.write_text(
        "\n".join(
            [
                "[2026-07-12 10:00:00,001][WARNING]: "
                "sdh_ludusavi.syncthing.watcher: Syncthing watch repeat-watch "
                "exceeded 180.0s TTL without stop_watch; terminating",
                "[2026-07-12 10:00:01,002][WARNING]: "
                "sdh_ludusavi.syncthing.watcher: Syncthing watch repeat-watch "
                "exceeded 180.0s TTL without stop_watch; terminating",
            ]
        ),
        encoding="utf-8",
    )
    module = load_analyze_module()

    findings, _ = module.analyze_logs([log_path])

    assert len(findings) == 1
    assert findings[0].rule_id == "syncthing.watch_ttl_expired"
    assert findings[0].occurrences == 2


def test_analyze_absolute_ceiling_as_launch_gate_expiry(tmp_path: Path) -> None:
    log_path = tmp_path / "absolute.log"
    log_path.write_text(
        "[2026-07-12 10:00:00,001][WARNING]: watchdog: "
        "Watchdog detected PID 4321 suspended for 360s "
        "(absolute ceiling). Resuming automatically.\n",
        encoding="utf-8",
    )
    module = load_analyze_module()

    findings, _ = module.analyze_logs([log_path])

    assert [finding.rule_id for finding in findings] == ["launch_gate.lease_expired"]
    assert "absolute ceiling" in findings[0].evidence


def test_analyze_scope_freeze_and_thaw_watchdog_syntax(tmp_path: Path) -> None:
    log_path = tmp_path / "scope-freeze.log"
    log_path.write_text(
        "\n".join(
            [
                "[2026-07-14 12:32:45,001][INFO]: frontend: "
                "App started: Wolverine (3156562597) tracked=true",
                "[2026-07-14 12:32:46,001][INFO]: launch_gate: Froze Steam app scope "
                "app-steam-app3156562597-12992.scope for root PID 12992",
                "[2026-07-14 12:32:52,001][INFO]: frontend: check_game_start result for "
                'Wolverine (3156562597): {"status":"conflict","game":"Wolverine"}',
                "[2026-07-14 12:33:22,001][WARNING]: watchdog: Watchdog detected Steam "
                "app scope app-steam-app3156562597-12992.scope for root PID 12992 frozen "
                "for 36s (lease expired). Thawing automatically.",
                "[2026-07-14 12:33:24,001][INFO]: frontend: [Wolverine] restore: Restored",
            ]
        ),
        encoding="utf-8",
    )
    module = load_analyze_module()

    findings, _ = module.analyze_logs([log_path])

    assert {finding.rule_id for finding in findings} == {
        "launch_gate.lease_expired",
        "launch_gate.resume_before_resolution",
    }


def test_analyze_strict_returns_1() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            "--strict",
            str(FIXTURES_DIR / "watchdog-resume-before-resolution.log"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_analyze_json_and_text_match() -> None:
    json_data = run_json_fixture("watchdog-resume-before-resolution.log")
    text_result = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_plugin_logs.py",
            str(FIXTURES_DIR / "watchdog-resume-before-resolution.log"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "launch_gate.resume_before_resolution" in text_result.stdout
    assert {finding["rule_id"] for finding in json_data["findings"]} == {
        "launch_gate.resume_before_resolution"
    }


def test_analyze_malformed_lines_handled(tmp_path: Path) -> None:
    mixed = tmp_path / "mixed.log"
    mixed.write_text(
        "not a log line\n"
        "[2026-07-12 10:00:00,001][INFO]: frontend: App started: Game (1) tracked=true\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "scripts/analyze_plugin_logs.py", "--format", "json", str(mixed)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["stats"]["parse_failures"] == 1


def test_analyze_missing_input_returns_2() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/analyze_plugin_logs.py", "nonexistent_file_xyz123.log"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Operational error" in result.stderr


def test_analyze_unreadable_utf8_returns_2(tmp_path: Path) -> None:
    unreadable = tmp_path / "invalid.log"
    unreadable.write_bytes(b"\xff\xfe")
    result = subprocess.run(
        [sys.executable, "scripts/analyze_plugin_logs.py", str(unreadable)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Operational error" in result.stderr
