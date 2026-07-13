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

    # PID states
    # state shape: {"tracked": bool, "conflict": bool, "watchdog_resumed": bool}
    pids = defaultdict(dict)

    # regexes
    level_re = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]")
    pid_re = re.compile(r"PID=(\d+)")
    tracked_false_re = re.compile(r"tracked=false")
    backend_matched_re = re.compile(r"backend check: matched")
    backend_conflict_re = re.compile(r"backend check: conflict")
    watchdog_resume_re = re.compile(r"watchdog resume game process")
    user_resolved_re = re.compile(r"User resolved conflict")
    ttl_expiry_re = re.compile(r"syncthing TTL expired")

    for path in sorted(paths):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for idx, line in enumerate(content.splitlines(), 1):
            stats.lines_parsed += 1
            level_match = level_re.search(line)
            if level_match:
                lvl = level_match.group(1)
                stats.levels[lvl] = stats.levels.get(lvl, 0) + 1
            else:
                if "Traceback" in line:
                    stats.tracebacks += 1
                else:
                    stats.parse_failures += 1

            if "Traceback" in line or (
                level_match and level_match.group(1) in ("ERROR", "CRITICAL")
            ):
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

            pid_match = pid_re.search(line)
            if pid_match:
                pid = pid_match.group(1)

                if "App launch:" in line:
                    pids[pid] = {
                        "tracked": not bool(tracked_false_re.search(line)),
                        "conflict": False,
                        "watchdog_resumed": False,
                    }

                if backend_matched_re.search(line):
                    if pid in pids and pids[pid].get("tracked") is False:
                        findings.append(
                            LogFinding(
                                "launch_gate.backend_match_after_untracked_start",
                                "error",
                                path.name,
                                idx,
                                line[:200],
                            )
                        )

                if backend_conflict_re.search(line):
                    if pid in pids:
                        pids[pid]["conflict"] = True

                if watchdog_resume_re.search(line):
                    if pid in pids:
                        pids[pid]["watchdog_resumed"] = True

                if user_resolved_re.search(line):
                    if (
                        pid in pids
                        and pids[pid].get("conflict")
                        and pids[pid].get("watchdog_resumed")
                    ):
                        findings.append(
                            LogFinding(
                                "launch_gate.resume_before_resolution",
                                "error",
                                path.name,
                                idx,
                                line[:200],
                            )
                        )

    # Deduplicate findings
    deduped = {}
    for f in findings:
        key = (f.rule_id, f.filename, f.line_number)
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
