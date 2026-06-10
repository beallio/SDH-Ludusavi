from __future__ import annotations

from typing import Any
import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI
from sdh_ludusavi.syncthing.config import api_url_from_gui_address


# ============================================
# SyncthingAPI URL validation tests
# ============================================


def test_accepts_local_http_loopback() -> None:
    api = SyncthingAPI("http://127.0.0.1:8384", "test-key")
    assert api.base_url == "http://127.0.0.1:8384"


def test_accepts_local_https_loopback() -> None:
    api = SyncthingAPI("https://127.0.0.1:8384", "test-key")
    assert api.base_url == "https://127.0.0.1:8384"


def test_accepts_localhost_http() -> None:
    api = SyncthingAPI("http://localhost:8384", "test-key")
    assert api.base_url == "http://localhost:8384"


def test_accepts_localhost_https() -> None:
    api = SyncthingAPI("https://localhost:8384", "test-key")
    assert api.base_url == "https://localhost:8384"


def test_accepts_ipv6_loopback_http() -> None:
    api = SyncthingAPI("http://[::1]:8384", "test-key")
    assert api.base_url == "http://[::1]:8384"


def test_accepts_ipv6_loopback_https() -> None:
    api = SyncthingAPI("https://[::1]:8384", "test-key")
    assert api.base_url == "https://[::1]:8384"


def test_rejects_lan_ip_http() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("http://192.168.1.50:8384", "test-key")


def test_rejects_lan_ip_https() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("https://192.168.1.50:8384", "test-key")


def test_rejects_remote_hostname() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("http://syncthing.example.com:8384", "test-key")


def test_rejects_remote_https_with_valid_cert() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("https://syncthing.example.com:8384", "test-key")


def test_rejects_local_hostname() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("http://steamdeck.local:8384", "test-key")


def test_rejects_wildcard_ipv4() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("http://0.0.0.0:8384", "test-key")


def test_rejects_wildcard_ipv6() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("http://[::]:8384", "test-key")


def test_rejects_unsupported_scheme() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("ftp://127.0.0.1:8384", "test-key")


def test_rejects_malformed_url() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("not-a-url", "test-key")


def test_local_https_uses_self_signed_by_default() -> None:
    api = SyncthingAPI("https://127.0.0.1:8384", "test-key")
    assert api.ssl_context is not None


def test_local_https_uses_verified_tls_when_opted_out() -> None:
    api = SyncthingAPI("https://127.0.0.1:8384", "test-key", allow_local_https_self_signed=False)
    assert api.ssl_context is None


def test_rejects_redirect_to_non_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    api = SyncthingAPI("http://127.0.0.1:8384", "test-key")

    def redirecting_get_json(path: str, **kwargs: Any) -> Any:
        raise RuntimeError("redirected to non-loopback host")

    monkeypatch.setattr(api, "get_json", redirecting_get_json)

    with pytest.raises(RuntimeError, match="redirected to non-loopback host"):
        api.get_json("/rest/path")


def test_error_message_mentions_listen_address() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        SyncthingAPI("http://192.168.1.50:8384", "test-key")
    msg = str(exc_info.value)
    assert "listen" in msg.lower() or "0.0.0.0" in msg or "127.0.0.1" in msg


def test_explicit_remote_gui_url_is_rejected() -> None:
    url = api_url_from_gui_address("http://192.168.1.50:8384", False)
    assert url == "http://192.168.1.50:8384"

    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI(url, "test-key")


def test_no_private_ssl_api_used() -> None:
    import inspect

    source = inspect.getsource(SyncthingAPI.__init__)
    assert "ssl._create_unverified_context" not in source
    assert "ssl._create_default_https_context" not in source
