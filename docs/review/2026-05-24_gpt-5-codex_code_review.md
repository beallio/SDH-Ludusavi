# GPT-5 Codex Code Review - 2026-05-24

## Review Scope

Reviewed first-party code and repo-owned scripts/tests for SDH-ludusavi. Excluded `node_modules`, `dist`, `out`, and vendored `py_modules/pyludusavi`.

Protocol facts verified during review:

- Project root: `/home/beallio/Dropbox/Scripts/SDH-ludusavi`
- Execution mode: Project
- Cache root: `/tmp/sdh_ludusavi`
- Command wrapper: `./run.sh`
- Type checker: `ty`

Validation run:

- `./run.sh uv run pytest` passed with `261 passed`
- `./run.sh pnpm run typecheck` passed

## Findings

* **[Critical]**
* **File & Function/Line:** `py_modules/sdh_ludusavi/service.py` `pause_game_process` line 283; `_send_signal_tree` line 1578
* **Description:** RPC-exposed process signaling accepts arbitrary integer PIDs. `pid=0` signals the current process group and `pid=-1` can signal every permitted process, causing denial of service or suspending unrelated processes.
* **Vulnerable Code:**
```python
pid = int(pid)
if not _send_signal_tree(pid, signal.SIGSTOP):
    ...
```
```python
for target_pid in _process_tree(pid):
    os.kill(target_pid, sig)
```
* **Proposed Fix:**
```python
def _coerce_signal_pid(value: object) -> int:
    try:
        pid = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("PID must be a positive process id") from exc
    if pid <= 1:
        raise ValueError("Refusing to signal process id <= 1")
    return pid

def pause_game_process(self, pid: int) -> dict[str, object]:
    try:
        pid = _coerce_signal_pid(pid)
    except ValueError as exc:
        return {"status": "failed", "message": str(exc)}
    ...
```

* **[High]**
* **File & Function/Line:** `py_modules/sdh_ludusavi/service.py` `check_game_start` line 743; `check_game_exit` line 921; diagnostics thread line 1537
* **Description:** Several Ludusavi subprocess calls bypass `_run_locked`, despite the service contract saying only one Ludusavi operation should run at once. This can race backup/restore/preview/version/config operations against each other.
* **Vulnerable Code:**
```python
recency = self._ludusavi().compare_recency(game.name)
preview = self._ludusavi().backup(game.name, preview=True)
threading.Thread(target=run, daemon=True).start()
```
* **Proposed Fix:**
```python
try:
    recency = self._run_locked(
        "start_check",
        game.name,
        lambda: self._ludusavi().compare_recency(game.name),
    )
except OperationLockedError:
    return self._skip("start", game.name, "operation_running")

try:
    preview = self._run_locked(
        "exit_check",
        game.name,
        lambda: self._ludusavi().backup(game.name, preview=True),
    )
except OperationLockedError:
    return self._skip("exit", game.name, "operation_running")
```

* **[High]**
* **File & Function/Line:** `src/index.tsx` `ConflictResolutionModal` line 720
* **Description:** The modal's default OK action restores the backup. On a save conflict, a default confirm action should not perform the destructive choice that may overwrite local saves.
* **Vulnerable Code:**
```tsx
<ConfirmModal
  bAlertDialog={true}
  strTitle="Conflict Detected"
  onOK={() => choose("restore_backup")}
  onCancel={dismiss}
>
```
* **Proposed Fix:**
```tsx
<ConfirmModal
  bAlertDialog={true}
  strTitle="Conflict Detected"
  onOK={dismiss}
  onCancel={dismiss}
>
```

* **[Medium]**
* **File & Function/Line:** `src/index.tsx` `handleAppStart` line 1610
* **Description:** The frontend pauses every app with an `instanceID` before checking whether auto-sync is enabled or the game is tracked. That can stall unrelated launches and magnifies the PID-signaling risk above.
* **Vulnerable Code:**
```tsx
if (typeof instanceID === "number" && instanceID > 0) {
  const pauseResult = await pauseGameProcessCall(instanceID);
  ...
}
```
* **Proposed Fix:**
```tsx
const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
const shouldPause = autoSyncEnabled && tracked && typeof instanceID === "number" && instanceID > 1;

if (shouldPause) {
  const pauseResult = await pauseGameProcessCall(instanceID);
  if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
    paused = true;
  }
}
```

* **[Medium]**
* **File & Function/Line:** `py_modules/sdh_ludusavi/service.py` `_apply_state_data` line 1119; `_load_state` line 1226
* **Description:** Boolean settings are coerced with `bool(...)`, so malformed persisted data like `"false"` becomes `True`, potentially enabling auto-sync unexpectedly.
* **Vulnerable Code:**
```python
self._auto_sync_enabled = bool(data.get("auto_sync_enabled", False))
self._auto_sync_enabled = bool(settings.get("auto_sync_enabled", False))
```
* **Proposed Fix:**
```python
def _coerce_bool(value: object, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default

self._auto_sync_enabled = _coerce_bool(data.get("auto_sync_enabled"), False)
self._selected_game = self._sanitize_name(str(data.get("selected_game", "")))
```

* **[Medium]**
* **File & Function/Line:** `py_modules/sdh_ludusavi/service.py` `get_game_history` line 404; `get_recent_logs` line 1115
* **Description:** Accessors return live mutable state without locking. Direct callers can mutate service internals, and concurrent background RPC threads can observe partially updated state.
* **Vulnerable Code:**
```python
def get_game_history(self) -> dict[str, dict[str, Any]]:
    return self._game_history
```
* **Proposed Fix:**
```python
from copy import deepcopy

def get_game_history(self) -> dict[str, dict[str, Any]]:
    with self._state_lock:
        return deepcopy(self._game_history)

def get_recent_logs(self) -> list[dict[str, object]]:
    return [entry.to_dict() for entry in list(self._logs)]
```

* **[Medium]**
* **File & Function/Line:** `.git/hooks/pre-commit` line 27; `scripts/pre_commit.sh` line 34
* **Description:** The live pre-commit hook does not run the frontend supply-chain/typecheck/build verification that the tracked script runs. The tracked script also invokes `pnpm` without `./run.sh`, bypassing the repo wrapper policy.
* **Vulnerable Code:**
```bash
./run.sh uv run pytest || { echo "Pytest failed. Commit aborted."; exit 1; }
./run.sh bash scripts/check_tdd.sh || { echo "TDD check failed!"; exit 1; }
```
* **Proposed Fix:**
```bash
./run.sh uv run pytest || { echo "Pytest failed. Commit aborted."; exit 1; }

echo "Running frontend supply-chain checks..."
./run.sh pnpm run verify || { echo "Frontend supply-chain checks failed."; exit 1; }

./run.sh bash scripts/check_tdd.sh || { echo "TDD check failed."; exit 1; }
```

* **[Medium]**
* **File & Function/Line:** `scripts/check_tdd.sh` line 12
* **Description:** `test_file` is never assigned. Any staged first-party Python source file would make the TDD gate test an empty path and fail with a misleading missing-test message.
* **Vulnerable Code:**
```bash
if [[ ! -f "$test_file" ]]; then
  echo "Missing test: $test_file for source file: $f"
  exit 1
fi
```
* **Proposed Fix:**
```bash
test_file="tests/test_${base}.py"
if [[ ! -f "$test_file" ]]; then
  echo "Missing test: $test_file for source file: $f"
  exit 1
fi
```

* **[Best Practice]**
* **File & Function/Line:** `py_modules/sdh_ludusavi/ludusavi.py` `get_aliases` line 85; `compare_recency` line 101
* **Description:** Broad `except Exception: pass` blocks hide Ludusavi/config failures. The caller sees ambiguous behavior, but logs lack enough evidence to diagnose root cause.
* **Vulnerable Code:**
```python
except Exception:
    pass
```
* **Proposed Fix:**
```python
except Exception as exc:
    LOGGER.warning("Unable to read Ludusavi aliases: %s", exc, exc_info=True)
```
