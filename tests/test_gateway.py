from __future__ import annotations

import threading
from unittest.mock import patch

from sdh_ludusavi.gateway import LudusaviGateway


class MockAdapter:
    def get_versions(self):
        return {"ludusavi": "0.31.0"}

    def get_log_contents(self):
        return "some logs"

    def get_diagnostics(self):
        return {"version": "0.31.0"}


class DummyService:
    def __init__(self, adapter=None) -> None:
        self._adapter = adapter
        self._adapter_lock = threading.Lock()
        self._adapter_factory = lambda: adapter
        self._diagnostics_logged = False

    def log(self, level, message, operation=None, game_name=None):
        pass

    def _log_ludusavi_diagnostics(self, adapter):
        pass


def test_ludusavi_gateway_methods() -> None:
    factory_calls = 0

    def adapter_factory():
        nonlocal factory_calls
        factory_calls += 1
        return MockAdapter()

    with patch(
        "pyludusavi.discovery.find_ludusavi", return_value=["/usr/bin/ludusavi", "-f"]
    ) as mock_find:
        gateway = LudusaviGateway(adapter_factory=adapter_factory)

        # Initial calls cache the values
        gateway.get_adapter()
        gateway.get_versions()
        gateway.get_ludusavi_command()

        assert factory_calls == 1
        assert mock_find.call_count == 1

        # Subsequent calls return cached values
        gateway.get_adapter()
        gateway.get_versions()
        gateway.get_ludusavi_command()

        assert factory_calls == 1
        assert mock_find.call_count == 1

        # Invalidate caches
        gateway.invalidate()

        # Next calls should re-evaluate
        gateway.get_adapter()
        gateway.get_versions()
        gateway.get_ludusavi_command()

        assert factory_calls == 2
        assert mock_find.call_count == 2


def test_ludusavi_gateway_discovery() -> None:
    gateway = LudusaviGateway(adapter=MockAdapter())

    with patch("pyludusavi.discovery.find_ludusavi", return_value=["/usr/bin/ludusavi", "-f"]):
        cmd = gateway.get_ludusavi_command()
        assert cmd["commandPath"] == "/usr/bin/ludusavi"
        assert cmd["args"] == ["-f"]


def test_gateway_current_config_mtime_ns_read_failure() -> None:
    from unittest.mock import MagicMock
    from sdh_ludusavi.constants import CONFIG_MARKER_READ_FAILED
    from sdh_ludusavi.types import LudusaviAdapter

    mock_adapter = MagicMock(spec=LudusaviAdapter)
    mock_adapter.get_config_mtime_ns.side_effect = RuntimeError("Read error")

    log_calls = []

    def log_callback(level, message, operation=None, game_name=None):
        log_calls.append((level, message, operation, game_name))

    gateway = LudusaviGateway(adapter=mock_adapter, log_callback=log_callback)

    mtime = gateway.current_config_mtime_ns()
    assert mtime is CONFIG_MARKER_READ_FAILED
    assert len(log_calls) >= 1
    assert log_calls[-1][0] == "debug"
    assert "Unable to read Ludusavi config marker" in log_calls[-1][1]


def test_ludusavi_gateway_factory_returns_none() -> None:
    import pytest
    from unittest.mock import MagicMock

    log_mock = MagicMock()
    gateway = LudusaviGateway(
        adapter_factory=lambda: None,
        log_callback=log_mock,
    )

    with pytest.raises(RuntimeError) as exc_info:
        gateway.get_adapter()

    assert "Ludusavi adapter factory returned None" in str(exc_info.value)
    assert not gateway._diagnostics_logged
    log_mock.assert_not_called()


def test_gateway_invalidate_shuts_down_outgoing_adapter_and_clears_caches() -> None:
    class ShutdownRecordingAdapter(MockAdapter):
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def shutdown(self) -> bool:
            self.shutdown_calls += 1
            return True

    adapter = ShutdownRecordingAdapter()
    gateway = LudusaviGateway(adapter=adapter)
    gateway._versions = {"ludusavi": "0.31.0"}
    gateway._ludusavi_command = {"commandPath": "/usr/bin/ludusavi"}

    gateway.invalidate()

    assert adapter.shutdown_calls == 1
    assert gateway._adapter is None
    assert gateway._versions is None
    assert gateway._ludusavi_command is None


def test_gateway_invalidate_retires_failed_adapter_for_later_shutdown_retry() -> None:
    class RetryShutdownAdapter(MockAdapter):
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def shutdown(self) -> bool:
            self.shutdown_calls += 1
            if self.shutdown_calls == 1:
                raise RuntimeError("shutdown failed")
            return True

    log_entries: list[tuple[object, ...]] = []
    adapter = RetryShutdownAdapter()
    gateway = LudusaviGateway(adapter=adapter, log_callback=lambda *args: log_entries.append(args))

    gateway.invalidate()

    assert adapter.shutdown_calls == 1
    assert len(log_entries) == 1
    assert log_entries[0][0] == "warning"
    assert log_entries[0][2] == "init"
    assert gateway.shutdown()
    assert adapter.shutdown_calls == 2


def test_gateway_invalidate_reaps_outgoing_adapter_without_holding_adapter_lock() -> None:
    class BlockingShutdownAdapter(MockAdapter):
        def __init__(self) -> None:
            self.shutdown_entered = threading.Event()
            self.release_shutdown = threading.Event()

        def shutdown(self) -> bool:
            self.shutdown_entered.set()
            assert self.release_shutdown.wait(timeout=1)
            return True

    outgoing = BlockingShutdownAdapter()
    replacement = MockAdapter()
    gateway = LudusaviGateway(adapter=outgoing, adapter_factory=lambda: replacement)
    invalidate_errors: list[BaseException] = []
    adapter_results: list[MockAdapter] = []
    adapter_errors: list[BaseException] = []
    adapter_returned = threading.Event()

    def invalidate() -> None:
        try:
            gateway.invalidate()
        except BaseException as exc:  # pragma: no cover - asserted after bounded joins.
            invalidate_errors.append(exc)

    def get_adapter() -> None:
        try:
            adapter_results.append(gateway.get_adapter())
        except BaseException as exc:  # pragma: no cover - asserted after bounded joins.
            adapter_errors.append(exc)
        finally:
            adapter_returned.set()

    invalidate_worker = threading.Thread(target=invalidate, daemon=True)
    adapter_worker = threading.Thread(target=get_adapter, daemon=True)
    adapter_worker_started = False
    invalidate_worker.start()
    try:
        assert outgoing.shutdown_entered.wait(timeout=1)
        adapter_worker.start()
        adapter_worker_started = True
        assert adapter_returned.wait(timeout=1)
        assert adapter_results == [replacement]
        assert not adapter_errors
    finally:
        outgoing.release_shutdown.set()
        invalidate_worker.join(timeout=1)
        if adapter_worker_started:
            adapter_worker.join(timeout=1)

    assert not invalidate_worker.is_alive()
    assert not adapter_worker_started or not adapter_worker.is_alive()
    assert not invalidate_errors
