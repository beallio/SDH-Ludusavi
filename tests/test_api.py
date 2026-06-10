from __future__ import annotations

import http.server
import threading
from typing import Any
from typing import Generator
import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI
from sdh_ludusavi.syncthing.config import api_url_from_gui_address


# ============================================
# Allowed loopback URLs
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


def test_accepts_non_trivial_loopback_ipv4() -> None:
    """127.1.2.3 is a loopback address and should be accepted."""
    api = SyncthingAPI("http://127.1.2.3:8384", "test-key")
    assert api.base_url == "http://127.1.2.3:8384"


# ============================================
# Rejected non-loopback URLs
# ============================================


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


def test_rejects_empty_string_url() -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("", "test-key")


def test_rejects_file_scheme() -> None:
    """file:// URI does not have a hostname that maps to loopback."""
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("file:///tmp/syncthing.sock", "test-key")


def test_rejects_scheme_less_ipv4() -> None:
    """127.0.0.1:8384 without scheme is rejected."""
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("127.0.0.1:8384", "test-key")


def test_rejects_scheme_less_localhost() -> None:
    """localhost:8384 without scheme is rejected."""
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI("localhost:8384", "test-key")


# ============================================
# Defensive re-validation in get_json
# ============================================


def test_get_json_rejects_mutated_base_url() -> None:
    """Mutating base_url to non-loopback after construction is caught."""
    api = SyncthingAPI("http://127.0.0.1:8384", "test-key")
    api.base_url = "http://192.168.1.50:8384"
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        api.get_json("/rest/system/version")


def test_get_json_accepts_valid_mutated_base_url() -> None:
    """Mutating base_url to another loopback address is fine."""
    api = SyncthingAPI("http://127.0.0.1:8384", "test-key")
    api.base_url = "http://127.1.2.3:8384"
    # Will fail with connection error (no server), not a validation error
    with pytest.raises(RuntimeError, match="Cannot reach Syncthing API"):
        api.get_json("/rest/system/version")


# ============================================
# SSL context behavior
# ============================================


def test_local_https_uses_self_signed_by_default() -> None:
    api = SyncthingAPI("https://127.0.0.1:8384", "test-key")
    assert api.ssl_context is not None


def test_local_https_uses_verified_tls_when_opted_out() -> None:
    api = SyncthingAPI("https://127.0.0.1:8384", "test-key", allow_local_https_self_signed=False)
    assert api.ssl_context is None


# ============================================
# Redirect handler — real http.server stubs
# ============================================


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    """Serves a single 301 redirect to the target stored in server_state."""

    def do_GET(self) -> None:  # type: ignore[override]
        target = str(self.server.redirect_target)  # type: ignore[attr-defined]
        self.send_response(301)
        self.send_header("Location", target)
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # suppress HTTP server logs during tests


@pytest.fixture
def redirect_server() -> Generator[int, None, None]:
    """Yield an ephemeral port where a GET returns 301 to 192.0.2.10."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectHandler)
    server.redirect_target = "http://192.0.2.10:8384/evil"  # type: ignore[attr-defined]
    port = server.server_address[1]
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    yield port
    server.server_close()


@pytest.fixture
def loopback_redirect_server() -> Generator[int, None, None]:
    """Yield an ephemeral port where a GET returns 301 to another loopback."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectHandler)
    server.redirect_target = "http://127.0.0.1:18384/safe"  # type: ignore[attr-defined]
    port = server.server_address[1]
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    yield port
    server.server_close()


def test_rejects_redirect_to_non_loopback(redirect_server: int) -> None:
    """A redirect to a non-loopback host is rejected."""
    api = SyncthingAPI(f"http://127.0.0.1:{redirect_server}", "test-key")
    with pytest.raises(RuntimeError, match="redirected to non-loopback host"):
        api.get_json("/rest/system/version")


def test_follows_redirect_to_loopback(loopback_redirect_server: int) -> None:
    """A redirect to another loopback address is followed."""
    api = SyncthingAPI(f"http://127.0.0.1:{loopback_redirect_server}", "test-key")
    with pytest.raises(RuntimeError, match="Cannot reach Syncthing API"):
        api.get_json("/rest/system/version")


# ============================================
# Error message
# ============================================


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


# ============================================
# No private SSL APIs
# ============================================


def test_no_private_ssl_api_used() -> None:
    import inspect

    source = inspect.getsource(SyncthingAPI.__init__)
    assert "ssl._create_unverified_context" not in source
    assert "ssl._create_default_https_context" not in source


def test_validate_local_api_url_is_module_level() -> None:
    """_validate_local_api_url is accessible as a module-level function."""
    from sdh_ludusavi.syncthing.api import _validate_local_api_url

    _validate_local_api_url("http://127.0.0.1:8384")
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        _validate_local_api_url("http://192.168.1.50:8384")
