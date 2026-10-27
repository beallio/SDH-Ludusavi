from __future__ import annotations

import json
from pathlib import Path
import sys
import shutil
import subprocess
import time
from typing import Any
from uuid import UUID, uuid4

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    import test_contract

    unit = f"sdh-contract-no-heartbeat-{uuid4().hex}.service"
    wait_for = test_contract._wait_for

    def fail_after_pid(predicate: Any, timeout: float, message: str) -> Any:
        if message == "systemd child heartbeat did not start":
            raise TimeoutError("simulated heartbeat failure")
        return wait_for(predicate, timeout, message)

    monkeypatch.setattr(test_contract, "_wait_for", fail_after_pid)
    try:
        with pytest.raises(TimeoutError, match="simulated heartbeat failure"):
            test_contract._start_systemd_child(
                tmp_path, unit, ["--user", "--wait", "--quiet"], request
            )
        assert _unit_load_state(unit) == "not-found"
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False, timeout=5)


def _unit_load_state(unit: str) -> str:
    return subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=LoadState", "--value"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()


def test_systemd_fixture_stops_unit_after_client_exits(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    import test_contract

    unit = f"sdh-contract-client-{uuid4().hex}.service"
    child = test_contract._start_systemd_child(
        tmp_path, unit, ["--user", "--wait", "--quiet"], request
    )
    state = test_contract._unit_state(unit)
    assert state["Description"] == child.owner.description
    assert state["InvocationID"] == child.owner.invocation_id and child.owner.invocation_id
    lifetime = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=RuntimeMaxUSec", "--value"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    assert lifetime not in {"", "0", "infinity"}
    try:
        child.process.terminate()
        child.process.wait(timeout=3)
        assert _unit_load_state(unit) == "loaded"
        test_contract._stop_child(child)
        assert _unit_load_state(unit) == "not-found"
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False, timeout=5)


def test_systemd_fixture_stops_a_sigstopped_owned_service(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    import os
    import signal
    import test_contract

    unit = f"sdh-contract-stopped-{uuid4().hex}.service"
    child = test_contract._start_systemd_child(
        tmp_path, unit, ["--user", "--wait", "--quiet"], request
    )
    try:
        os.kill(child.pid, signal.SIGSTOP)
        test_contract._wait_for(
            lambda: test_contract._proc_state(child.pid) == "T", 2, "not stopped"
        )
        test_contract._stop_child(child)
        assert _unit_load_state(unit) == "not-found"
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False, timeout=5)


def test_systemd_fixture_cleans_unit_before_pid_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    import test_contract

    unit = f"sdh-contract-no-pid-{uuid4().hex}.service"
    pid_file = tmp_path / f"{unit}.pid"
    callbacks: list[Any] = []
    popen: Any = subprocess.Popen
    systemd_run = shutil.which("systemd-run")
    wait_for = test_contract._wait_for

    class RecordingRequest:
        def addfinalizer(self, callback: Any) -> None:
            callbacks.append(callback)
            request.addfinalizer(callback)

    recording_request: Any = RecordingRequest()

    def without_pid(arguments: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(arguments, list) and arguments[0] == systemd_run and "-c" in arguments:
            arguments = list(arguments)
            arguments[arguments.index("-c") + 1] = "import time; time.sleep(30)"
        return popen(arguments, *args, **kwargs)

    monkeypatch.setattr(test_contract.subprocess, "Popen", without_pid)

    def fail_before_pid(predicate: Any, timeout: float, message: str) -> Any:
        if "systemd-run did not start" in message:
            assert callbacks, "cleanup was not registered before PID publication"
            assert not pid_file.exists(), "fixture unexpectedly published a PID"
            assert _unit_load_state(unit) == "loaded"
            raise TimeoutError("simulated missing PID")
        return wait_for(predicate, timeout, message)

    monkeypatch.setattr(test_contract, "_wait_for", fail_before_pid)
    try:
        with pytest.raises(TimeoutError, match="simulated missing PID"):
            test_contract._start_systemd_child(
                tmp_path, unit, ["--user", "--wait", "--quiet"], recording_request
            )
        assert _unit_load_state(unit) == "not-found"
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False, timeout=5)


def test_systemd_fixture_refuses_a_preexisting_unit(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    import test_contract

    unit = f"sdh-contract-unowned-{uuid4().hex}.service"
    subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit={unit}",
            "--description=unowned-test-fixture",
            "--property=RuntimeMaxSec=30s",
            "--collect",
            "--quiet",
            "/bin/sleep",
            "30",
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    try:
        before = test_contract._unit_state(unit)
        with pytest.raises(pytest.fail.Exception, match="already loaded"):
            test_contract._start_systemd_child(tmp_path, unit, ["--user", "--wait"], request)
        assert test_contract._unit_state(unit) == before
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False, timeout=5)


def test_systemd_fixture_does_not_stop_a_different_invocation(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    import test_contract

    unit = f"sdh-contract-replaced-{uuid4().hex}.service"
    child = test_contract._start_systemd_child(
        tmp_path, unit, ["--user", "--wait", "--quiet"], request
    )
    try:
        identity = child.owner.invocation_id
        child.owner.invocation_id = "0" * 32
        test_contract._stop_child(child)
        assert test_contract._unit_state(unit)["InvocationID"] == identity
        assert _unit_load_state(unit) == "loaded"
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False, timeout=5)


def test_systemd_fixture_escalates_failed_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_contract
    from types import SimpleNamespace

    process = subprocess.Popen(["/bin/true"])
    process.wait(timeout=2)
    owner = test_contract._OwnedUnit("fixture.service", "owned", process, "invocation")
    active = True
    actions: list[str] = []

    def state(_unit: str) -> dict[str, str]:
        if not active:
            return {"LoadState": "not-found"}
        return {"LoadState": "loaded", "Description": "owned", "InvocationID": "invocation"}

    def run(command: list[str], **_kwargs: Any) -> Any:
        nonlocal active
        action = next(item for item in command if item in {"thaw", "stop", "kill"})
        actions.append(action)
        if action == "stop" and actions.count("stop") == 1:
            return SimpleNamespace(returncode=1)
        if action == "stop":
            active = False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(test_contract, "_unit_state", state)
    monkeypatch.setattr(test_contract.subprocess, "run", run)
    test_contract._stop_owned_unit(owner)
    assert actions == ["thaw", "stop", "kill", "stop"]
    assert owner.cleaned


def test_cleanup_failure_for_scoped_child_does_not_skip_prescope_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    import test_contract
    from types import SimpleNamespace

    prescope = SimpleNamespace(unit="prescope")
    scoped = SimpleNamespace(unit="scoped")
    stopped: list[str] = []
    backend: Any = SimpleNamespace(root=tmp_path)
    backend.set_scenario = lambda _scenario: (_ for _ in ()).throw(RuntimeError("test body failed"))
    monkeypatch.setattr(test_contract, "_start_prescope_child", lambda *_args: prescope)
    monkeypatch.setattr(test_contract, "_start_scoped_child", lambda *_args: scoped)

    def stop(child: Any) -> None:
        stopped.append(child.unit)
        if child is scoped:
            raise RuntimeError("scope cleanup failed")

    monkeypatch.setattr(test_contract, "_stop_child", stop)
    with pytest.raises(RuntimeError, match="scope cleanup failed"):
        test_contract.test_hanging_ludusavi_exits_and_reaps_process_group(backend, request)
    assert stopped == ["scoped", "prescope"]
