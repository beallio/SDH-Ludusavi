"""A cancellable, project-owned executor for Ludusavi subprocesses.

The vendored ``pyludusavi`` executor uses ``subprocess.run``, which cannot be
cancelled after the call has entered a worker thread.  This module preserves
that executor's public command/response contract while keeping every managed
non-spawn command in its own process group so a timeout or scoped cancellation
can stop the command and its descendants together.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
import signal
import subprocess
import threading
from typing import Any, Literal, overload
from uuid import uuid4

from pyludusavi import (
    LudusaviContractError,
    LudusaviError,
    LudusaviExecutionError,
    LudusaviResponse,
    LudusaviTimeoutError,
)
from pyludusavi._environment import resolve_environment
from pyludusavi.core import LudusaviExecutor


_TERMINATE_GRACE_SECONDS = 0.5
_KILL_GRACE_SECONDS = 1.0


class LudusaviOperationCancelledError(LudusaviError):
    """Raised when a managed Ludusavi operation is explicitly cancelled."""


@dataclass(eq=False)
class _OperationToken:
    executor: ManagedLudusaviExecutor
    identifier: str = field(default_factory=lambda: uuid4().hex)
    cancellation_requested: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> bool:
        """Cancel only processes registered under this exact token."""
        return self.executor._cancel_token(self)


@dataclass(eq=False)
class _ProcessRecord:
    token: _OperationToken | None
    process: subprocess.Popen[str]
    completion: threading.Event = field(default_factory=threading.Event)
    cancellation_requested: threading.Event = field(default_factory=threading.Event)
    state_lock: threading.Lock = field(default_factory=threading.Lock)
    terminate_sent: bool = False
    kill_sent: bool = False


class ManagedLudusaviExecutor(LudusaviExecutor):
    """Execute Ludusavi commands with token-scoped process-group cancellation."""

    def __init__(self, command_prefix: list[str], env: Mapping[str, str] | None = None) -> None:
        self.command_prefix = command_prefix
        self.env = resolve_environment(env)
        self._records: dict[str, _ProcessRecord] = {}
        self._records_lock = threading.Lock()
        self._thread_state = threading.local()
        self._shutdown = False

    @contextmanager
    def operation_scope(self) -> Iterator[_OperationToken]:
        """Bind one unique, cancellable token to commands on the current thread."""
        token = _OperationToken(self)
        previous_token = getattr(self._thread_state, "token", None)
        self._thread_state.token = token
        try:
            yield token
        finally:
            self._thread_state.token = previous_token

    @overload
    def execute(
        self,
        args: list[str],
        mode: Literal["JSON", "TEXT", "STDIN_JSON"] = ...,
        input_data: Any | None = ...,
        timeout: float | None = ...,
        env: Mapping[str, str] | None = ...,
        auto_api: bool = ...,
    ) -> LudusaviResponse[Any]: ...

    @overload
    def execute(
        self,
        args: list[str],
        mode: Literal["SPAWN"],
        input_data: Any | None = ...,
        timeout: float | None = ...,
        env: Mapping[str, str] | None = ...,
        auto_api: bool = ...,
    ) -> None: ...

    def execute(
        self,
        args: list[str],
        mode: Literal["JSON", "TEXT", "SPAWN", "STDIN_JSON"] = "JSON",
        input_data: Any | None = None,
        timeout: float | None = 30.0,
        env: Mapping[str, str] | None = None,
        auto_api: bool = True,
    ) -> LudusaviResponse[Any] | None:
        """Execute a command with pyludusavi-compatible response semantics."""
        full_command = [*self.command_prefix, *args]
        if auto_api and mode in ("JSON", "STDIN_JSON") and "--api" not in full_command:
            full_command.append("--api")

        subprocess_env = self._resolve_environment(env)
        if mode == "SPAWN":
            subprocess.Popen(full_command, env=subprocess_env)
            return None

        self._raise_if_shutdown()
        stdin_content = (
            json.dumps(input_data) if mode == "STDIN_JSON" and input_data is not None else None
        )
        process = subprocess.Popen(
            full_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=subprocess_env,
            start_new_session=True,
        )
        record = _ProcessRecord(token=self._current_token(), process=process)
        record_key = uuid4().hex
        cancelled_before_wait = self._register_record(record_key, record)

        try:
            if cancelled_before_wait:
                self._request_cancel(record, wait_for_completion=False)
            try:
                stdout, stderr = process.communicate(input=stdin_content, timeout=timeout)
            except subprocess.TimeoutExpired:
                self._request_cancel(record, wait_for_completion=False)
                self._reap_after_timeout(record)
                raise LudusaviTimeoutError("Ludusavi command exceeded its configured timeout")

            if record.cancellation_requested.is_set():
                raise LudusaviOperationCancelledError("Ludusavi operation was cancelled")
            if process.returncode != 0:
                raise LudusaviExecutionError(full_command, process.returncode, stdout, stderr)
            if mode in ("JSON", "STDIN_JSON"):
                try:
                    data = json.loads(stdout)
                except json.JSONDecodeError as exc:
                    raise LudusaviContractError("Failed to parse Ludusavi JSON output") from exc
                return LudusaviResponse(data=data, raw=data, warnings=stderr, command=full_command)
            return LudusaviResponse(
                data=stdout,
                raw=stdout,
                warnings=stderr,
                command=full_command,
            )
        finally:
            self._complete_record(record_key, record)

    def cancel_all(self) -> bool:
        """Request cancellation for every currently managed command and reap it."""
        with self._records_lock:
            records = tuple(self._records.values())
        for record in records:
            record.cancellation_requested.set()
            self._request_cancel(record, wait_for_completion=False)
        return self._wait_for_records(records)

    def shutdown(self) -> bool:
        """Reject new managed commands and cancel every command already running."""
        with self._records_lock:
            self._shutdown = True
        return self.cancel_all()

    def _current_token(self) -> _OperationToken | None:
        token = getattr(self._thread_state, "token", None)
        return token if isinstance(token, _OperationToken) else None

    def _resolve_environment(self, env: Mapping[str, str] | None) -> dict[str, str] | None:
        if env is None:
            return self.env
        if self.env is None:
            return resolve_environment(env)
        return {**self.env, **env}

    def _raise_if_shutdown(self) -> None:
        with self._records_lock:
            if self._shutdown:
                raise LudusaviOperationCancelledError("Ludusavi executor is shutting down")

    def _register_record(self, record_key: str, record: _ProcessRecord) -> bool:
        with self._records_lock:
            self._records[record_key] = record
            cancelled = self._shutdown or (
                record.token is not None and record.token.cancellation_requested.is_set()
            )
            if cancelled:
                record.cancellation_requested.set()
            return cancelled

    def _complete_record(self, record_key: str, record: _ProcessRecord) -> None:
        with self._records_lock:
            if self._records.get(record_key) is record:
                del self._records[record_key]
            record.completion.set()

    def _cancel_token(self, token: _OperationToken) -> bool:
        token.cancellation_requested.set()
        with self._records_lock:
            records = tuple(record for record in self._records.values() if record.token is token)
        for record in records:
            record.cancellation_requested.set()
            self._request_cancel(record, wait_for_completion=False)
        return self._wait_for_records(records)

    def _request_cancel(self, record: _ProcessRecord, *, wait_for_completion: bool) -> bool:
        record.cancellation_requested.set()
        self._signal_process_group(record, signal.SIGTERM)
        if not wait_for_completion:
            return True
        return self._wait_for_completion(record)

    def _wait_for_completion(self, record: _ProcessRecord) -> bool:
        if record.completion.wait(_TERMINATE_GRACE_SECONDS):
            return True
        self._signal_process_group(record, signal.SIGKILL)
        return record.completion.wait(_KILL_GRACE_SECONDS)

    def _wait_for_records(self, records: tuple[_ProcessRecord, ...]) -> bool:
        """Wait for every captured record even when an earlier one cannot be reaped."""
        all_completed = True
        for record in records:
            if not self._wait_for_completion(record):
                all_completed = False
        return all_completed

    def _signal_process_group(self, record: _ProcessRecord, sig: signal.Signals) -> None:
        with record.state_lock:
            if record.completion.is_set() or record.process.returncode is not None:
                return
            if sig == signal.SIGTERM:
                if record.terminate_sent:
                    return
                record.terminate_sent = True
            elif record.kill_sent:
                return
            else:
                record.kill_sent = True
            try:
                os.killpg(record.process.pid, sig)
            except ProcessLookupError:
                return

    def _reap_after_timeout(self, record: _ProcessRecord) -> None:
        process = record.process
        try:
            process.communicate(timeout=_TERMINATE_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        self._signal_process_group(record, signal.SIGKILL)
        try:
            process.communicate(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            raise LudusaviTimeoutError("Ludusavi command did not exit after cancellation") from None
