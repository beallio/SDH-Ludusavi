# Syncthing Loopback Fix — Review Remediation Plan

## Problem Definition

Commit `8b11f12` (`fix(syncthing): restrict API client to local loopback URLs`) on branch
`fix/syncthing_tls_verify` implements the loopback-only security fix from
`docs/plans/2026-06-09_syncthing_local_only_tls_implementation_plan.md`. Code review
found the implementation functionally sound — the redirect protection was verified
working against a live loopback redirect server — but identified two must-fix defects
and four minor deviations from the plan. This remediation plan addresses all of them.

### Must-fix findings

1. **Vacuous redirect test.** `tests/test_api.py::test_rejects_redirect_to_non_loopback`
   monkeypatches `api.get_json` to raise `RuntimeError`, then asserts that it raises.
   It exercises the monkeypatch, not `_LoopbackOnlyHTTPRedirectHandler`. Deleting the
   handler entirely would not fail this test. The original plan designated a real
   `http.server` stub test as mandatory.

2. **Missing defensive re-validation in `get_json`.** Validation runs once in
   `SyncthingAPI.__init__` and never again. The original plan (Step 4) required
   re-validating `self.base_url` as the first statement of `get_json` to protect
   against post-construction mutation. The plan's `_validate_local_api_url` helper was
   never factored out — validation is inlined in `__init__` — so there is currently
   nothing for `get_json` to call.

### Minor deviations

3. **`allow_local_https_self_signed` is not keyword-only.** The plan specified a `*,`
   separator. Positional semantics happen to coincide with the removed
   `tls_skip_verify`, so nothing breaks silently today, but the keyword-only contract
   should be enforced before any third-party call sites appear.

4. **Implicit verified-TLS opt-out.** With `allow_local_https_self_signed=False`, the
   constructor sets `self.ssl_context = None` and relies on
   `urllib.request.HTTPSHandler(context=None)` falling back to `http.client`'s default
   verified context. Functionally correct but implicit; the plan wanted an explicit
   `ssl.create_default_context()` assigned to `self.ssl_context` so the policy is
   inspectable and testable.

5. **Unrelated churn in `tests/test_syncthing.py`.** The commit stripped ten
   explanatory comment lines from unrelated tests (`test_resolve_folder_by_path`,
   `test_compute_activity_status`). These must be restored; they were user-owned
   content unrelated to the security fix.

6. **Missing plan test cases.** Not carried over from the original plan's test matrix:
   empty-string URL, scheme-less `127.0.0.1:8384` and `localhost:8384`, non-trivial
   loopback `127.1.2.3`, `file://` scheme, and the companion test that
   loopback-to-loopback redirects are still followed.

### Out of scope

- Do not rewrite or amend `8b11f12`. Apply remediation as new atomic commits on
  `fix/syncthing_tls_verify`. (The bundling of the plan doc into `8b11f12` and the
  single-commit test+impl delivery are accepted as done; the lesson is recorded here,
  not retroactively fixed with history surgery.)
- No behavior changes beyond the four code-level findings above. No new features, no
  `config.py` changes, no frontend changes.

---

## Architecture Overview

All changes are confined to:

```text
py_modules/sdh_ludusavi/syncthing/api.py   (helper extraction, ctor tweaks, get_json guard)
tests/test_api.py                          (replace vacuous test, add missing cases)
tests/test_syncthing.py                    (restore stripped comments only)
```

The security boundary stays exactly where the original plan put it: `api.py` is the
single enforcement point. The remediation extracts the inlined constructor validation
into a module-level `_validate_local_api_url` helper so the same check runs in three
places that already exist conceptually:

```text
__init__            -> _validate_local_api_url(base_url)        (existing, refactored)
get_json            -> _validate_local_api_url(self.base_url)   (new, defensive)
redirect handler    -> _is_loopback_host(new host)              (existing, unchanged)
```

The redirect handler keeps its own error message ("Refusing to follow redirect") — it
is more specific than `_LOCAL_ONLY_ERROR` and already verified working.

---

## Core Data Structures

No new data structures. The only attribute-level change: after this remediation,
`self.ssl_context` is an `ssl.SSLContext` for **every** HTTPS client (self-signed mode
or verified mode) and `None` only for HTTP. Today it is `None` for both HTTP and the
verified-HTTPS opt-out, which makes the TLS policy uninspectable.

| Scheme | `allow_local_https_self_signed` | `self.ssl_context` after remediation |
|---|---|---|
| http | (any) | `None` |
| https | `True` (default) | context with `check_hostname=False`, `verify_mode=CERT_NONE` |
| https | `False` | `ssl.create_default_context()` (`check_hostname=True`, `verify_mode=CERT_REQUIRED`) |

---

## Public Interfaces

Final constructor signature (keyword-only flag is the only signature change):

```python
class SyncthingAPI:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        allow_local_https_self_signed: bool = True,
    ) -> None: ...
```

`SyncthingAPI(url, key, False)` becomes a `TypeError`. The only production call site,
`py_modules/sdh_ludusavi/syncthing/watcher.py:291`, passes two positional arguments and
is unaffected. Re-verify before committing:

```bash
grep -rn "SyncthingAPI(" py_modules/
```

New module-level helper (private, same module):

```python
def _validate_local_api_url(base_url: str) -> urllib.parse.ParseResult:
    """Raise RuntimeError unless base_url is an http(s) loopback URL."""
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname

    if parsed.scheme not in ("http", "https"):
        raise RuntimeError(
            _LOCAL_ONLY_ERROR.format(scheme=parsed.scheme, host=host or base_url)
        )

    if not _is_loopback_host(host):
        raise RuntimeError(_LOCAL_ONLY_ERROR.format(scheme=parsed.scheme, host=host or ""))

    return parsed
```

`get_json` gains exactly one statement at the top:

```python
_validate_local_api_url(self.base_url)
```

Do not otherwise modify `get_json`'s body or exception handling.

---

## Dependency Requirements

None. All changes use modules already imported in `api.py` (`ipaddress`, `ssl`,
`urllib.*`) plus `http.server` and `threading` in tests — all Python standard library.
No `pyproject.toml` or `uv.lock` changes.

---

## Implementation Steps

Follow strict TDD per project protocol: for each behavior-changing step, write the
test, run `./run.sh uv run pytest tests/test_api.py` and observe the failure, then
implement. Steps R1 and R5 are test-only/restoration changes where the red phase does
not apply.

### Step R1: Replace the vacuous redirect test (test-only; no red phase)

Delete `test_rejects_redirect_to_non_loopback` (the monkeypatch version) from
`tests/test_api.py` and replace it with a real loopback stub server. Use a TEST-NET
address (`192.0.2.x`, RFC 5737, guaranteed unroutable) as the redirect target so a
regression can never leak a request off-box during the test run.

```python
import http.server
import threading


class _RedirectingHandler(http.server.BaseHTTPRequestHandler):
    redirect_target = "http://192.0.2.10:8384/rest/system/status"

    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", self.redirect_target)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_rejects_redirect_to_non_loopback() -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        api = SyncthingAPI(f"http://127.0.0.1:{port}", "test-key")

        with pytest.raises(RuntimeError, match="non-loopback"):
            api.get_json("/rest/system/status", timeout=5)
    finally:
        server.shutdown()
        thread.join()
```

Add the companion test proving loopback-to-loopback redirects still work. A handler
that redirects `/old` to `/data` on the same server and serves JSON at `/data`:

```python
class _LoopbackRedirectingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data":
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            port = self.server.server_address[1]
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/data")
            self.end_headers()

    def log_message(self, *args):
        pass


def test_follows_redirect_to_loopback() -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), _LoopbackRedirectingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        api = SyncthingAPI(f"http://127.0.0.1:{port}", "test-key")

        assert api.get_json("/old", timeout=5) == {"ok": True}
    finally:
        server.shutdown()
        thread.join()
```

Both tests must pass against the current implementation (the handler is already
correct). Sanity-check the rejection test by temporarily commenting out
`_LoopbackOnlyHTTPRedirectHandler` from the opener's handler list and confirming the
test then fails; restore before committing. This guards against re-introducing a
vacuous test.

### Step R2: Extract `_validate_local_api_url` and guard `get_json` (RED first)

Red: add the mutation test. It must fail against the current code (no re-validation
exists, and the unroutable TEST-NET host means the current code fails with a timeout
or `URLError`-derived message instead of the loopback rejection):

```python
def test_get_json_revalidates_base_url_before_request() -> None:
    api = SyncthingAPI("http://127.0.0.1:8384", "test-key")
    api.base_url = "http://192.0.2.10:8384"

    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        api.get_json("/rest/system/status", timeout=5)
```

Green:

1. Add the `_validate_local_api_url` helper (see Public Interfaces) above the
   `SyncthingAPI` class.
2. Replace the inlined scheme/host validation in `__init__` with
   `parsed = _validate_local_api_url(self.base_url)`. The constructor's subsequent
   `parsed.scheme` branches are unchanged.
3. Insert `_validate_local_api_url(self.base_url)` as the first statement of
   `get_json`.

All existing constructor rejection tests must still pass unchanged — the helper is a
pure extraction of the same logic and the same `_LOCAL_ONLY_ERROR` message.

### Step R3: Make `allow_local_https_self_signed` keyword-only (RED first)

Red:

```python
def test_allow_local_https_self_signed_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        SyncthingAPI("https://127.0.0.1:8384", "test-key", False)  # type: ignore[misc]
```

Green: add `*,` before `allow_local_https_self_signed` in `__init__`.

### Step R4: Explicit verified context on self-signed opt-out (RED first)

Red: replace the current weak assertion. Today
`test_local_https_uses_verified_tls_when_opted_out` asserts `api.ssl_context is None`;
change it to assert the explicit verified context, which fails until implemented:

```python
def test_local_https_uses_verified_tls_when_opted_out() -> None:
    api = SyncthingAPI(
        "https://127.0.0.1:8384",
        "test-key",
        allow_local_https_self_signed=False,
    )
    assert api.ssl_context is not None
    assert api.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert api.ssl_context.check_hostname is True
```

Also strengthen the default-mode test while here:

```python
def test_local_https_uses_self_signed_by_default() -> None:
    api = SyncthingAPI("https://127.0.0.1:8384", "test-key")
    assert api.ssl_context is not None
    assert api.ssl_context.verify_mode == ssl.CERT_NONE
    assert api.ssl_context.check_hostname is False
```

Green: restructure the constructor's SSL block so HTTPS always gets an explicit
context:

```python
if parsed.scheme == "https":
    ctx = ssl.create_default_context()
    if allow_local_https_self_signed:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    self.ssl_context: ssl.SSLContext | None = ctx
else:
    self.ssl_context = None
```

The opener construction below it is unchanged (`HTTPSHandler(context=self.ssl_context)`
is only appended for HTTPS, and now always receives a real context).

`import ssl` is already present in `tests/test_api.py`'s dependencies via the
assertions — add `import ssl` to the test file if not already imported.

### Step R5: Add the missing URL test cases from the original plan (test-only)

These must all pass against the post-R2 code; if any fails, fix the validator, not the
test:

```python
@pytest.mark.parametrize(
    "url",
    [
        "",
        "127.0.0.1:8384",   # scheme-less; urlparse yields no usable scheme
        "localhost:8384",   # urlparse treats "localhost" as the scheme
        "file:///tmp/syncthing.sock",
    ],
)
def test_rejects_unsupported_or_malformed_urls(url: str) -> None:
    with pytest.raises(RuntimeError, match="Only local Syncthing"):
        SyncthingAPI(url, "test-key")


def test_accepts_nontrivial_loopback_range_address() -> None:
    api = SyncthingAPI("http://127.1.2.3:8384", "test-key")
    assert api.base_url == "http://127.1.2.3:8384"
```

### Step R6: Restore stripped comments in `tests/test_syncthing.py` (restoration-only)

The ten deleted lines were comments only; `8b11f12` made no other change to that file.
Restore the pre-commit version wholesale:

```bash
git checkout 8b11f12^ -- tests/test_syncthing.py
```

Then verify the diff against `8b11f12` shows exactly the ten comment lines returning
and nothing else:

```bash
git diff 8b11f12 -- tests/test_syncthing.py
```

---

## Testing Strategy

- All new and modified tests live in `tests/test_api.py` (established by `8b11f12` and
  consistent with the per-module convention: `test_folders.py`, `test_activity.py`).
- TDD ordering is per-step, not per-plan: R2, R3, R4 each have an explicit red phase
  with the failing run observed via `./run.sh uv run pytest tests/test_api.py` before
  implementation. R1, R5, R6 are test-only or restoration changes (no red phase per
  protocol §9's enforcement rule).
- The stub servers bind `("127.0.0.1", 0)` (ephemeral port) so tests never collide
  with a real Syncthing on 8384 and remain parallel-safe.
- The redirect rejection test's off-box target is `192.0.2.10` (TEST-NET-1): if the
  handler ever regresses, the test fails with the loopback-rejection mismatch or a
  connection error to an unroutable address — no real host is ever contacted.
- Full gate before each commit:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

Targeted formatting only (`tests/test_api.py`, `py_modules/sdh_ludusavi/syncthing/api.py`)
if unrelated dirty files exist in the working tree at execution time.

---

## Commit Sequence

Atomic commits on `fix/syncthing_tls_verify`, in this order. Do not amend or rebase
`8b11f12`.

1. `docs(plans): add syncthing loopback review remediation plan`
   — this file.
2. `test(syncthing): restore comments stripped from unrelated tests`
   — Step R6 alone; pure restoration of user-owned content.
3. `test(syncthing): exercise redirect handler with live loopback stubs`
   — Step R1 (replace vacuous test, add loopback-follow companion) and Step R5
   (missing URL cases). Test-only commit.
4. `fix(syncthing): re-validate base_url before each API request`
   — Step R2: helper extraction + `get_json` guard + its red-phase test.
5. `fix(syncthing): make allow_local_https_self_signed keyword-only`
   — Step R3 + its test.
6. `fix(syncthing): use explicit verified TLS context on self-signed opt-out`
   — Step R4 + its test updates.

Each commit must pass the full quality gate and the pre-commit hook (which includes
`scripts/check_tdd.sh`).

---

## Acceptance Criteria

- [ ] `test_rejects_redirect_to_non_loopback` uses a real `http.server` stub and fails
      when `_LoopbackOnlyHTTPRedirectHandler` is removed from the opener (verified
      manually during R1, handler restored afterward).
- [ ] Loopback-to-loopback redirects are followed (companion test passes).
- [ ] `_validate_local_api_url` exists as a module-level helper; `__init__` and
      `get_json` both call it; the redirect handler still uses `_is_loopback_host`.
- [ ] Mutating `api.base_url` to a non-loopback URL after construction causes
      `get_json` to raise the loopback rejection before any request is sent.
- [ ] `allow_local_https_self_signed` is keyword-only; positional use raises
      `TypeError`.
- [ ] `self.ssl_context` is a real `SSLContext` for every HTTPS client:
      `CERT_NONE`/no-hostname-check in default mode, `CERT_REQUIRED`/hostname-check in
      opt-out mode; `None` only for HTTP.
- [ ] `tests/test_syncthing.py` is byte-identical to its `8b11f12^` version.
- [ ] Empty, scheme-less, `file://`, and `127.1.2.3` URL cases are covered.
- [ ] `watcher.py:291` re-verified as the only production `SyncthingAPI(` call site.
- [ ] All gates pass: `ruff check`, `ruff format`, `ty check`, full `pytest` via
      `./run.sh`.
- [ ] No new dependencies; standard library only.
- [ ] Session log recorded in `docs/agent_conversations/`.

---

## Design Decisions Record

- **No history rewrite of `8b11f12`.** Even though the branch is local-only, follow-up
  atomic commits are cheaper, run the pre-commit hooks per concern, and keep the review
  trail honest: the review found defects in a commit, and the fixes are visible as
  commits.
- **Redirect handler keeps its own error message.** "Syncthing API {code} response
  redirected to non-loopback host '{host}'. Refusing to follow redirect." is more
  diagnostic than `_LOCAL_ONLY_ERROR` for this failure mode, and it is a static-format
  string safe for RPC surfaces.
- **`ssl_context` always explicit for HTTPS.** Relying on `HTTPSHandler(context=None)`
  falling back to `http.client`'s default verified context was functionally correct
  but made the TLS policy invisible to tests and readers. An explicit context costs
  one line and makes the policy assertable.
- **Vacuous-test prevention.** The R1 sanity check (comment out the handler, watch the
  test fail, restore) is a one-time manual mutation check, recorded here so the
  implementing agent does not skip it.
