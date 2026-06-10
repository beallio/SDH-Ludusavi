from __future__ import annotations

import ipaddress
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_LOCAL_ONLY_ERROR = (
    "Only local Syncthing API URLs are supported. "
    "Got '{scheme}://{host}'. "
    "Configure your Syncthing GUI to listen on 127.0.0.1:8384 "
    "or 0.0.0.0:8384 instead of a LAN-specific address."
)


def _is_loopback_host(host: str | None) -> bool:
    """Return True if *host* is a loopback address or localhost name."""
    if host is None:
        return False

    # localhost is always loopback
    if host.lower() == "localhost":
        return True

    # Try as an IP address
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_loopback
    except ValueError:
        # Not an IP address and not localhost -> not loopback
        return False


class _LoopbackOnlyHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse HTTP redirects that target a non-loopback host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            parsed = urllib.parse.urlparse(new_req.full_url)
            if not _is_loopback_host(parsed.hostname):
                raise RuntimeError(
                    f"Syncthing API {code} response redirected to non-loopback "
                    f"host '{parsed.hostname}'. Refusing to follow redirect."
                )
        return new_req


class SyncthingAPI:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        allow_local_https_self_signed: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

        # Validate that URL is loopback-only
        parsed = urllib.parse.urlparse(self.base_url)
        host = parsed.hostname

        if parsed.scheme not in ("http", "https"):
            raise RuntimeError(
                _LOCAL_ONLY_ERROR.format(scheme=parsed.scheme, host=host or self.base_url)
            )

        if not _is_loopback_host(host):
            raise RuntimeError(_LOCAL_ONLY_ERROR.format(scheme=parsed.scheme, host=host or ""))

        # Set up SSL context for HTTPS
        if parsed.scheme == "https" and allow_local_https_self_signed:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self.ssl_context = ctx
        else:
            self.ssl_context = None

        # Build opener with redirect protection and custom SSL handling
        handlers: list[urllib.request.BaseHandler] = [_LoopbackOnlyHTTPRedirectHandler()]
        if parsed.scheme == "https":
            handlers.append(urllib.request.HTTPSHandler(context=self.ssl_context))
        self._opener = urllib.request.build_opener(*handlers)

    def get_json(
        self, path: str, params: dict[str, Any] | None = None, timeout: float = 30.0
    ) -> Any:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)

        url = f"{self.base_url}{path}{query}"
        request = urllib.request.Request(
            url,
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with self._opener.open(request, timeout=timeout) as response:  # type: ignore[no-untyped-call]
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Syncthing API HTTP {exc.code} for {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Syncthing API at {url}: {exc}") from exc

        if not raw:
            return None

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            text = raw[:500].decode("utf-8", errors="replace")
            raise RuntimeError(f"Invalid JSON from {url}: {text!r}") from exc
