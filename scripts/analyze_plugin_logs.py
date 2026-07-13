import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


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
    levels: dict[str, int] = field(
        default_factory=lambda: {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0}
    )
    tracebacks: int = 0


def analyze_logs(paths: list[Path], strict: bool) -> tuple[list[LogFinding], Stats]:
    findings = []
    stats = Stats()

    # state tracking
    app_state = defaultdict(dict)  # app_id -> {"tracked": bool}
    pid_state = defaultdict(
        dict
    )  # pid -> {"paused": bool, "watchdog_resumed": bool, "app_id": str}

    # regexes
    level_re = re.compile(r"(?:\[(.*?)\])?\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]:?\s*(.*)")

    app_start_re = re.compile(r"App started: .*? \((.*?)\) tracked=(true|false)")
    backend_check_re = re.compile(
        r"lifecycle: check_game_start result.*?\"status\":\"(matched|conflict|unmatched_game|auto_sync_disabled|ignored)\""
    )
    pause_re = re.compile(r"launch_gate: Paused game process tree rooted at PID (\d+)")
    watchdog_resume_re = re.compile(
        r"watchdog: Watchdog detected PID (\d+) suspended for 15s.*?Resuming automatically"
    )
    lease_expired_re = re.compile(r"lease expired for PID (\d+)")
    explicit_resume_re = re.compile(r"launch_gate: Resumed game process tree rooted at PID (\d+)")
    action_re = re.compile(r"(backup: Kept local save|restore: Restored|User resolved conflict)")
    ttl_expiry_re = re.compile(r"exceeded 180\.0s TTL")

    # To correlate PID to app, we'd need them on the same line, or just maintain last seen app
    last_seen_app = None

    for path in sorted(paths):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for idx, line in enumerate(content.splitlines(), 1):
            stats.lines_parsed += 1
            # tolerant parsing
            level_match = level_re.search(line)
            if level_match:
                lvl = level_match.group(2)
                msg = level_match.group(3)
                stats.levels[lvl] = stats.levels.get(lvl, 0) + 1
            else:
                lvl = None
                msg = line
                if "Traceback" in line:
                    stats.tracebacks += 1
                else:
                    stats.parse_failures += 1

            if "failures_errors" not in msg and "timeout" not in msg and "skipped" not in msg:
                if "Traceback" in line or lvl in ("ERROR", "CRITICAL"):
                    findings.append(
                        LogFinding(
                            "diagnostics.error_or_traceback", "error", path.name, idx, line[:200]
                        )
                    )

            if len(line) > 2000 or any(
                x in line for x in ['"backupPath"', '"/home/deck"', '"/run/media"', '"files":']
            ):
                findings.append(
                    LogFinding(
                        "diagnostics.oversized_or_raw_payload",
                        "warning",
                        path.name,
                        idx,
                        line[:200],
                    )
                )

            if ttl_expiry_re.search(line):
                findings.append(
                    LogFinding("syncthing.watch_ttl_expired", "error", path.name, idx, line[:200])
                )

            m = app_start_re.search(line)
            if m:
                app_id, tracked = m.groups()
                app_state[app_id] = {"tracked": tracked == "true"}
                last_seen_app = app_id

            m = backend_check_re.search(line)
            if m and last_seen_app:
                status = m.group(1)
                if (
                    status in ("matched", "conflict")
                    and app_state[last_seen_app].get("tracked") is False
                ):
                    findings.append(
                        LogFinding(
                            "launch_gate.backend_match_after_untracked_start",
                            "error",
                            path.name,
                            idx,
                            line[:200],
                        )
                    )

            m = pause_re.search(line)
            if m:
                pid = m.group(1)
                pid_state[pid]["paused"] = True
                pid_state[pid]["watchdog_resumed"] = False

            m = watchdog_resume_re.search(line)
            if m:
                pid = m.group(1)
                pid_state[pid]["watchdog_resumed"] = True

            m = lease_expired_re.search(line)
            if m:
                pid = m.group(1)
                findings.append(
                    LogFinding("launch_gate.lease_expired", "error", path.name, idx, line[:200])
                )

            m = explicit_resume_re.search(line)
            if m:
                pid = m.group(1)
                pid_state[pid]["paused"] = False

            m = action_re.search(line)
            if m:
                # User resolved action, check if resumed before this
                for pid, state in list(pid_state.items()):
                    if state.get("watchdog_resumed"):
                        findings.append(
                            LogFinding(
                                "launch_gate.resume_before_resolution",
                                "error",
                                path.name,
                                idx,
                                line[:200],
                            )
                        )
                        state["watchdog_resumed"] = False

    # Deduplicate findings by rule and evidence prefix
    deduped = {}
    for f in findings:
        key = (f.rule_id, f.evidence[:50])
        if key not in deduped:
            deduped[key] = f
        else:
            deduped[key].occurrences += 1

    return list(deduped.values()), stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    files = []
    for p in args.paths:
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(p.glob("**/*"))

    if not files:
        sys.exit(2)

    findings, stats = analyze_logs(files, args.strict)

    if args.format == "json":
        out = {"stats": stats.__dict__, "findings": [f.__dict__ for f in findings]}
        print(json.dumps(out, indent=2))
    else:
        for f in findings:
            print(
                f"[{f.severity.upper()}] {f.rule_id} at {f.filename}:{f.line_number} ({f.occurrences}x) - {f.evidence}"
            )

    if args.strict and any(f.severity == "error" for f in findings):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
