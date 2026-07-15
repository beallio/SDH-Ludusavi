from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOG_LINE_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s*\[(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s*:\s*(?P<message>.*)$"
)
APP_STARTED_RE = re.compile(
    r"App started:\s*(?P<game>.*?)\s+\((?P<app_id>\d+)\)\s+tracked=(?P<tracked>true|false)"
)
CHECK_RESULT_RE = re.compile(
    r"check_game_start result for\s+(?P<game>.*?)\s+\((?P<app_id>\d+)\):\s*(?P<payload>\{.*\})\s*$"
)
PAUSE_RE = re.compile(
    r"(?:Paused game process tree rooted at|Froze Steam app scope "
    r"app-steam-app[0-9]+-[0-9]+\.scope for root)\s+PID\s+(?P<pid>\d+)"
)
WATCHDOG_RE = re.compile(
    r"Watchdog detected (?:Steam app scope app-steam-app[0-9]+-[0-9]+\.scope for root )?"
    r"PID\s+(?P<pid>\d+)\s+(?:suspended|frozen) for .*?\((?P<reason>[^)]+)\)\.\s+"
    r"(?:Resuming|Thawing) automatically\."
)
GATE_FAILURE_RE = re.compile(
    r"Unable to (?P<operation>acquire frozen|discover|freeze) Steam app scope"
    r"(?: for root)? PID (?P<pid>\d+):\s*(?P<reason>.*)"
)
CONFLICT_SKIPPED_MESSAGE = (
    "Launch gate unavailable; conflict resolution skipped while game is loading."
)
ACTION_RE = re.compile(
    r"(?:\[(?P<game>[^\]]+)\]\s+)?(?:backup:\s+Kept local save|restore:\s+Restored)"
)
TTL_RE = re.compile(r"Syncthing watch\s+(?P<watch>\S+)\s+exceeded\s+180(?:\.0)?s TTL")

UNRECOGNIZED_REASONS = {
    "unmatched_game",
    "auto_sync_disabled",
    "autosync_disabled",
    "operation_running",
    "not_configured",
}
MAX_INCIDENT_LINES = 250


@dataclass
class LogFinding:
    rule_id: str
    severity: str
    filename: str
    line_number: int
    evidence: str
    occurrences: int = 1


@dataclass
class Stats:
    lines_parsed: int = 0
    parse_failures: int = 0
    levels: dict[str, int] = field(default_factory=lambda: dict.fromkeys(LEVELS, 0))
    tracebacks: int = 0


@dataclass
class _LaunchIncident:
    app_id: str
    app_name: str
    tracked: bool
    start_line: int
    pid: str | None = None
    check_line: int | None = None
    canonical_game: str | None = None
    waiting_for_action: bool = False
    watchdog_line: int | None = None
    watchdog_reason: str | None = None
    gate_failure_rule: str | None = None
    completed: bool = False


def _normalized_game(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _game_matches(action_game: str | None, incident: _LaunchIncident) -> bool:
    if action_game is None:
        return True
    action = _normalized_game(action_game)
    candidates = (
        _normalized_game(incident.app_name),
        _normalized_game(incident.canonical_game or ""),
    )
    return any(
        candidate and (candidate in action or action in candidate) for candidate in candidates
    )


def _is_backend_recognized(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    reason = payload.get("reason")
    operation = payload.get("operation")
    if status in {"needed", "conflict"}:
        return True
    if status == "skipped" and isinstance(reason, str):
        return reason not in UNRECOGNIZED_REASONS
    return status in {"backed_up", "restored"} or operation in {"backup", "restore"}


def _is_known_benign_error(message: str) -> bool:
    """Exclude only the known status-surface timeout/skip grammar."""
    lowered = message.casefold()
    has_timeout_source = bool(re.search(r"\bsource[=:]\s*timeout\b", lowered))
    has_skipped_status = bool(re.search(r"\b(?:status|result_status)[=:]\s*skipped\b", lowered))
    return has_timeout_source and has_skipped_status


def analyze_logs(paths: list[Path], strict: bool = False) -> tuple[list[LogFinding], Stats]:
    del strict  # Strictness affects the CLI exit code, not parsing.
    stats = Stats()
    findings: dict[tuple[object, ...], LogFinding] = {}

    def add_finding(
        key: tuple[object, ...],
        rule_id: str,
        severity: str,
        path: Path,
        line_number: int,
        evidence: str,
    ) -> None:
        existing = findings.get(key)
        if existing is not None:
            existing.occurrences += 1
            return
        findings[key] = LogFinding(
            rule_id=rule_id,
            severity=severity,
            filename=path.name,
            line_number=line_number,
            evidence=evidence[:200],
        )

    for path in sorted(paths, key=lambda item: str(item)):
        if not path.is_file():
            raise OSError(f"Unreadable log input: {path}")
        content = path.read_text(encoding="utf-8")

        # Correlation is deliberately reset for each file. Rotated logs are independent inputs.
        incidents: list[_LaunchIncident] = []

        for line_number, line in enumerate(content.splitlines(), 1):
            stats.lines_parsed += 1
            parsed = LOG_LINE_RE.match(line)
            message = line
            level: str | None = None
            if parsed is not None:
                level = parsed.group("level")
                message = parsed.group("message")
                stats.levels[level] += 1
            elif line.strip():
                stats.parse_failures += 1

            if "Traceback (most recent call last)" in line:
                stats.tracebacks += 1
            if (
                "Traceback (most recent call last)" in line or level in {"ERROR", "CRITICAL"}
            ) and not _is_known_benign_error(message):
                add_finding(
                    ("diagnostics.error_or_traceback", str(path), line_number),
                    "diagnostics.error_or_traceback",
                    "error",
                    path,
                    line_number,
                    line,
                )

            if len(line) > 2000 or any(
                marker in line
                for marker in ('"backupPath"', '"/home/deck', '"/run/media', '"files":')
            ):
                add_finding(
                    ("diagnostics.oversized_or_raw_payload", str(path), line_number),
                    "diagnostics.oversized_or_raw_payload",
                    "warning",
                    path,
                    line_number,
                    line,
                )

            ttl_match = TTL_RE.search(message)
            if ttl_match is not None:
                add_finding(
                    ("syncthing.watch_ttl_expired", str(path), ttl_match.group("watch")),
                    "syncthing.watch_ttl_expired",
                    "error",
                    path,
                    line_number,
                    line,
                )

            app_match = APP_STARTED_RE.search(message)
            if app_match is not None:
                incidents.append(
                    _LaunchIncident(
                        app_id=app_match.group("app_id"),
                        app_name=app_match.group("game"),
                        tracked=app_match.group("tracked") == "true",
                        start_line=line_number,
                    )
                )
                continue

            gate_failure = GATE_FAILURE_RE.search(message)
            if gate_failure is not None:
                reason = gate_failure.group("reason").casefold()
                operation = gate_failure.group("operation")
                is_freeze_failure = operation == "freeze" or any(
                    marker in reason
                    for marker in (
                        "systemctl freeze",
                        "freezer state",
                        "freeze verification",
                        "scope freeze",
                    )
                )
                rule_id = (
                    "launch_gate.scope_freeze_failed"
                    if is_freeze_failure
                    else "launch_gate.scope_acquisition_failed"
                )
                incident = next(
                    (
                        item
                        for item in reversed(incidents)
                        if not item.completed
                        and item.gate_failure_rule is None
                        and line_number - item.start_line <= MAX_INCIDENT_LINES
                    ),
                    None,
                )
                if incident is not None:
                    incident.pid = gate_failure.group("pid")
                    incident.gate_failure_rule = rule_id
                incident_key = (
                    incident.start_line
                    if incident is not None
                    else f"pid:{gate_failure.group('pid')}:{line_number}"
                )
                add_finding(
                    (rule_id, str(path), incident_key),
                    rule_id,
                    "error",
                    path,
                    line_number,
                    line,
                )
                continue

            if CONFLICT_SKIPPED_MESSAGE in message:
                incident = next(
                    (
                        item
                        for item in reversed(incidents)
                        if not item.completed
                        and line_number - item.start_line <= MAX_INCIDENT_LINES
                    ),
                    None,
                )
                if incident is None or incident.gate_failure_rule is None:
                    incident_key = (
                        incident.start_line if incident is not None else f"line:{line_number}"
                    )
                    add_finding(
                        ("launch_gate.conflict_skipped", str(path), incident_key),
                        "launch_gate.conflict_skipped",
                        "error",
                        path,
                        line_number,
                        line,
                    )
                if incident is not None:
                    incident.completed = True
                continue

            pause_match = PAUSE_RE.search(message)
            if pause_match is not None:
                incident = next(
                    (
                        item
                        for item in reversed(incidents)
                        if item.pid is None
                        and not item.completed
                        and line_number - item.start_line <= MAX_INCIDENT_LINES
                    ),
                    None,
                )
                if incident is not None:
                    incident.pid = pause_match.group("pid")
                continue

            check_match = CHECK_RESULT_RE.search(message)
            if check_match is not None:
                incident = next(
                    (
                        item
                        for item in reversed(incidents)
                        if item.app_id == check_match.group("app_id")
                        and item.check_line is None
                        and line_number - item.start_line <= MAX_INCIDENT_LINES
                    ),
                    None,
                )
                try:
                    payload = json.loads(check_match.group("payload"))
                except json.JSONDecodeError:
                    stats.parse_failures += 1
                    continue
                if incident is None or not isinstance(payload, dict):
                    continue
                incident.check_line = line_number
                canonical_game = payload.get("game")
                if isinstance(canonical_game, str):
                    incident.canonical_game = canonical_game
                incident.waiting_for_action = payload.get("status") in {"needed", "conflict"}
                if not incident.tracked and _is_backend_recognized(payload):
                    add_finding(
                        (
                            "launch_gate.backend_match_after_untracked_start",
                            str(path),
                            incident.start_line,
                        ),
                        "launch_gate.backend_match_after_untracked_start",
                        "error",
                        path,
                        line_number,
                        line,
                    )
                continue

            watchdog_match = WATCHDOG_RE.search(message)
            if watchdog_match is not None:
                pid = watchdog_match.group("pid")
                reason = watchdog_match.group("reason").casefold()
                incident = next(
                    (
                        item
                        for item in reversed(incidents)
                        if item.pid == pid
                        and not item.completed
                        and line_number - item.start_line <= MAX_INCIDENT_LINES
                    ),
                    None,
                )
                if incident is not None:
                    incident.watchdog_line = line_number
                    incident.watchdog_reason = reason
                if reason in {"lease expired", "absolute ceiling"}:
                    incident_key = (
                        incident.start_line if incident is not None else f"pid:{pid}:{line_number}"
                    )
                    add_finding(
                        ("launch_gate.lease_expired", str(path), incident_key),
                        "launch_gate.lease_expired",
                        "error",
                        path,
                        line_number,
                        f"{line} (watchdog reason: {reason})",
                    )
                continue

            action_match = ACTION_RE.search(message)
            if action_match is not None:
                incident = next(
                    (
                        item
                        for item in reversed(incidents)
                        if item.watchdog_line is not None
                        and item.waiting_for_action
                        and not item.completed
                        and line_number - item.start_line <= MAX_INCIDENT_LINES
                        and _game_matches(action_match.group("game"), item)
                    ),
                    None,
                )
                if incident is not None:
                    add_finding(
                        ("launch_gate.resume_before_resolution", str(path), incident.start_line),
                        "launch_gate.resume_before_resolution",
                        "error",
                        path,
                        incident.watchdog_line or line_number,
                        f"{line} (watchdog resume at line {incident.watchdog_line})",
                    )
                    incident.completed = True

    return list(findings.values()), stats


def _expand_inputs(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
        else:
            raise OSError(f"Unreadable log input: {path}")
    if not files:
        raise OSError("No readable log inputs found")
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    try:
        findings, stats = analyze_logs(_expand_inputs(args.paths), args.strict)
    except (OSError, UnicodeError) as exc:
        print(f"Operational error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(
            json.dumps(
                {"stats": stats.__dict__, "findings": [finding.__dict__ for finding in findings]},
                indent=2,
            )
        )
    else:
        for finding in findings:
            print(
                f"[{finding.severity.upper()}] {finding.rule_id} at "
                f"{finding.filename}:{finding.line_number} ({finding.occurrences}x) - "
                f"{finding.evidence}"
            )

    if args.strict and any(finding.severity == "error" for finding in findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
