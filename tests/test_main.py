from __future__ import annotations

import asyncio
import importlib.util
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

from sdh_ludusavi.service import OperationLockedError


class FakeLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.exceptions: list[str] = []

    def info(self, message: str, *args: object) -> None:
        self.infos.append(_format_log(message, args))

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(_format_log(message, args))

    def exception(self, message: str, *args: object) -> None:
        self.exceptions.append(_format_log(message, args))


def _format_log(message: str, args: tuple[object, ...]) -> str:
    return message % args if args else message


def fake_decky_module(
    tmp_path: Path,
    settings_dir: Path | str | None = None,
) -> tuple[types.SimpleNamespace, FakeLogger]:
    logger = FakeLogger()
    decky = types.SimpleNamespace(
        DECKY_USER_HOME=str(tmp_path / "decky-home"),
        DECKY_HOME=str(tmp_path / "decky"),
        logger=logger,
        migrate_logs=lambda *args: None,
        migrate_settings=lambda *args: None,
        migrate_runtime=lambda *args: None,
    )
    if settings_dir is not None:
        decky.DECKY_SETTINGS_DIR = str(settings_dir)
    return decky, logger


def import_main(monkeypatch: pytest.MonkeyPatch, decky: types.SimpleNamespace) -> Any:
    monkeypatch.setitem(sys.modules, "decky", decky)
    sys.modules.pop("main", None)
    spec = importlib.util.spec_from_file_location("main", Path("main.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["main"] = module
    spec.loader.exec_module(module)
    return module


def test_call_does_not_block_event_loop_while_callback_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    async def scenario() -> None:
        def blocking_callback() -> dict[str, str]:
            time.sleep(0.15)
            return {"status": "ok"}

        started = time.perf_counter()
        task = asyncio.create_task(plugin._call("blocking", blocking_callback))
        await asyncio.sleep(0.01)

        assert time.perf_counter() - started < 0.08
        assert await task == {"status": "ok"}

    asyncio.run(scenario())


def test_call_maps_operation_locked_error_from_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def raise_locked() -> dict[str, object]:
        raise OperationLockedError("refresh is already running")

    result = asyncio.run(plugin._call("refresh", raise_locked))

    assert result == {
        "status": "skipped",
        "reason": "operation_running",
        "message": "refresh is already running",
    }
    assert logger.infos == ["refresh skipped: refresh is already running"]


def test_call_maps_generic_exception_from_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def raise_failure() -> dict[str, object]:
        raise RuntimeError("boom")

    result = asyncio.run(plugin._call("refresh", raise_failure))

    assert result == {"status": "failed", "message": "boom"}
    assert logger.exceptions == ["refresh failed"]


def test_call_maps_base_exception_from_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WorkerFatal(BaseException):
        pass

    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def raise_failure() -> dict[str, object]:
        raise WorkerFatal("fatal")

    result = asyncio.run(plugin._call("refresh", raise_failure))

    assert result == {"status": "failed", "message": "fatal"}
    assert logger.exceptions == ["refresh failed"]


def test_service_uses_decky_settings_dir_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_dir = tmp_path / "settings"
    decky, _logger = fake_decky_module(tmp_path, settings_dir=settings_dir)
    module = import_main(monkeypatch, decky)
    captured: dict[str, Path] = {}

    class CapturingService:
        def __init__(self, state_path: Path) -> None:
            captured["state_path"] = state_path

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)

    module.Plugin()._service()

    assert captured["state_path"] == settings_dir / "sdh_ludusavi.json"


def test_service_initializes_once_when_called_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_dir = tmp_path / "settings"
    decky, _logger = fake_decky_module(tmp_path, settings_dir=settings_dir)
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    barrier = threading.Barrier(3)
    count_lock = threading.Lock()
    services: list[object] = []
    errors: list[BaseException] = []
    service_count = 0

    class CapturingService:
        def __init__(self, state_path: Path) -> None:
            nonlocal service_count
            with count_lock:
                service_count += 1
            self.state_path = state_path
            time.sleep(0.05)

    def load_service() -> None:
        try:
            barrier.wait(timeout=1)
            services.append(plugin._service())
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)
    threads = [threading.Thread(target=load_service) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=1)
    for thread in threads:
        thread.join(timeout=1)

    assert errors == []
    assert service_count == 1
    assert len(services) == 2
    assert services[0] is services[1]


@pytest.mark.parametrize("settings_dir", [None, ""])
def test_service_fallback_uses_private_user_config_and_logs_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_dir: str | None,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=settings_dir)
    module = import_main(monkeypatch, decky)
    captured: dict[str, Path] = {}

    class CapturingService:
        def __init__(self, state_path: Path) -> None:
            captured["state_path"] = state_path

    monkeypatch.setattr(module, "SDHLudusaviService", CapturingService)

    module.Plugin()._service()

    expected = Path(decky.DECKY_USER_HOME) / ".config" / "sdh-ludusavi" / "sdh_ludusavi.json"
    assert captured["state_path"] == expected
    assert expected.parent.stat().st_mode & 0o777 == 0o700
    assert any("DECKY_SETTINGS_DIR" in warning for warning in logger.warnings)
