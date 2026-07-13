import argparse
import re
import subprocess
import sys
from pathlib import Path


def validate_token(token: str) -> str:
    if not token or not re.match(r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$", token):
        raise ValueError(f"Invalid token: {token}")
    return token


def pull_logs(host: str, plugin: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    remote_dir = f"/home/deck/homebrew/logs/{plugin}/"

    # inspect remote directory
    ssh_cmd = ["ssh", host, "ls", "-1", remote_dir]
    res = subprocess.run(ssh_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Failed to list remote logs: {res.stderr}", file=sys.stderr)
        sys.exit(2)

    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if not lines:
        print("No logs found.")
        return

    # construct scp args
    scp_cmd = ["scp", "-p"]
    for filename in lines:
        if filename.endswith(".log") or filename.endswith(".log.save"):
            scp_cmd.append(f"{host}:{remote_dir}{filename}")

    if len(scp_cmd) > 2:
        scp_cmd.append(str(dest))
        try:
            subprocess.run(scp_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Failed to copy logs: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"Pulled {len(scp_cmd) - 3} logs to {dest}")
    else:
        print("No matching log files found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull Decky plugin logs")
    parser.add_argument("--host", default="steamdeck", help="SSH host alias")
    parser.add_argument("--plugin", default="SDH-Ludusavi", help="Plugin name")
    parser.add_argument("--destination", type=Path, help="Destination directory")
    args = parser.parse_args()

    try:
        host = validate_token(args.host)
        plugin = validate_token(args.plugin)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    dest = args.destination or Path(f"/tmp/sdh_ludusavi/{host}/logs")
    pull_logs(host, plugin, dest)


if __name__ == "__main__":
    main()
