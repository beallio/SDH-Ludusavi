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
