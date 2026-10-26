from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import signal
import sys
import tempfile
import types
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "py_modules"))


class SettingsManager:
    """Test copy of Decky's JSON SettingsManager semantics."""

    def __init__(self, name: str, settings_directory: str | None = None) -> None:
        directory = Path(settings_directory or Path.home() / ".config" / "decky" / "settings")
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{name}.json"
        self.settings: Any = {}
        try:
            self.path.open("x", encoding="utf-8").close()
        except FileExistsError:
            self.read()

    def read(self) -> None:
        try:
            self.settings = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(exc, file=sys.stderr)

    def getSetting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def setSetting(self, key: str, value: Any) -> Any:
        self.settings[key] = value
        self.commit()
        return value

    def commit(self) -> None:
        try:
            mode = self.path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(self.settings, stream, indent=4, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.chmod(temporary, mode)
            os.replace(temporary, self.path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


class _DeckyLogger:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("sdh-contract-decky")
        self._logger.handlers.clear()
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        handler = logging.FileHandler(directory / "backend.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        self._logger.addHandler(handler)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


active_writer: asyncio.StreamWriter | None = None
write_lock: asyncio.Lock | None = None


async def emit(event: str, *args: Any) -> None:
    if active_writer is None or write_lock is None:
        return
    async with write_lock:
        active_writer.write(
            (json.dumps({"type": 2, "event": event, "args": list(args)}) + "\n").encode("utf-8")
        )
        await active_writer.drain()


def install_environment_modules() -> None:
    decky = types.ModuleType("decky")
    for name in (
        "DECKY_PLUGIN_SETTINGS_DIR",
        "DECKY_PLUGIN_RUNTIME_DIR",
        "DECKY_PLUGIN_LOG_DIR",
        "DECKY_PLUGIN_DIR",
        "DECKY_PLUGIN_NAME",
        "DECKY_PLUGIN_VERSION",
        "DECKY_PLUGIN_AUTHOR",
        "DECKY_PLUGIN_SOCKET",
        "DECKY_HOME",
        "DECKY_USER",
        "DECKY_USER_HOME",
        "DECKY_VERSION",
    ):
        setattr(decky, name, os.environ[name])
    decky.logger = _DeckyLogger(Path(os.environ["DECKY_PLUGIN_LOG_DIR"]))
    decky.emit = emit
    sys.modules["decky"] = decky

    settings = types.ModuleType("settings")
    settings.SettingsManager = SettingsManager
    sys.modules["settings"] = settings


async def serve() -> None:
    global active_writer, write_lock
    install_environment_modules()
    from main import Plugin

    plugin = Plugin()
    await plugin._migration()
    stopping = asyncio.Event()
    uninstalling = False
    write_lock = asyncio.Lock()
    loop = asyncio.get_running_loop()

    loop.add_signal_handler(signal.SIGTERM, stopping.set)

    async def connection_handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal uninstalling
        global active_writer
        active_writer = writer
        in_flight: set[asyncio.Task[None]] = set()

        async def dispatch(message: dict[str, Any]) -> None:
            request_id = message.get("id")
            method_name = message.get("method")
            try:
                if not isinstance(method_name, str):
                    raise RuntimeError("Plugin method name is missing")
                method = getattr(plugin, method_name, None)
                if not callable(method):
                    raise RuntimeError(f"Plugin has no method {method_name}")
                args = message.get("args")
                result = await method(*(args if isinstance(args, list) else []))
                reply = {"type": 1, "id": request_id, "success": True, "res": result}
            except Exception as exc:
                reply = {"type": 1, "id": request_id, "success": False, "res": str(exc)}
            async with write_lock:
                writer.write((json.dumps(reply) + "\n").encode("utf-8"))
                try:
                    await writer.drain()
                except (ConnectionError, OSError):
                    pass

        try:
            while not stopping.is_set():
                line = await reader.readline()
                if not line:
                    break
                message = json.loads(line)
                if message.get("uninstall") is True:
                    uninstalling = True
                    continue
                if message.get("type") != 0:
                    continue
                task = asyncio.create_task(dispatch(message))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)
        finally:
            if active_writer is writer:
                active_writer = None
            writer.close()
            await writer.wait_closed()
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)

    socket_path = Path(os.environ["DECKY_PLUGIN_SOCKET"])
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    server = await asyncio.start_unix_server(connection_handler, path=str(socket_path))
    main_task = asyncio.create_task(plugin._main())

    await stopping.wait()
    server.close()
    if active_writer is not None:
        active_writer.close()
    await server.wait_closed()
    await plugin._unload()
    if uninstalling:
        await plugin._uninstall()
    if not main_task.done():
        main_task.cancel()
    await asyncio.gather(main_task, return_exceptions=True)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
