from __future__ import annotations

import json
from pathlib import Path
import sys
import shutil
import time
from uuid import UUID

import pytest

from harness import ContractHarness


def test_shim_mode_reports_missing_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SDH_CONTRACT_SHIM_BINARY", str(tmp_path / "absent"))
    harness = ContractHarness(backend="shim", root=tmp_path / "environment")
    try:
        with pytest.raises(RuntimeError, match="bin/backend"):
            harness.start()
    finally:
        harness.close()


def test_shim_mode_reports_missing_metadata(tmp_path: Path) -> None:
    harness = ContractHarness(backend="shim", root=tmp_path / "environment")
    metadata_path = harness.plugin_dir / "plugin.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("backend")
    metadata_path.write_text(json.dumps(metadata))
    try:
        with pytest.raises(RuntimeError, match="plugin.json has no relative backend path"):
            harness.start()
    finally:
        harness.close()


def test_shim_mode_rejects_empty_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import harness as harness_module

    project = tmp_path / "project"
    host_dir = project / "tests" / "contract"
    host_dir.mkdir(parents=True)
    shutil.copyfile(harness_module.REPO_ROOT / "tests/contract/host.py", host_dir / "host.py")
    shutil.copyfile(harness_module.REPO_ROOT / "plugin.json", project / "plugin.json")
    shutil.copytree(harness_module.REPO_ROOT / "theme", project / "theme")
    (project / "main.py").write_text("class Plugin:\n    pass\n")
    monkeypatch.setattr(harness_module, "REPO_ROOT", project)
    harness = ContractHarness(backend="shim", root=tmp_path / "environment")
    try:
        with pytest.raises(RuntimeError, match="_main"):
            harness.start()
    finally:
        harness.close()


def _probe_backend(tmp_path: Path, response: dict[str, object]) -> tuple[Path, Path]:
    executable = tmp_path / "probe_backend.py"
    request_log = tmp_path / "request.json"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, socket\n"
        "listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "listener.bind(os.environ['DECKY_PLUGIN_SOCKET'])\n"
        "listener.listen(1)\n"
        "connection, _ = listener.accept()\n"
        "with connection:\n"
        "    request = json.loads(connection.makefile('rb').readline())\n"
        "    with open(os.environ['SDH_CONTRACT_PROBE_LOG'], 'w') as stream:\n"
        "        json.dump(request, stream)\n"
        "    response = json.loads(os.environ['SDH_CONTRACT_PROBE_REPLY'])\n"
        "    response['id'] = request['id']\n"
        "    connection.sendall((json.dumps(response) + '\\n').encode())\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, request_log


def _harness(executable: Path, request_log: Path, response: dict[str, object]) -> ContractHarness:
    harness = ContractHarness(backend=str(executable))
    harness.env["SDH_CONTRACT_PROBE_LOG"] = str(request_log)
    harness.env["SDH_CONTRACT_PROBE_REPLY"] = json.dumps(response)
    return harness


def test_requests_use_string_ids_and_match_string_replies(tmp_path: Path) -> None:
    executable, request_log = _probe_backend(
        tmp_path, {"type": 1, "success": True, "res": "round-trip"}
    )
    harness = _harness(executable, request_log, {"type": 1, "success": True, "res": "round-trip"})
    try:
        harness.start()
        assert harness.call("probe", "argument") == (True, "round-trip")
        request = json.loads(request_log.read_text(encoding="utf-8"))
        assert isinstance(request["id"], str)
        assert str(UUID(request["id"])) == request["id"]
    finally:
        harness.close()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"type": 1, "success": "true", "res": "not a boolean"}, "success is not a boolean"),
        ({"type": 1, "success": True}, "missing res"),
    ],
)
def test_malformed_reply_envelopes_fail_calls(
    tmp_path: Path,
    response: dict[str, object],
    error: str,
) -> None:
    executable, request_log = _probe_backend(tmp_path, response)
    harness = _harness(executable, request_log, response)
    try:
        harness.start()
        with pytest.raises(ConnectionError, match=error):
            harness.call("probe")
    finally:
        harness.close()


def test_graceful_backend_exit_still_kills_remaining_process_group(tmp_path: Path) -> None:
    executable = tmp_path / "orphaning_backend.py"
    pid_file = tmp_path / "orphan.pid"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, socket, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        '"import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(600)"])\n'
        "with open(os.environ['SDH_CONTRACT_ORPHAN_PID'], 'w') as stream:\n"
        "    stream.write(str(child.pid))\n"
        "listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "listener.bind(os.environ['DECKY_PLUGIN_SOCKET'])\n"
        "listener.listen(1)\n"
        "connection, _ = listener.accept()\n"
        "connection.close()\n"
        "signal.pause()\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    harness = ContractHarness(backend=str(executable))
    harness.env["SDH_CONTRACT_ORPHAN_PID"] = str(pid_file)
    try:
        harness.start()
        child_pid = int(pid_file.read_text(encoding="ascii"))
        harness.stop()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                stat = Path(f"/proc/{child_pid}/stat").read_text(encoding="ascii")
            except (FileNotFoundError, ProcessLookupError):
                break
            close_paren = stat.rfind(")")
            fields = stat[close_paren + 1 :].split() if close_paren >= 0 else []
            if fields and fields[0] == "Z":
                break
            time.sleep(0.01)
        else:
            pytest.fail("backend process group survived graceful backend exit")
    finally:
        harness.close()


def test_systemd_child_startup_failure_stops_started_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signal
    from io import BytesIO

    import test_contract

    child_pid = 424242
    signals: list[tuple[int, int]] = []
    wait_calls = 0

    class FakeProcess:
        stderr = BytesIO()
        waited = False

        def poll(self) -> int | None:
            return None if not self.waited else 0

        def wait(self, timeout: float | None = None) -> int:
            self.waited = True
            return 0

    process = FakeProcess()

    def start_process(arguments: list[str], **_kwargs: object) -> FakeProcess:
        Path(arguments[-2]).write_text(str(child_pid), encoding="ascii")
        return process

    def fail_after_pid(_predicate: object, _timeout: float, _message: str) -> int:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            return child_pid
        raise TimeoutError("simulated heartbeat failure")

    monkeypatch.setattr(test_contract.shutil, "which", lambda _name: "/usr/bin/systemd-run")
    monkeypatch.setattr(test_contract.subprocess, "Popen", start_process)
    monkeypatch.setattr(test_contract.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(test_contract, "_wait_for", fail_after_pid)

    with pytest.raises(TimeoutError, match="simulated heartbeat failure"):
        test_contract._start_systemd_child(tmp_path, "fixture.service", ["--user"])

    assert signals == [(child_pid, signal.SIGCONT), (child_pid, signal.SIGTERM)]
    assert process.waited
