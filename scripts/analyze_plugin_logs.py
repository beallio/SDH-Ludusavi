import argparse
import json
import sys
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

    for path in sorted(paths):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for idx, line in enumerate(content.splitlines(), 1):
            stats.lines_parsed += 1

            if "Traceback" in line:
                stats.tracebacks += 1

            if "failures_errors" not in line and "timeout" not in line and "skipped" not in line:
                if "Traceback" in line or "[ERROR]" in line or "[CRITICAL]" in line:
                    findings.append(
                        LogFinding(
                            "diagnostics.error_or_traceback", "error", path.name, idx, line[:200]
                        )
                    )

            if (
                len(line) > 2000
                or '"backupPath"' in line
                or '"/home/deck"' in line
                or '"/run/media"' in line
                or '"files":' in line
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

            if "exceeded 180.0s TTL" in line:
                findings.append(
                    LogFinding("syncthing.watch_ttl_expired", "error", path.name, idx, line[:200])
                )

            if "backend_match_after_untracked_start" in line:
                findings.append(
                    LogFinding(
                        "launch_gate.backend_match_after_untracked_start",
                        "error",
                        path.name,
                        idx,
                        line[:200],
                    )
                )

            if "lease expired for PID" in line:
                findings.append(
                    LogFinding("launch_gate.lease_expired", "error", path.name, idx, line[:200])
                )

            if "resume_before_resolution" in line:
                findings.append(
                    LogFinding(
                        "launch_gate.resume_before_resolution",
                        "error",
                        path.name,
                        idx,
                        line[:200],
                    )
                )

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
