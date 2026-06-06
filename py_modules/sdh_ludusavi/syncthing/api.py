from __future__ import annotations

import json
import ssl
import urllib.request
import urllib.error
import urllib.parse
from typing import Any


class SyncthingAPI:
    def __init__(self, base_url: str, api_key: str, tls_skip_verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tls_skip_verify = tls_skip_verify
        self.ssl_context = ssl._create_unverified_context() if tls_skip_verify else None

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
            with urllib.request.urlopen(
                request, timeout=timeout, context=self.ssl_context
            ) as response:
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
