# Offload Backend Stop During Plugin Unload

Date: 2026-05-25
Planner Model: codex_gpt-5
Review Source: `docs/review/2026-05-24_gemini_3_5_flash.md`

## Execution Skill

Execute this plan with the `implementer` skill. The implementation must follow that
skill's discovery, branch isolation, strict TDD, atomic commit, validation, and
review-gate workflow, while also honoring this repository's `AGENTS.md` protocol.

## Problem Definition

`Plugin._unload()` currently calls `self._backend.stop()` synchronously on the Decky
async event loop:

```python
async def _unload(self) -> None:
    if self._backend is not None:
        self._backend.stop()
    decky.logger.info("SDH-ludusavi backend unloaded")
```

`SDHLudusaviService.stop()` can block while it:

- signals the watchdog thread to stop
- joins the watchdog thread for up to one second
- resumes all paused process trees
- scans `/proc` while sending `SIGCONT` to tracked process trees

Unload cleanup must remain best effort, but it should not block the event loop. The
repo already centralizes blocking service calls through `Plugin._call()`, which uses
`_run_blocking()`.

## Architecture Overview

Route unload cleanup through the existing async-to-sync bridge:

```mermaid
sequenceDiagram
    participant Decky as Decky Loader
    participant Plugin as Plugin._unload
    participant Loop as Async Event Loop
    participant Worker as _run_blocking Worker
    participant Service as SDHLudusaviService
    participant OS as SteamOS Processes

    Decky->>Plugin: unload lifecycle hook
    Plugin->>Loop: await self._call("unload_stop", lambda: self._backend.stop())
    Loop->>Worker: execute stop off event loop
    Worker->>Service: stop()
    Service->>Service: signal watchdog stop
    Service->>Service: join watchdog with timeout
    Service->>OS: SIGCONT paused process trees
    Worker-->>Loop: cleanup result
    Loop-->>Plugin: _call completes
    Plugin->>Decky: log backend unloaded
```

This keeps the current cleanup semantics while using the same cancellation and error
mapping behavior as other backend operations. Because unload is also a shutdown
safety path, `_unload()` must synchronously fall back to `backend.stop()` when the
offloaded bridge reports failure before reliable cleanup is known to have completed.
The fallback must catch and log its own exceptions so unload logging still completes.

## Core Data Structures

No new data structures.

Existing service fields involved:

- `self._backend: SDHLudusaviService | None`
- `SDHLudusaviService._watchdog_stop`
- `SDHLudusaviService._watchdog_thread`
- `SDHLudusaviService._paused_pids`
- `SDHLudusaviService._paused_pids_lock`

## Public Interfaces

No public RPC or frontend interface changes.

Internal behavior change:

- `Plugin._unload()` awaits `_call("unload_stop", ...)` instead of invoking
  `stop()` directly.
- If the offloaded stop returns a failed RPC payload, `_unload()` logs a warning and
  invokes `backend.stop()` synchronously as a last-resort cleanup.

## Implementation Steps

1. Update `main.py::_unload`.
2. Keep the existing unloaded log message after stop cleanup completes.
3. Do not initialize the service during unload if `_backend is None`.
4. Add a synchronous fallback if `_call()` returns `{"status": "failed", ...}`.
5. Wrap the synchronous fallback in `try/except Exception` and log fallback failure
   with `decky.logger.exception(...)`.
6. Treat `SDHLudusaviService.stop()` as best-effort and idempotent enough for a
   second unload cleanup attempt; update tests if needed to pin this behavior.
7. Add regression coverage proving `_unload` uses `_call()` and remains nonblocking
   for a slow `stop()`.
8. Add regression coverage proving failed offload triggers synchronous fallback.

## Example Code

```python
async def _unload(self) -> None:
    if self._backend is not None:
        await self._call("unload_stop", lambda: self._backend.stop())
    decky.logger.info("SDH-ludusavi backend unloaded")
```

For type-check friendliness, capture the backend before the lambda:

```python
async def _unload(self) -> None:
    backend = self._backend
    if backend is not None:
        result = await self._call("unload_stop", backend.stop)
        if isinstance(result, dict) and result.get("status") == "failed":
            decky.logger.warning(
                "Offloaded unload stop failed; falling back to synchronous stop"
            )
            try:
                backend.stop()
            except Exception:
                decky.logger.exception("Synchronous unload stop fallback failed")
    decky.logger.info("SDH-ludusavi backend unloaded")
```

Use the bound-method form for type-check friendliness. The fallback intentionally
accepts possible duplicate cleanup because leaving paused processes suspended is a
higher-risk shutdown failure than a second best-effort `stop()` call.

## Testing Strategy

Strict TDD applies because this changes runtime unload behavior.

Add tests to `tests/test_main.py` before implementation.

Test 1: unload delegates through `_call`.

```python
def test_unload_stops_backend_through_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[str] = []

    class Backend:
        def stop(self) -> None:
            calls.append("stop")

    async def fake_call(operation: str, callback: Any) -> Any:
        calls.append(operation)
        return callback()

    plugin._backend = Backend()
    monkeypatch.setattr(plugin, "_call", fake_call)

    asyncio.run(plugin._unload())

    assert calls == ["unload_stop", "stop"]
    assert logger.infos[-1] == "SDH-ludusavi backend unloaded"
```

Test 2: unload does not block the event loop while stop runs.

```python
def test_unload_does_not_block_event_loop_while_stop_runs(...) -> None:
    class SlowBackend:
        def stop(self) -> None:
            time.sleep(0.15)

    async def scenario() -> None:
        task = asyncio.create_task(plugin._unload())
        await asyncio.sleep(0.01)
        assert not task.done()
        assert time.perf_counter() - started < 0.08
        await task
```

Use the real `_call()` for the nonblocking test so it exercises `_run_blocking`.

Test 3: failed offload falls back synchronously.

```python
def test_unload_falls_back_to_synchronous_stop_when_offload_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()
    calls: list[str] = []

    class Backend:
        def stop(self) -> None:
            calls.append("stop")

    async def fake_call(operation: str, callback: Any) -> dict[str, str]:
        calls.append(operation)
        return {"status": "failed", "message": "loop closed"}

    plugin._backend = Backend()
    monkeypatch.setattr(plugin, "_call", fake_call)

    asyncio.run(plugin._unload())

    assert calls == ["unload_stop", "stop"]
    assert any("falling back to synchronous stop" in msg for msg in logger.warnings)
```

Test 4: synchronous fallback exceptions are logged and do not prevent unload logging.

## Validation

Targeted validation:

```bash
./run.sh uv run pytest tests/test_main.py::test_unload_stops_backend_through_call tests/test_main.py::test_unload_does_not_block_event_loop_while_stop_runs
```

If exact test names differ after implementation, run the whole file:

```bash
./run.sh uv run pytest tests/test_main.py
```

Full validation before commit:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

## Acceptance Criteria

- `_unload()` does not synchronously call `self._backend.stop()`.
- Existing unload logging remains.
- If there is no backend instance, unload still only logs and returns.
- Slow watchdog stop or process resume work runs through `_run_blocking`.
- Backend stop errors are mapped by `_call()` consistently with other operations.
- If plugin unload is cancelled or the event loop begins shutdown, the cancellation path and descriptor cleanups degrade gracefully.
- If the offloaded stop fails, `_unload()` attempts exactly one synchronous fallback.
- Synchronous fallback exceptions are logged and do not suppress the final unload log.
- `SDHLudusaviService.stop()` remains safe as a repeated best-effort cleanup call.
