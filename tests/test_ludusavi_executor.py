"""Contract tests for the project-owned, cancellable Ludusavi executor."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import pytest

from pyludusavi import LudusaviContractError, LudusaviExecutionError, LudusaviTimeoutError


_HELPER_SOURCE = r"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

action = sys.argv[1]
arguments = sys.argv[2:]

if action == "json":
    print(json.dumps({"arguments": arguments, "base": os.environ.get("BASE")}))
elif action == "text":
    print("plain response")
elif action == "stdin-json":
    print(json.dumps({"input": json.load(sys.stdin), "arguments": arguments}))
elif action == "bad-json":
    print("not json")
elif action == "fail":
    print("expected stdout")
    print("expected stderr", file=sys.stderr)
    raise SystemExit(7)
elif action == "spawn":
    Path(os.environ["SPAWN_FILE"]).write_text("started", encoding="utf-8")
elif action == "tree":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(os.environ["PID_FILE"]).write_text(
        f"{os.getpid()} {child.pid}", encoding="utf-8"
    )
    while True:
        time.sleep(1)
else:
    raise RuntimeError(f"unknown action: {action}")
"""


def _managed_executor_module() -> Any:
    return importlib.import_module("sdh_ludusavi.ludusavi_executor")


def _new_executor(command_prefix: list[str], env: dict[str, str] | None = None) -> Any:
    module = _managed_executor_module()
    return module.ManagedLudusaviExecutor(command_prefix, env=env)


def _helper_command(tmp_path: Path) -> list[str]:
    helper = tmp_path / "ludusavi_helper.py"
    helper.write_text(_HELPER_SOURCE, encoding="utf-8")
    return [sys.executable, str(helper)]


def _wait_for_text(path: Path, timeout: float = 2.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return path.read_text(encoding="utf-8")
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for helper output at {path.name}")


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False

    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists():
        return False
    try:
        return stat_path.read_text(encoding="utf-8").split()[2] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def _wait_until_stopped(pid: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_running(pid):
            return
        time.sleep(0.01)
    raise AssertionError(f"process {pid} remained running after cancellation")


def test_process_check_treats_a_vanished_proc_entry_as_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The process can exit after the probe succeeds but before /proc is read."""

    def vanished_proc_entry(self: Path, *, encoding: str) -> str:
        del self, encoding
        raise FileNotFoundError

    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "read_text", vanished_proc_entry)

    assert _is_running(4242) is False


def test_process_check_treats_a_proc_lookup_race_as_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux can report this equivalent disappearance exception while reading /proc."""

    def vanished_proc_entry(self: Path, *, encoding: str) -> str:
        del self, encoding
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "read_text", vanished_proc_entry)

    assert _is_running(4242) is False


def test_managed_executor_preserves_pyludusavi_json_text_stdin_and_error_contracts(
    tmp_path: Path,
) -> None:
    executor = _new_executor(_helper_command(tmp_path), env={"BASE": "adapter"})

    json_response = executor.execute(["json"], mode="JSON")
    assert json_response.data == {"arguments": ["--api"], "base": "adapter"}
    assert json_response.raw == json_response.data
    assert json_response.warnings == ""
    assert json_response.command[-2:] == ["json", "--api"]

    text_response = executor.execute(["text"], mode="TEXT")
    assert text_response.data == "plain response\n"
    assert text_response.raw == "plain response\n"

    stdin_response = executor.execute(
        ["stdin-json"], mode="STDIN_JSON", input_data={"game": "Hades"}
    )
    assert stdin_response.data == {
        "input": {"game": "Hades"},
        "arguments": ["--api"],
    }

    with pytest.raises(LudusaviExecutionError) as execution_error:
        executor.execute(["fail"], mode="TEXT")
    assert execution_error.value.returncode == 7
    assert execution_error.value.stdout == "expected stdout\n"
    assert execution_error.value.stderr == "expected stderr\n"

    with pytest.raises(LudusaviContractError):
        executor.execute(["bad-json"], mode="JSON")


def test_managed_executor_merges_per_command_environment_and_preserves_spawn_mode(
    tmp_path: Path,
) -> None:
    spawn_file = tmp_path / "spawned.txt"
    executor = _new_executor(
        _helper_command(tmp_path),
        env={"BASE": "adapter", "SPAWN_FILE": str(spawn_file)},
    )

    response = executor.execute(["json"], mode="JSON", env={"BASE": "override"})
    assert response.data["base"] == "override"

    assert executor.execute(["spawn"], mode="SPAWN") is None
    assert _wait_for_text(spawn_file) == "started"


def test_timeout_cancels_and_reaps_the_entire_managed_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "timeout-pids.txt"
    executor = _new_executor(
        _helper_command(tmp_path),
        env={"PID_FILE": str(pid_file)},
    )

    with pytest.raises(LudusaviTimeoutError) as timeout_error:
        executor.execute(["tree"], mode="TEXT", timeout=0.1)

    parent_pid, child_pid = (int(pid) for pid in _wait_for_text(pid_file).split())
    _wait_until_stopped(parent_pid)
    _wait_until_stopped(child_pid)
    assert str(tmp_path) not in str(timeout_error.value)
    assert len(str(timeout_error.value)) < 512


def test_token_cancellation_stops_only_its_own_process_group(tmp_path: Path) -> None:
    executor = _new_executor(_helper_command(tmp_path))
    first_token: queue.Queue[Any] = queue.Queue()
    second_token: queue.Queue[Any] = queue.Queue()
    failures: queue.Queue[BaseException] = queue.Queue()

    def run_tree(token_queue: queue.Queue[Any], pid_file: Path) -> None:
        try:
            with executor.operation_scope() as token:
                token_queue.put(token)
                executor.execute(
                    ["tree"], mode="TEXT", timeout=5.0, env={"PID_FILE": str(pid_file)}
                )
        except BaseException as exc:
            failures.put(exc)

    first_pids = tmp_path / "first-pids.txt"
    second_pids = tmp_path / "second-pids.txt"
    first_thread = threading.Thread(target=run_tree, args=(first_token, first_pids))
    second_thread = threading.Thread(target=run_tree, args=(second_token, second_pids))
    first_thread.start()
    second_thread.start()

    first = first_token.get(timeout=1)
    second = second_token.get(timeout=1)
    first_parent, first_child = (int(pid) for pid in _wait_for_text(first_pids).split())
    second_parent, second_child = (int(pid) for pid in _wait_for_text(second_pids).split())

    first.cancel()
    first_thread.join(timeout=2)
    assert not first_thread.is_alive()
    cancelled_error = getattr(_managed_executor_module(), "LudusaviOperationCancelledError")
    assert isinstance(failures.get(timeout=1), cancelled_error)
    _wait_until_stopped(first_parent)
    _wait_until_stopped(first_child)
    assert _is_running(second_parent)
    assert _is_running(second_child)

    second.cancel()
    second_thread.join(timeout=2)
    assert not second_thread.is_alive()
    assert isinstance(failures.get(timeout=1), cancelled_error)
    _wait_until_stopped(second_parent)
    _wait_until_stopped(second_child)


def test_completed_token_cannot_cancel_a_later_real_process_group(
    tmp_path: Path,
) -> None:
    executor = _new_executor(_helper_command(tmp_path))

    with executor.operation_scope() as completed_token:
        assert executor.execute(["text"], mode="TEXT").data == "plain response\n"
    completed_token.cancel()
    completed_token.cancel()

    active_token: queue.Queue[Any] = queue.Queue()
    failures: queue.Queue[BaseException] = queue.Queue()
    active_pids = tmp_path / "active-pids.txt"

    def run_later_tree() -> None:
        try:
            with executor.operation_scope() as token:
                active_token.put(token)
                executor.execute(
                    ["tree"], mode="TEXT", timeout=5.0, env={"PID_FILE": str(active_pids)}
                )
        except BaseException as exc:
            failures.put(exc)

    active_thread = threading.Thread(target=run_later_tree)
    active_thread.start()
    later_token = active_token.get(timeout=1)
    later_parent, later_child = (int(pid) for pid in _wait_for_text(active_pids).split())

    completed_token.cancel()
    assert _is_running(later_parent)
    assert _is_running(later_child)

    later_token.cancel()
    active_thread.join(timeout=2)
    assert not active_thread.is_alive()
    cancelled_error = getattr(_managed_executor_module(), "LudusaviOperationCancelledError")
    assert isinstance(failures.get(timeout=1), cancelled_error)
    _wait_until_stopped(later_parent)
    _wait_until_stopped(later_child)


def test_completed_token_cannot_cancel_later_pid_reuse_fake_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A completed token must not signal a newer record with the recycled PID."""

    module = _managed_executor_module()
    reused_pid = 4242

    class FakeProcess:
        def __init__(self, *, complete: bool) -> None:
            self.args: list[str] = []
            self.pid = reused_pid
            self.returncode: int | None = 0 if complete else None
            self._finished = threading.Event()
            if complete:
                self._finished.set()

        def communicate(
            self,
            input: str | None = None,
            timeout: float | None = None,
        ) -> tuple[str, str]:
            del input
            if not self._finished.wait(timeout):
                raise subprocess.TimeoutExpired(self.args, timeout)
            return "plain response\n", ""

        def wait(self, timeout: float | None = None) -> int:
            if not self._finished.wait(timeout):
                raise subprocess.TimeoutExpired(self.args, timeout)
            assert self.returncode is not None
            return self.returncode

        def poll(self) -> int | None:
            return self.returncode

        def finish(self, returncode: int) -> None:
            self.returncode = returncode
            self._finished.set()

    completed_process = FakeProcess(complete=True)
    active_process = FakeProcess(complete=False)
    processes: queue.Queue[FakeProcess] = queue.Queue()
    processes.put(completed_process)
    processes.put(active_process)
    process_group_signals: list[tuple[int, signal.Signals]] = []

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        del args, kwargs
        return processes.get_nowait()

    def fake_killpg(pgid: int, sig: signal.Signals) -> None:
        process_group_signals.append((pgid, sig))
        assert pgid == reused_pid
        active_process.finish(-int(sig))

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.os, "killpg", fake_killpg)
    executor = _new_executor(_helper_command(tmp_path))

    with executor.operation_scope() as completed_token:
        assert executor.execute(["text"], mode="TEXT").data == "plain response\n"

    active_token: queue.Queue[Any] = queue.Queue()
    failures: queue.Queue[BaseException] = queue.Queue()

    def run_reused_pid_process() -> None:
        try:
            with executor.operation_scope() as token:
                active_token.put(token)
                executor.execute(["text"], mode="TEXT", timeout=5.0)
        except BaseException as exc:
            failures.put(exc)

    active_thread = threading.Thread(target=run_reused_pid_process)
    active_thread.start()
    later_token = active_token.get(timeout=1)
    assert later_token is not completed_token
    assert active_process.poll() is None

    completed_token.cancel()
    assert process_group_signals == []
    assert active_process.poll() is None
    assert active_thread.is_alive()

    later_token.cancel()
    active_thread.join(timeout=2)
    assert not active_thread.is_alive()
    assert process_group_signals == [(reused_pid, signal.SIGTERM)]
    cancelled_error = getattr(module, "LudusaviOperationCancelledError")
    assert isinstance(failures.get(timeout=1), cancelled_error)


def test_completed_process_cannot_be_signalled_during_final_deregistration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A completed owned process must not be signalled before registry cleanup finishes."""

    module = _managed_executor_module()
    process_group_signals: list[tuple[int, signal.Signals]] = []

    class CompletedProcess:
        args: list[str] = []
        pid = 4242

        def __init__(self) -> None:
            self.returncode: int | None = None

        def communicate(
            self,
            input: str | None = None,
            timeout: float | None = None,
        ) -> tuple[str, str]:
            del input, timeout
            self.returncode = 0
            return "plain response\n", ""

        def poll(self) -> int | None:
            return self.returncode

    process = CompletedProcess()

    def fake_popen(*args: object, **kwargs: object) -> CompletedProcess:
        del args, kwargs
        return process

    def fake_killpg(pgid: int, sig: signal.Signals) -> None:
        process_group_signals.append((pgid, sig))

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.os, "killpg", fake_killpg)
    executor = _new_executor(_helper_command(tmp_path))
    original_complete_record = executor._complete_record
    original_wait_for_completion = executor._wait_for_completion
    cleanup_entered = threading.Event()
    allow_cleanup = threading.Event()
    wait_entered = threading.Event()
    token_queue: queue.Queue[Any] = queue.Queue()
    cancellation_results: queue.Queue[bool] = queue.Queue()
    worker_errors: queue.Queue[BaseException] = queue.Queue()

    def block_complete_record(record_key: str, record: Any) -> None:
        cleanup_entered.set()
        assert allow_cleanup.wait(timeout=2)
        original_complete_record(record_key, record)

    def track_wait_for_completion(record: Any) -> bool:
        wait_entered.set()
        return original_wait_for_completion(record)

    monkeypatch.setattr(executor, "_complete_record", block_complete_record)
    monkeypatch.setattr(executor, "_wait_for_completion", track_wait_for_completion)

    def run_completed_command() -> None:
        try:
            with executor.operation_scope() as token:
                token_queue.put(token)
                executor.execute(["text"], mode="TEXT", timeout=5.0)
        except BaseException as exc:
            worker_errors.put(exc)

    worker = threading.Thread(target=run_completed_command)
    worker.start()
    token = token_queue.get(timeout=1)
    assert cleanup_entered.wait(timeout=1)

    canceller = threading.Thread(target=lambda: cancellation_results.put(token.cancel()))
    canceller.start()
    assert wait_entered.wait(timeout=1)
    try:
        assert process.returncode == 0
        assert process_group_signals == []
    finally:
        allow_cleanup.set()

    canceller.join(timeout=2)
    worker.join(timeout=2)
    assert not canceller.is_alive()
    assert not worker.is_alive()
    assert cancellation_results.get(timeout=1) is True
    assert worker_errors.empty()


def test_cancel_all_waits_for_every_captured_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed first wait must not skip later records captured by cancel-all."""

    module = _managed_executor_module()
    executor = _new_executor(_helper_command(tmp_path))
    first = module._ProcessRecord(token=None, process=object())
    second = module._ProcessRecord(token=None, process=object())
    executor._records = {"first": first, "second": second}
    cancellation_requests: list[Any] = []
    waited_records: list[Any] = []

    def fake_request_cancel(record: Any, *, wait_for_completion: bool) -> bool:
        assert wait_for_completion is False
        cancellation_requests.append(record)
        return True

    def fake_wait_for_completion(record: Any) -> bool:
        waited_records.append(record)
        return record is second

    monkeypatch.setattr(executor, "_request_cancel", fake_request_cancel)
    monkeypatch.setattr(executor, "_wait_for_completion", fake_wait_for_completion)

    assert executor.cancel_all() is False
    assert cancellation_requests == [first, second]
    assert waited_records == [first, second]


def test_token_cancellation_waits_for_every_captured_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed token-scoped wait must not skip a second owned record."""

    module = _managed_executor_module()
    executor = _new_executor(_helper_command(tmp_path))
    token = module._OperationToken(executor)
    first = module._ProcessRecord(token=token, process=object())
    second = module._ProcessRecord(token=token, process=object())
    executor._records = {"first": first, "second": second}
    cancellation_requests: list[Any] = []
    waited_records: list[Any] = []

    def fake_request_cancel(record: Any, *, wait_for_completion: bool) -> bool:
        assert wait_for_completion is False
        cancellation_requests.append(record)
        return True

    def fake_wait_for_completion(record: Any) -> bool:
        waited_records.append(record)
        return record is second

    monkeypatch.setattr(executor, "_request_cancel", fake_request_cancel)
    monkeypatch.setattr(executor, "_wait_for_completion", fake_wait_for_completion)

    assert token.cancel() is False
    assert cancellation_requests == [first, second]
    assert waited_records == [first, second]


def test_adapter_installs_managed_executor_without_breaking_new_only_test_clients(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import pyludusavi

    from sdh_ludusavi.ludusavi import PyludusaviAdapter

    class FakeLudusavi:
        command_prefix = _helper_command(tmp_path)

        def __init__(self, **kwargs: object) -> None:
            self.executor = object()

    monkeypatch.setattr(pyludusavi, "Ludusavi", FakeLudusavi)
    adapter = PyludusaviAdapter()
    assert isinstance(adapter._client.executor, _managed_executor_module().ManagedLudusaviExecutor)

    class NewOnlyClient:
        def backup(self, **kwargs: object) -> Any:
            return type("Response", (), {"data": {"games": {}}})()

    test_adapter = PyludusaviAdapter.__new__(PyludusaviAdapter)
    test_adapter._client = NewOnlyClient()
    assert test_adapter.backup("Hades") == {"games": {}}
