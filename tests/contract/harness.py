from __future__ import annotations

from concurrent.futures import Future, TimeoutError
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_BIN = Path(__file__).resolve().parent / "fakes"
PROTOCOL_TIMEOUT = 10.0
STOP_TIMEOUT = 5.0


class ContractHarness:
    """Run a backend as Decky's loader and speak its newline-delimited socket protocol."""

    def __init__(
        self,
        *,
        backend: str | None = None,
        root: Path | None = None,
        scenario: dict[str, Any] | None = None,
    ) -> None:
        self._owned_root = (
            tempfile.TemporaryDirectory(prefix="sdh-contract-") if root is None else None
        )
        self.root = Path(self._owned_root.name) if self._owned_root else root
        assert self.root is not None
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)

        self.settings_dir = self.root / "settings"
        self.runtime_dir = self.root / "runtime"
        self.log_dir = self.root / "logs"
        self.plugin_dir = self.root / "plugin"
        self.home = self.root / "home"
        self.decky_home = self.root / "decky-home"
        self.xdg_config = self.root / "xdg-config"
        self.xdg_data = self.root / "xdg-data"
        self.xdg_cache = self.root / "xdg-cache"
        self.xdg_state = self.root / "xdg-state"
        self.config_dir = self.xdg_config / "ludusavi"
        self.backup_root = self.root / "ludusavi-backups"
        self.socket_path = self.runtime_dir / "plugin.sock"
        self.scenario_path = self.root / "scenario.json"
        self.fake_log_path = self.root / "fake-processes.jsonl"
        self.systemctl_log_path = self.root / "systemctl.jsonl"
        self.stdout_path = self.root / "backend.stdout"
        self.stderr_path = self.root / "backend.stderr"

        for directory in (
            self.settings_dir,
            self.runtime_dir,
            self.log_dir,
            self.plugin_dir,
            self.home,
            self.decky_home,
            self.xdg_config,
            self.xdg_data,
            self.xdg_cache,
            self.xdg_state,
            self.config_dir,
            self.backup_root,
        ):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)
        shutil.copytree(REPO_ROOT / "theme", self.plugin_dir / "theme")
        (self.config_dir / "config.yaml").write_text("backup: {}\n", encoding="utf-8")

        self.env = os.environ.copy()
        for name in (
            "SYNCTHING_API_KEY",
            "SYNCTHING_API_URL",
            "SYNCTHING_CONFIG_FILE",
            "STCONFDIR",
            "STHOMEDIR",
        ):
            self.env.pop(name, None)
        current_path = os.environ.get("PATH", "")
        self.env.update(
            {
                "DECKY_PLUGIN_SETTINGS_DIR": str(self.settings_dir),
                "DECKY_PLUGIN_RUNTIME_DIR": str(self.runtime_dir),
                "DECKY_PLUGIN_LOG_DIR": str(self.log_dir),
                "DECKY_PLUGIN_DIR": str(self.plugin_dir),
                "DECKY_PLUGIN_NAME": "SDH-Ludusavi",
                "DECKY_PLUGIN_VERSION": "0.0.0-contract",
                "DECKY_PLUGIN_AUTHOR": "contract tests",
                "DECKY_HOME": str(self.decky_home),
                "DECKY_USER": "contract-user",
                "DECKY_USER_HOME": str(self.home),
                "DECKY_VERSION": "contract-loader",
                "HOME": str(self.home),
                "USER": "contract-user",
                "DECKY_PLUGIN_SOCKET": str(self.socket_path),
                "XDG_CONFIG_HOME": str(self.xdg_config),
                "XDG_DATA_HOME": str(self.xdg_data),
                "XDG_CACHE_HOME": str(self.xdg_cache),
                "XDG_STATE_HOME": str(self.xdg_state),
                "XDG_RUNTIME_DIR": str(self.runtime_dir),
                "SDH_CONTRACT_SCENARIO": str(self.scenario_path),
                "SDH_CONTRACT_FAKE_LOG": str(self.fake_log_path),
                "SDH_CONTRACT_SYSTEMCTL_LOG": str(self.systemctl_log_path),
                "SDH_CONTRACT_LUDUSAVI_CONFIG_DIR": str(self.config_dir),
                "SDH_CONTRACT_BACKUP_ROOT": str(self.backup_root),
                "SDH_CONTRACT_SAVE_FILE": str(self.root / "save.dat"),
                "PYTHONPATH": os.pathsep.join(
                    [str(REPO_ROOT / "py_modules"), str(REPO_ROOT), self.env.get("PYTHONPATH", "")]
                ),
                "PATH": os.pathsep.join([str(FAKE_BIN), current_path]),
            }
        )
        self.backend = (
            backend if backend is not None else os.environ.get("SDH_CONTRACT_BACKEND", "python")
        )
        self.set_scenario(scenario or {})
        self.process: subprocess.Popen[bytes] | None = None
        self.connection: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._pending: dict[str, Future[tuple[bool, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stopping = False
        self._reader_error: BaseException | None = None
        self._events: list[dict[str, Any]] = []

    def set_scenario(self, scenario: dict[str, Any]) -> None:
        self.scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    def _check_fakes(self) -> None:
        for command in ("flatpak", "systemctl"):
            expected = str(FAKE_BIN / command)
            resolved = shutil.which(command, path=self.env["PATH"])
            if resolved != expected:
                raise RuntimeError(
                    f"contract harness refused to start: {command} resolves to {resolved!r}, "
                    f"not the contract fake {expected!r}"
                )

    def start(self) -> ContractHarness:
        if self.process is not None:
            raise RuntimeError("contract backend is already running")
        self._stopping = False
        try:
            self._check_fakes()
        except Exception:
            self.close()
            raise
        if self.backend == "python":
            command = [sys.executable, str(REPO_ROOT / "tests/contract/host.py")]
        else:
            executable = Path(self.backend)
            if not executable.is_file() or not os.access(executable, os.X_OK):
                self.close()
                raise RuntimeError(f"contract backend executable is not runnable: {self.backend}")
            command = [str(executable)]

        stdout_file = self.stdout_path.open("ab")
        stderr_file = self.stderr_path.open("ab")
        try:
            self.process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
        finally:
            stdout_file.close()
            stderr_file.close()

        deadline = time.monotonic() + PROTOCOL_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise self._startup_failure("backend exited before creating its socket")
            if self.socket_path.exists():
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    connection.connect(str(self.socket_path))
                except OSError:
                    connection.close()
                    time.sleep(0.01)
                    continue
                self.connection = connection
                self._reader = threading.Thread(target=self._read_replies, daemon=True)
                self._reader.start()
                return self
            time.sleep(0.01)
        raise self._startup_failure("backend did not create its socket in time")

    def _backend_failure(self, message: str) -> str:
        stdout = self.stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = self.stderr_path.read_text(encoding="utf-8", errors="replace")
        return f"{message}\nbackend stdout:\n{stdout}\nbackend stderr:\n{stderr}"

    def _startup_failure(self, message: str) -> RuntimeError:
        details = self._backend_failure(message)
        try:
            self.close()
        except Exception as exc:
            details += f"\nstartup cleanup failed: {exc}"
        return RuntimeError(details)

    def _read_replies(self) -> None:
        assert self.connection is not None
        buffer = bytearray()
        try:
            while True:
                chunk = self.connection.recv(65536)
                if not chunk:
                    raise ConnectionError("backend closed the RPC socket")
                buffer.extend(chunk)
                while (newline := buffer.find(b"\n")) >= 0:
                    line = bytes(buffer[:newline])
                    del buffer[: newline + 1]
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("RPC message is not an object")
                    message_type = message.get("type")
                    if message_type == 2:
                        self._events.append(message)
                    elif message_type == 1:
                        request_id = message.get("id")
                        if not isinstance(request_id, str):
                            raise ValueError("RPC reply ID is not a string")
                        success = message.get("success")
                        if type(success) is not bool:
                            raise ValueError("RPC reply success is not a boolean")
                        if "res" not in message:
                            raise ValueError("RPC reply is missing res")
                        with self._pending_lock:
                            pending = self._pending.get(request_id)
                            if pending is not None and not pending.done():
                                pending.set_result((success, message["res"]))
        except (OSError, ValueError, ConnectionError) as exc:
            self._reader_error = exc
            with self._pending_lock:
                for pending in self._pending.values():
                    if not pending.done():
                        pending.set_exception(ConnectionError(f"backend RPC socket failed: {exc}"))

    def call(self, method: str, *args: Any, timeout: float = 10.0) -> tuple[bool, Any]:
        if self.connection is None:
            raise RuntimeError("contract backend is not connected")
        with self._pending_lock:
            if self._stopping:
                raise RuntimeError("contract backend is stopping")
            request_id = str(uuid.uuid4())
            pending: Future[tuple[bool, Any]] = Future()
            self._pending[request_id] = pending
        request = json.dumps({"type": 0, "method": method, "id": request_id, "args": list(args)})
        try:
            with self._send_lock:
                self.connection.sendall((request + "\n").encode("utf-8"))
            return pending.result(timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(f"RPC {method!r} timed out after {timeout}s") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def restart(self) -> ContractHarness:
        self.stop()
        return self.start()

    def stop(self) -> None:
        process = self.process
        with self._pending_lock:
            self._stopping = True
            pending_calls = tuple(self._pending.values())
            self._pending.clear()
            for pending in pending_calls:
                if not pending.done():
                    pending.set_exception(ConnectionError("backend is shutting down"))
        if process is None:
            return
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                self._kill_process_group(process.pid)
                process.wait()
                self._close_connection()
                self.process = None
                details = self._backend_failure(
                    f"backend exceeded the {STOP_TIMEOUT:g}s SIGTERM shutdown limit"
                )
                raise AssertionError(f"{details}; the process group was killed")
        self._kill_process_group(process.pid)
        self._close_connection()
        self.process = None

    @staticmethod
    def _kill_process_group(pgid: int) -> None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _close_connection(self) -> None:
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        if self._reader is not None:
            self._reader.join(timeout=1)
            self._reader = None

    def uninstall(self) -> None:
        if self.connection is None:
            raise RuntimeError("contract backend is not connected")
        with self._send_lock:
            self.connection.sendall(b'{"uninstall":true}\n')
        time.sleep(0.025)
        self.stop()

    def fake_processes(self) -> list[dict[str, Any]]:
        return self._read_json_lines(self.fake_log_path)

    def systemctl_calls(self) -> list[dict[str, Any]]:
        return self._read_json_lines(self.systemctl_log_path)

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    @staticmethod
    def _read_json_lines(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def close(self) -> None:
        try:
            self.stop()
        finally:
            if self._owned_root is not None:
                self._owned_root.cleanup()
