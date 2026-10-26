from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ludusavi"
_GENERATED_BACKUP_ROOT = "/tmp/sdh_ludusavi_contract_fixture/backups"
_GENERATED_SAVE_FILE = "/tmp/sdh_ludusavi_contract_fixture/save.dat"


_DEFAULT_FIXTURES = {
    "config_show": "config-show.json",
    "backup_preview": "backup-preview.json",
    "backup": "backup-result.json",
    "restore_preview": "restore-preview.json",
    "restore": "restore-result.json",
    "backups": "backups.json",
}


def _scenario() -> dict[str, Any]:
    try:
        return json.loads(Path(os.environ["SDH_CONTRACT_SCENARIO"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {}


def _append_record(path_key: str, record: dict[str, Any]) -> None:
    path = os.environ[path_key]
    payload = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def _response_key(args: list[str]) -> str:
    if args == ["--version"]:
        return "version"
    if args[:2] == ["config", "path"]:
        return "config_path"
    if args[:2] == ["config", "show"]:
        return "config_show"
    if args and args[0] == "backup":
        return "backup_preview" if "--preview" in args else "backup"
    if args and args[0] == "restore":
        return "restore_preview" if "--preview" in args else "restore"
    if args and args[0] == "backups":
        return "backups"
    return "unsupported"


def _generated_response(key: str) -> tuple[str, str, int]:
    if key == "version":
        return "ludusavi 0.31.0\n", "", 0
    if key == "config_path":
        return (
            str(Path(os.environ["SDH_CONTRACT_LUDUSAVI_CONFIG_DIR"]) / "config.yaml") + "\n",
            "",
            0,
        )
    fixture = _DEFAULT_FIXTURES.get(key)
    if fixture is None:
        return "", f"unsupported fake Ludusavi command: {key}\n", 64
    output = (FIXTURES / fixture).read_text(encoding="utf-8")
    return _relocate_paths(output), "", 0


def _relocate_paths(output: str) -> str:
    return output.replace(_GENERATED_BACKUP_ROOT, os.environ["SDH_CONTRACT_BACKUP_ROOT"]).replace(
        _GENERATED_SAVE_FILE, os.environ["SDH_CONTRACT_SAVE_FILE"]
    )


def _apply_response(response: dict[str, Any], key: str) -> tuple[str, str, int]:
    if "json" in response:
        stdout, stderr, exit_code = json.dumps(response["json"]), "", 0
    elif "fixture" in response:
        stdout = (FIXTURES / str(response["fixture"])).read_text(encoding="utf-8")
        stderr, exit_code = "", 0
    elif "stdout" in response:
        stdout, stderr, exit_code = str(response["stdout"]), "", 0
    else:
        stdout, stderr, exit_code = _generated_response(key)
    return (
        _relocate_paths(stdout),
        str(response.get("stderr", stderr)),
        int(response.get("exit_code", exit_code)),
    )


def _hang_if_configured(config: dict[str, Any]) -> None:
    delay = config.get("delay_seconds")
    if config.get("ignore_term") is True:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if config.get("spawn_child") is True:
        child_code = (
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(600)"
        )
        child = subprocess.Popen([sys.executable, "-c", child_code])
        config["child_pid"] = child.pid
    if isinstance(delay, int | float) and delay > 0:
        time.sleep(float(delay))


def run_flatpak(argv: list[str]) -> int:
    record: dict[str, Any] = {
        "argv": argv,
        "pid": os.getpid(),
        "pgid": os.getpgid(0),
    }
    _append_record("SDH_CONTRACT_FAKE_LOG", record)
    scenario = _scenario().get("flatpak", {})
    command_args = argv[2:] if argv[:2] == ["run", "com.github.mtkennerly.ludusavi"] else argv
    key = _response_key(command_args)
    response = scenario.get("responses", {}).get(key, {})
    _hang_if_configured(response)

    if scenario.get("mode") == "real":
        binary = os.environ.get("SDH_CONTRACT_LUDUSAVI_BIN")
        if not binary:
            print("SDH_CONTRACT_LUDUSAVI_BIN is required for real Ludusavi mode", file=sys.stderr)
            return 78
        executable = str(Path(binary).resolve())
        command = [
            executable,
            "--no-manifest-update",
            "--config",
            os.environ["SDH_CONTRACT_LUDUSAVI_CONFIG_DIR"],
        ]
        command.extend(command_args)
        environment = os.environ.copy()
        library_path = environment.get("SDH_CONTRACT_LUDUSAVI_LD_LIBRARY_PATH")
        if library_path:
            environment["LD_LIBRARY_PATH"] = library_path
        os.execve(executable, command, environment)

    if not response:
        stdout, stderr, exit_code = _generated_response(key)
    else:
        stdout, stderr, exit_code = _apply_response(response, key)
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return exit_code


def _simulate_scope_transition(argv: list[str], config: dict[str, Any]) -> tuple[str, int] | None:
    if (
        config.get("simulate_scope_freeze") is not True
        or len(argv) != 3
        or argv[0] != "--user"
        or argv[1] not in {"freeze", "thaw"}
    ):
        return None
    unit = argv[2]
    if (
        unit != config.get("scope_unit")
        or re.fullmatch(r"app-steam-app[0-9]+-[0-9]+\.scope", unit) is None
    ):
        return "refusing to transition an unconfigured contract scope\n", 64

    uid = os.geteuid()
    cgroup_root = Path("/sys/fs/cgroup/user.slice") / f"user-{uid}.slice"
    cgroup_root /= f"user@{uid}.service/app.slice"
    scope = cgroup_root / unit
    try:
        if scope.resolve(strict=True) != scope or not scope.is_relative_to(cgroup_root):
            return "contract scope path is not canonical\n", 64
        freezer = scope / "cgroup.freeze"
        events = scope / "cgroup.events"
        if not freezer.is_file() or not events.is_file():
            return "contract scope has no cgroup freezer controls\n", 1
        expected = "1" if argv[1] == "freeze" else "0"
        freezer.write_text(expected, encoding="ascii")
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            frozen = [
                fields[1]
                for line in events.read_text(encoding="ascii").splitlines()
                if len(fields := line.split()) == 2 and fields[0] == "frozen"
            ]
            if frozen == [expected]:
                return "", 0
            time.sleep(0.01)
    except OSError as exc:
        return f"contract scope transition failed: {exc}\n", 1
    return "contract scope freezer did not converge\n", 1


def run_systemctl(argv: list[str]) -> int:
    record = {
        "argv": argv,
        "pid": os.getpid(),
        "pgid": os.getpgid(0),
    }
    _append_record("SDH_CONTRACT_SYSTEMCTL_LOG", record)
    result = _scenario().get("systemctl", {})
    _hang_if_configured(result)
    simulation = (
        None if int(result.get("exit_code", 0)) != 0 else _simulate_scope_transition(argv, result)
    )
    if simulation is None:
        stdout, exit_code = str(result.get("stdout", "")), int(result.get("exit_code", 0))
    else:
        stdout, exit_code = simulation
    response_delay = result.get("response_delay_seconds")
    if isinstance(response_delay, int | float) and response_delay > 0:
        time.sleep(float(response_delay))
    sys.stdout.write(stdout)
    sys.stderr.write(str(result.get("stderr", "")))
    return exit_code
