# SDH-Ludusavi Syncthing API Local-Only TLS Fix — Agent Implementation Plan

## Purpose

Implement a narrowly scoped security fix for the Syncthing API client on `main`.

The plugin is intended to communicate with a Syncthing instance running on the same Steam Deck. Therefore, the correct security boundary is not a general-purpose remote TLS policy. The correct boundary is:

> SDH-Ludusavi must never send the Syncthing API key to a non-loopback host.

This plan keeps the Steam Deck happy path simple while removing the unsafe default behavior where HTTPS certificate verification can be skipped for arbitrary remote Syncthing API URLs.

---

## Preconditions and Resolved Decisions

- Target branch: `main`. Create a `fix/` feature branch from `main` for the work.
- The only production call site is `py_modules/sdh_ludusavi/syncthing/watcher.py:291`, which constructs `SyncthingAPI(api_url, api_key)` with two positional arguments. Removing the `tls_skip_verify` keyword is therefore safe; verify this call site is still the only one before changing the signature (`grep -rn "SyncthingAPI(" py_modules/`).
- Existing tests live in `tests/test_syncthing.py` (single file, not per-module). Add new tests there following the existing convention.
- Known breaking change (accepted): users who configured Syncthing's GUI to listen only on a LAN address (e.g. `192.168.1.50:8384`) will be rejected even though Syncthing runs on the same machine. This is intentional. The error message must tell those users how to recover (see `_LOCAL_ONLY_ERROR` below).
- Redirect protection is in scope: `urllib.request` follows HTTP redirects by default and re-sends headers, including `X-API-Key`. Without protection, a service on loopback could redirect the client to a remote host and leak the key, defeating the entire invariant. Step 5 addresses this.
- TDD ordering: per project protocol, write the failing tests from the Test Plan section first, confirm they fail via `./run.sh uv run pytest`, then implement Steps 1–6.

---

## Target Behavior

### Allow

The Syncthing API client should allow only loopback API URLs:

```text
http://127.0.0.1:8384
http://localhost:8384
http://[::1]:8384
https://127.0.0.1:8384
https://localhost:8384
https://[::1]:8384
```

### Reject

The client should reject non-loopback API URLs before making any HTTP request:

```text
http://192.168.1.50:8384
https://192.168.1.50:8384
http://10.0.0.5:8384
https://syncthing.example.com:8384
http://steamdeck.local:8384
https://nas.local:8384
http://0.0.0.0:8384
http://[::]:8384
```

### TLS Handling

For this plugin, TLS should be handled as follows:

| URL Type | Behavior |
|---|---|
| Local HTTP loopback | Allowed |
| Local HTTPS loopback | Allowed |
| Local HTTPS self-signed | Allowed by default |
| Remote HTTP | Rejected |
| Remote HTTPS with valid cert | Rejected |
| Remote HTTPS with skipped verification | Rejected |

Rationale: remote Syncthing GUI API control is not in scope for this Steam Deck plugin. Supporting remote APIs would require a broader trust and configuration model. Do not add that complexity here.

---

## Standard Library Import Check

The implementation should use only Python standard library modules.

Required imports:

```python
import ipaddress
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
```

All of these are Python standard library modules. `ipaddress` is also standard library and has been available since Python 3.3. No new packaged dependency is needed.

The current branch already uses `json`, `ssl`, `urllib.error`, `urllib.parse`, `urllib.request`, and `typing.Any` in the Syncthing API client. The only likely new import is `ipaddress`.

---

## Files to Inspect

Start by inspecting these files:

```text
py_modules/sdh_ludusavi/syncthing/api.py
py_modules/sdh_ludusavi/syncthing/config.py
py_modules/sdh_ludusavi/syncthing/_types.py
```

Test location (verified):

```text
tests/test_syncthing.py
```

Existing coverage for `api_url_from_gui_address` already lives there; extend it rather than creating new files.

---

## Current Problem

The current `SyncthingAPI` constructor defaults to skipping TLS verification for HTTPS API URLs. In simplified form, it behaves like this:

```python
class SyncthingAPI:
    def __init__(self, base_url: str, api_key: str, tls_skip_verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tls_skip_verify = tls_skip_verify
        self.ssl_context = ssl._create_unverified_context() if tls_skip_verify else None
```

That is too broad. It permits an HTTPS API URL on a LAN or remote host while disabling certificate verification. Since the Syncthing API key is a bearer-style credential, this creates unnecessary exposure.

For SDH-Ludusavi, the simpler and safer fix is to enforce loopback-only API URLs.

---

## Implementation Steps

### Step 1: Add loopback host detection helper

In `py_modules/sdh_ludusavi/syncthing/api.py`, add:

```python
import ipaddress
```

Then add a private helper near the top of the file:

```python
_LOCAL_ONLY_ERROR = (
    "Only local Syncthing GUI API URLs are supported "
    "(e.g. http://127.0.0.1:8384). If Syncthing's GUI listens on a "
    "LAN address, change its GUI listen address to 0.0.0.0:8384 or "
    "127.0.0.1:8384 in Syncthing settings, or set "
    "SYNCTHING_API_URL=http://127.0.0.1:8384."
)


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False

    normalized = host.strip().strip("[]").lower()

    if normalized == "localhost":
        return True

    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
```

Notes for the agent:

- Treat `localhost` as loopback.
- Treat literal loopback IPv4 and IPv6 addresses as loopback.
- Do not treat arbitrary hostnames as loopback.
- Do not attempt DNS resolution.
- Do not treat `.local` names as safe.
- Do not treat `0.0.0.0` or `[::]` as safe client targets.
- The error message is intentionally actionable: the main rejection cohort is users
  whose Syncthing GUI is bound only to a LAN address on the same machine, and the
  message must give them a recovery path. The message is a static string and safe to
  surface through RPC.

---

### Step 2: Add URL validation helper

Add:

```python
def _validate_local_api_url(base_url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(base_url)

    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError(
            f"Unsupported Syncthing API URL scheme: {parsed.scheme!r}. "
            "Expected http or https."
        )

    if not _is_loopback_host(parsed.hostname):
        raise RuntimeError(_LOCAL_ONLY_ERROR)

    return parsed
```

Notes:

- Use `urllib.parse.urlparse`.
- Validate the parsed scheme explicitly.
- Validate `parsed.hostname`, not raw string fragments.
- Return the parsed result so the constructor can branch on `parsed.scheme`.
- Do not silently rewrite remote URLs in this function. Reject them.

---

### Step 3: Replace broad `tls_skip_verify` constructor behavior

Update `SyncthingAPI.__init__`.

Recommended target shape:

```python
class SyncthingAPI:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        allow_local_https_self_signed: bool = True,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        parsed = _validate_local_api_url(normalized_url)

        self.base_url = normalized_url
        self.api_key = api_key

        if parsed.scheme == "https":
            ssl_context = ssl.create_default_context()
            if allow_local_https_self_signed:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            self.ssl_context: ssl.SSLContext | None = ssl_context
        else:
            self.ssl_context = None

        self._opener = _build_loopback_only_opener(self.ssl_context)
```

Important:

- Remove the default `tls_skip_verify=True` behavior.
- Do not use `ssl._create_unverified_context()`. It is a private CPython API; the
  public equivalent above (`create_default_context` with `check_hostname = False` and
  `verify_mode = ssl.CERT_NONE`) has identical behavior.
- `_build_loopback_only_opener` is defined in Step 5 (redirect protection).
- Do not keep a generic `tls_skip_verify` parameter unless needed for backwards compatibility.
- If backwards compatibility is needed, accept it only as a deprecated alias for `allow_local_https_self_signed`, and only after local URL validation.
- Do not allow skipped TLS verification for non-loopback URLs under any constructor option.

Preferred final API:

```python
SyncthingAPI(base_url, api_key)
SyncthingAPI(base_url, api_key, allow_local_https_self_signed=False)
```

Avoid:

```python
SyncthingAPI(base_url, api_key, tls_skip_verify=True)
```

The latter name is misleading because it sounds applicable to remote HTTPS. The actual supported behavior is local self-signed HTTPS only.

---

### Step 4: Add defensive validation before sending requests

In `SyncthingAPI.get_json`, make two minimal changes. Do not rewrite the rest of the
method body; recent commits adjusted Syncthing error handling, and a wholesale
replacement risks reverting them.

1. Insert as the first statement of `get_json`:

```python
_validate_local_api_url(self.base_url)
```

2. Replace the `urllib.request.urlopen(request, timeout=timeout, context=self.ssl_context)`
   call with the loopback-only opener from Step 5:

```python
with self._opener.open(request, timeout=timeout) as response:
```

(The SSL context is attached to the opener via `HTTPSHandler` in Step 5, so the
`context=` argument moves there.)

Notes:

- This validation is intentionally redundant with constructor validation.
- It protects against future mutation of `self.base_url`.
- Do not log or expose the API key in error messages.
- It is acceptable to include the API URL in errors.
- Leave the existing exception handling (`HTTPError`, `URLError`, JSON decode) as-is.

---

### Step 5: Refuse redirects to non-loopback hosts

`urllib.request` follows HTTP redirects by default, and Python's redirect handler
copies request headers — including `X-API-Key` — onto the new request. Without this
step, anything answering on loopback port 8384 could respond with
`Location: http://attacker.example.com/` and the client would re-send the API key
off-box, silently defeating the loopback-only invariant.

Add to `api.py`:

```python
class _LoopbackOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_local_api_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_loopback_only_opener(
    ssl_context: ssl.SSLContext | None,
) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [_LoopbackOnlyRedirectHandler()]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    return urllib.request.build_opener(*handlers)
```

Notes:

- `redirect_request` receives `newurl` already resolved to an absolute URL, so
  `_validate_local_api_url` applies directly.
- Loopback-to-loopback redirects remain allowed; redirects to any non-loopback host
  raise `RuntimeError` before the redirected request is built, so the API key is never
  re-sent off-box.
- The Syncthing REST API does not use redirects in normal operation, so this changes
  nothing on the happy path.
- The constructor stores the opener as `self._opener` (Step 3) and `get_json` uses it
  (Step 4).

---

### Step 6: Avoid unnecessary `config.py` changes

Inspect `py_modules/sdh_ludusavi/syncthing/config.py`.

The expected behavior is:

- Syncthing GUI address `0.0.0.0:8384` should be converted to a loopback client URL.
- Syncthing GUI address `[::]:8384` should be converted to an IPv6 loopback client URL.
- `tls=true` should produce an `https://` URL.
- `tls=false` should produce an `http://` URL.

Do not move the security boundary into `config.py`.

`config.py` may normalize discovered Syncthing GUI listen addresses, but `api.py` should remain the final enforcement point.

If `config.py` currently preserves an explicitly configured remote full URL such as:

```text
http://192.168.1.50:8384
```

that is acceptable. The API client should reject it.

---

## Test Plan

### Unit tests for loopback detection

Add or update API tests:

```python
import pytest

from sdh_ludusavi.syncthing.api import _is_loopback_host


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "LOCALHOST",
        "127.0.0.1",
        "127.1.2.3",
        "::1",
        "[::1]",
    ],
)
def test_is_loopback_host_accepts_loopback(host):
    assert _is_loopback_host(host)


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "0.0.0.0",
        "::",
        "[::]",
        "192.168.1.50",
        "10.0.0.5",
        "steamdeck.local",
        "nas.local",
        "syncthing.example.com",
    ],
)
def test_is_loopback_host_rejects_non_loopback(host):
    assert not _is_loopback_host(host)
```

If the project avoids testing private helpers, skip these direct helper tests and cover the same cases through `SyncthingAPI`.

---

### Unit tests for allowed API URLs

```python
import ssl

import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8384",
        "http://localhost:8384",
        "http://[::1]:8384",
    ],
)
def test_syncthing_api_allows_local_http(url):
    api = SyncthingAPI(url, "test-api-key")

    assert api.base_url == url.rstrip("/")
    assert api.ssl_context is None


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8384",
        "https://localhost:8384",
        "https://[::1]:8384",
    ],
)
def test_syncthing_api_allows_local_https_self_signed_by_default(url):
    api = SyncthingAPI(url, "test-api-key")

    assert api.base_url == url.rstrip("/")
    assert api.ssl_context is not None
    assert api.ssl_context.verify_mode == ssl.CERT_NONE


def test_syncthing_api_can_use_verified_tls_for_local_https():
    api = SyncthingAPI(
        "https://localhost:8384",
        "test-api-key",
        allow_local_https_self_signed=False,
    )

    assert api.ssl_context is not None
    assert api.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert api.ssl_context.check_hostname is True
```

---

### Unit tests for rejected API URLs

```python
import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.50:8384",
        "https://192.168.1.50:8384",
        "http://10.0.0.5:8384",
        "https://10.0.0.5:8384",
        "http://steamdeck.local:8384",
        "https://steamdeck.local:8384",
        "http://nas.local:8384",
        "https://syncthing.example.com:8384",
        "http://0.0.0.0:8384",
        "http://[::]:8384",
    ],
)
def test_syncthing_api_rejects_non_loopback_urls(url):
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI(url, "test-api-key")
```

---

### Unit tests for unsupported or malformed API URLs

```python
import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI


@pytest.mark.parametrize(
    "url",
    [
        "",
        "127.0.0.1:8384",
        "localhost:8384",
        "ftp://127.0.0.1:8384",
        "file:///tmp/syncthing.sock",
    ],
)
def test_syncthing_api_rejects_unsupported_or_malformed_urls(url):
    with pytest.raises(RuntimeError):
        SyncthingAPI(url, "test-api-key")
```

---

### Redirect protection tests

Stand up a real loopback HTTP server that issues a redirect to a non-loopback host and
assert the client refuses to follow it. No request must reach the redirect target, so
use a TEST-NET address (`192.0.2.x`) that is guaranteed unroutable.

```python
import http.server
import threading

import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI


class _RedirectingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://192.0.2.10:8384/rest/system/status")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_get_json_refuses_redirect_to_non_loopback():
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        api = SyncthingAPI(f"http://127.0.0.1:{port}", "test-api-key")

        with pytest.raises(RuntimeError, match="Only local Syncthing"):
            api.get_json("/rest/system/status")
    finally:
        server.shutdown()
        thread.join()
```

A loopback-to-loopback redirect (e.g. `Location: http://127.0.0.1:<port>/other`) should
still be followed; add a companion test for that if it is cheap with the same stub
server, but the rejection test above is the mandatory one.

---

### Config integration tests

If tests already exist for `api_url_from_gui_address`, extend them.

Expected behavior:

```python
import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI
from sdh_ludusavi.syncthing.config import api_url_from_gui_address


@pytest.mark.parametrize(
    ("address", "tls", "expected"),
    [
        ("127.0.0.1:8384", False, "http://127.0.0.1:8384"),
        ("localhost:8384", False, "http://localhost:8384"),
        (":8384", False, "http://127.0.0.1:8384"),
        ("0.0.0.0:8384", False, "http://127.0.0.1:8384"),
        ("0.0.0.0", False, "http://127.0.0.1:8384"),
        ("[::]:8384", False, "http://[::1]:8384"),
        ("[::]", False, "http://[::1]:8384"),
        ("127.0.0.1:8384", True, "https://127.0.0.1:8384"),
    ],
)
def test_discovered_gui_addresses_resolve_to_supported_local_api_urls(
    address,
    tls,
    expected,
):
    url = api_url_from_gui_address(address, tls)

    assert url == expected
    SyncthingAPI(url, "test-api-key")
```

Explicit remote full URL behavior:

```python
import pytest

from sdh_ludusavi.syncthing.api import SyncthingAPI
from sdh_ludusavi.syncthing.config import api_url_from_gui_address


def test_explicit_remote_gui_url_is_rejected_by_api_client():
    url = api_url_from_gui_address("http://192.168.1.50:8384", False)

    assert url == "http://192.168.1.50:8384"

    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI(url, "test-api-key")
```

If `api_url_from_gui_address` currently returns a different shape for full URLs, adjust the assertion to match existing behavior, but keep the final invariant: the API client must reject non-loopback URLs.

---

## Manual Verification

After implementing the code and tests, manually verify these cases.

### Local default

With no custom Syncthing API URL:

```text
DEFAULT_API_URL = http://127.0.0.1:8384
```

Expected:

- Plugin can query local Syncthing.
- No TLS context is used.
- Existing happy path remains unchanged.

### Local Syncthing GUI TLS enabled

If Syncthing GUI TLS is enabled and config discovery returns:

```text
https://127.0.0.1:8384
```

Expected:

- Plugin can query local Syncthing.
- Self-signed cert is accepted only because the host is loopback.

### Remote override

If a user sets or configures:

```text
SYNCTHING_API_URL=http://192.168.1.50:8384
```

Expected:

- Plugin refuses to create/use the API client.
- Error message says only local Syncthing API URLs are supported.
- No request is sent.
- API key is not transmitted.

### Remote HTTPS override

If a user sets or configures:

```text
SYNCTHING_API_URL=https://192.168.1.50:8384
```

Expected:

- Plugin refuses to create/use the API client.
- It must not bypass TLS verification.
- It must not send the API key.

---

## Acceptance Criteria

The implementation is complete when all of the following are true:

- [ ] The API client accepts loopback HTTP URLs.
- [ ] The API client accepts loopback HTTPS URLs.
- [ ] The API client allows local self-signed HTTPS by default.
- [ ] The API client optionally supports verified TLS for local HTTPS via `allow_local_https_self_signed=False`.
- [ ] The API client rejects all non-loopback URLs.
- [ ] The API client rejects wildcard client targets such as `0.0.0.0` and `[::]`.
- [ ] The API client rejects unsupported schemes.
- [ ] The API client does not send the Syncthing API key to a non-loopback host.
- [ ] The API client refuses HTTP redirects to non-loopback hosts before re-sending headers.
- [ ] The rejection error message tells LAN-bound-GUI users how to recover.
- [ ] The code does not use `ssl._create_unverified_context()` or other private APIs.
- [ ] The code uses only Python standard library imports.
- [ ] No frontend changes are required.
- [ ] Existing Syncthing config discovery behavior still works for Steam Deck local Syncthing.
- [ ] Tests cover allowed local HTTP, allowed local HTTPS, rejected remote URLs, rejected malformed URLs, rejected non-loopback redirects, and config-derived loopback URLs.
- [ ] Tests were written first and observed failing before implementation (project TDD protocol).

---

## Non-Goals

Do not implement these in this fix:

- Remote Syncthing API support.
- LAN Syncthing API support.
- Certificate pinning.
- Custom CA bundle discovery.
- User-facing TLS configuration UI.
- DNS resolution for hostname safety checks.
- `.local` hostname allowlisting.
- Environment-variable escape hatches for insecure remote APIs.

These are intentionally out of scope. If the project later wants remote Syncthing API support, design it separately with an explicit trust model.

---

## Suggested Commit Message

```text
fix(syncthing): restrict API client to local loopback URLs

The Syncthing integration is intended to talk to a local Syncthing
instance running on the Steam Deck. Previously the API client defaulted
to skipping TLS verification for HTTPS URLs, which could allow the
Syncthing API key to be sent to a non-loopback host without certificate
validation.

Add explicit loopback-only URL validation in the API client. Allow local
HTTP and local self-signed HTTPS, but reject remote, LAN, wildcard, and
unsupported API URLs before any request is sent. Refuse HTTP redirects
to non-loopback hosts so a loopback service cannot bounce the API key
off-box.

BREAKING CHANGE: setups where Syncthing's GUI listens only on a LAN
address are rejected; the error message explains how to switch to a
loopback or 0.0.0.0 listen address.
```

---

## Agent Notes

Prefer a small, targeted patch.

Do not generalize this into a full networking or TLS abstraction. The core security invariant is simple:

> The Syncthing API client must only communicate with loopback addresses.

Keep the enforcement in `api.py`, test it directly, and avoid changing UI behavior unless existing error propagation is broken.
