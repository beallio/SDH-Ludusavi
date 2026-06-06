# Thermo-Nuclear Code Quality Review

**Branch**: `feat/syncthing-status-strip-activity`
**Base**: `main` (`ef1a679`)
**Commits**: `24f1231`, `950e867`
**Diff**: +2334 / -28 lines across 17 files

---

## Verdict: **Not Approved — Structural Regressions Present**

The feature behavior appears correct and the plan was thorough. But the implementation
ships a new 1131-line monolith, grows the lifecycle controller by ~43% with tangled
polling logic, and misses several clear paths to delete complexity. The code works, but
it makes the codebase messier.

---

## 1. Presumptive Blocker: `syncthing.py` is 1131 Lines on Day One

> [!CAUTION]
> A brand-new file ships at **exactly** 1131 lines. There is no legacy reason for this — the
> file was written from scratch. This is the one moment where decomposition is cheapest.

[syncthing.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py) contains **five distinct responsibilities** in a single file:

| Responsibility | Lines (approx) | Natural module |
|---|---|---|
| Config discovery (XML parse, flatpak probing, credential resolution) | 79–401 | `syncthing/config.py` |
| Folder resolution (path normalization, folder lookup, selection) | 214–496 | `syncthing/folders.py` |
| API client (`SyncthingAPI`, `get_json`, HTTP layer) | 169–212 | `syncthing/api.py` |
| Activity computation (state machine, rates, pruning, `compute_activity_status`) | 506–773 | `syncthing/activity.py` |
| Watch manager + daemon thread (`SyncthingWatch`, `SyncthingWatchManager`) | 870–1132 | `syncthing/watcher.py` |

**Remedy**: Turn `syncthing.py` into a `syncthing/` package with an `__init__.py` that
re-exports the public surface (`SyncthingWatchManager`, config discovery). Each
sub-module becomes 100–250 lines, independently testable, and independently readable.
The test file can split similarly.

This is the single highest-leverage change in this review.

---

## 2. Structural: Lifecycle Controller Syncthing Polling is Spaghetti Growth

[gameLifecycleController.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx) grew from 533 → 760 lines. The new
Syncthing monitor logic (lines [138–334](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L138-L334)) is **~200 lines of setInterval-based polling state machine**
injected directly into the controller closure. This is the wrong layer for this logic.

### Problems

1. **Three levels of stop semantics**: `stopSpecificWatch` → `stopSyncthingMonitorWithoutTokenIncrement` → `stopSyncthingMonitor`. The token/generation dance exists because the polling loop is inlined in the controller — if the monitor were its own abstraction, the generation check would be internal.

2. **Repeated cleanup pattern**: The pattern `if (intervalID !== null) { window.clearInterval(intervalID); } if (activeWatchID === watchID) { activePollInterval = null; activeWatchID = null; } await stopSpecificWatch(watchID);` appears **7 times** in the polling callback (lines [200–203](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L200-L203), [209–217](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L209-L217), [223–239](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L223-L239), [244–251](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L244-L251), [304–311](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L304-L311), [319–326](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L319-L326)). Copy-paste, not abstraction.

3. **Status mapping logic leaks into lifecycle orchestration**: Lines [257–315](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L257-L315) contain the syncthing-status-to-strip-status mapping, settled-count tracking, and activity detection. This is feature-specific status interpretation living in the orchestration layer.

### Code-Judo Move

**Extract a `SyncthingMonitor` class/module** (e.g. `src/controllers/syncthingMonitor.ts`):

```typescript
// ~80 lines instead of ~200 inlined
class SyncthingMonitor {
  constructor(private rpc: SyncthingRpc, private onStatus: StatusCallback) {}
  async start(phase, name, appID): Promise<void> { /* start watch, begin polling */ }
  async stop(): Promise<void> { /* idempotent cleanup */ }
  dispose(): void { /* synchronous teardown */ }
}
```

The lifecycle controller then becomes:

```typescript
const monitor = new SyncthingMonitor(rpc, (status) => publishAutoSyncStatus(status, {...}));
// in handleAppStart:
await monitor.start("pre_game", name, appID);
// in handleAppExit:
await monitor.stop();
// in dispose:
monitor.dispose();
```

This deletes the token/generation dance, the 7 repeated cleanup blocks, and the status
mapping logic from the controller. The controller goes back to ~550 lines. The monitor
is independently testable.

---

## 3. Structural: `process_event` is a Long Elif Chain with Repeated Guard

Every branch in [process_event](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L776-L867) repeats `data.get("folder") == folder.folder_id`. This is checked
**10 times** in the function body. The `DownloadProgress` branch is the only one that
doesn't check it (because the folder ID is a dict key, not a field).

### Code-Judo Move

Extract the folder guard to the top of the function for events that use it:

```python
def process_event(event, folder, folder_state, runtime, remote_progress, local_activity, now):
    event_type = event.get("type")
    data = event.get("data") or {}
    if not isinstance(data, dict):
        return folder_state, runtime, remote_progress, local_activity, False

    event_folder = data.get("folder")
    is_our_folder = event_folder == folder.folder_id

    # Events that require folder match
    if event_type == "ConfigSaved":
        return folder_state, runtime, remote_progress, local_activity, True
    if event_type == "DownloadProgress":
        # special: keyed by folder ID in data dict
        ...
    if not is_our_folder:
        return folder_state, runtime, remote_progress, local_activity, False
    # All remaining handlers implicitly know they match our folder
    ...
```

This deletes 10 repeated conditionals and makes the code ~20 lines shorter. More
importantly, it makes the contract explicit: "all handlers below this point are for our
folder."

---

## 4. Boundary Problem: `_run()` Loop Mixes Concerns

[`SyncthingWatch._run()`](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L907-L1044) is 137 lines in a single method. It interleaves:

- Connection rate polling
- Folder status polling
- Remote progress pruning
- Local activity pruning
- Activity status computation
- Sample dict serialization
- Event polling and dispatch
- Config change handling

**Remedy**: Extract the per-tick work into a named method:

```python
def _tick(self, state: WatchState) -> WatchState:
    """Single iteration of the watch loop. Pure state transform."""
    ...
```

The `_run` method becomes a loop that calls `_tick` and sleeps. The tick is independently
testable without threading. This also makes the `latest_sample` serialization testable
without starting a thread.

---

## 5. Missed Simplification: Manual `FolderRuntime` Reconstruction

Lines [848–859](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L848-L859) manually reconstruct a `FolderRuntime` frozen dataclass by copying every
field except `sequence`:

```python
runtime = FolderRuntime(
    sequence=sequence or runtime.sequence,
    remote_sequence=runtime.remote_sequence,
    need_bytes=runtime.need_bytes,
    ...8 more fields...
)
```

This is brittle — any new field added to `FolderRuntime` must also be added here.

**Remedy**: Use `dataclasses.replace`:

```python
from dataclasses import replace
runtime = replace(runtime, sequence=sequence or runtime.sequence)
```

One line instead of twelve. Automatically forward-compatible with new fields.

---

## 6. Boundary Problem: `SyncthingWatch.latest_sample` is an Untyped Dict

[`latest_sample`](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L893) is `dict[str, Any]`. The serialization at lines [984–1006](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L984-L1006) manually
constructs the dict from `ActivityStatus` fields. The frontend then accesses these keys
by string name. There's no typed contract between the two — the shape is implicit.

This is acceptable for a v1 Decky RPC boundary (which is inherently untyped), but the
backend should at least use a typed serialization helper:

```python
def activity_status_to_sample(status: ActivityStatus, folder: FolderSelection) -> dict[str, Any]:
    return { ... }
```

This makes the serialization contract testable and keeps it out of the thread loop.

---

## 7. Subscribed-But-Unhandled Event: `RemoteIndexUpdated`

`EVENT_TYPES` on [line 33](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L33) subscribes to `RemoteIndexUpdated`, but `process_event` has no handler
for it. This event falls through to the default return. If it's intentional (the status
polling already captures sequence changes), remove it from `EVENT_TYPES` to avoid
unnecessary event traffic. If it's needed, add the handler.

---

## 8. `is_inside` Calls `normalize_path` Three Times

[`is_inside`](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L218-L224) calls `normalize_path(parent)` **twice** (once in the list, once in the
comparison). Each call does `expanduser → abspath → realpath → normcase`. This is a
minor inefficiency but more importantly it obscures the logic:

```python
def is_inside(parent: str, child: str) -> bool:
    np, nc = normalize_path(parent), normalize_path(child)
    try:
        return os.path.commonpath([np, nc]) == np
    except ValueError:
        return False
```

---

## 9. Pre-Existing: `isRpcStatus` is Duplicated 4 Times

This isn't new to this PR, but the PR **adds a 4th copy** in
[gameLifecycleController.tsx:94](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L94-L101).
Identical copies exist in:

- [index.tsx:139](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx#L139)
- [ludusaviLauncher.ts:79](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/ludusaviLauncher.ts#L79)
- [settingsMutationController.tsx:124](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/settings/settingsMutationController.tsx#L124)

Since this PR touches the files that own copies 1 and 4, it would be low-cost to
extract `isRpcStatus` to a shared utility (e.g. `src/utils/rpc.ts`) and import it.
This is not a blocker, but it's a missed opportunity to reduce copy-paste debt while
the files are already open.

---

## 10. `LocalActivity` Mutability Makes `prune_local_activity` Surprising

[`prune_local_activity`](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L612-L631) takes a `LocalActivity`, **mutates it in place**, and also returns it.
The caller at [line 970](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L970) reassigns the return value, implying it's a pure transform. But
`LocalActivity` is a mutable `@dataclass`, so the mutation happens regardless of the
return value.

Pick one contract:
- If it's a mutation, don't return and don't reassign at the call site.
- If it's a transform, make it return a new `LocalActivity` (or use `frozen=True` and
  `dataclasses.replace`).

The current dual-contract is confusing.

---

## 11. `active_items` Null Guard is Defensive Against an Impossible State

[`process_event` line 789](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L789):
```python
if local_activity.active_items is None:
    local_activity.active_items = {}
```

`active_items` has a `field(default_factory=dict)`. The only way it can be `None` is if
someone explicitly sets it. The watch thread initializes it as `LocalActivity(active_items={})`.
This guard is dead code that obscures the real invariant (the field is always a dict).
Remove it.

Similarly, [`compute_activity_status` line 662](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/syncthing.py#L662):
```python
active_items = local_activity.active_items or {}
```
Same issue — `active_items` is always a dict. The `or {}` is never triggered.

---

## 12. Frontend: `startSyncthingMonitor` is Fire-and-Forget with No Error Surface

In [handleAppStart](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L388):
```typescript
startSyncthingMonitor("pre_game", name, appID, tracked);
```

This is called **without `await`**. The function is `async` and can throw. If it throws,
the error is silently swallowed. This is a design choice (Syncthing monitoring is
best-effort), but it should be explicit:

```typescript
void startSyncthingMonitor("pre_game", name, appID, tracked);
```

The `void` prefix makes the fire-and-forget intent visible. Currently it looks like
a missing `await`.

---

## 13. `iconSvgForAutoSyncStatus` Growing Unchecked

[iconSvgForAutoSyncStatus](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/surfaces/autoSyncStatusSurface.tsx#L187-L224) is an if-chain that returns SVG string literals. The PR adds
3 more branches (lines 200–220). This is fine for now, but the function is heading toward
a `Record<AutoSyncStatusKind, string>` lookup — the same pattern already used for
`autoSyncStatusText` at [line 16](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/surfaces/autoSyncStatusSurface.tsx#L16).

Not a blocker, but the pattern inconsistency is worth noting: text uses a record, icons
use an if-chain. Unifying them would delete ~30 lines.

---

## Summary of Required Actions

| # | Severity | Issue | Action |
|---|---|---|---|
| 1 | **Blocker** | `syncthing.py` is 1131 lines on day one | Decompose into `syncthing/` package |
| 2 | **Blocker** | Syncthing polling logic tangled into lifecycle controller | Extract `SyncthingMonitor` |
| 3 | **Strong** | `process_event` repeats folder guard 10x | Factor out early-exit guard |
| 4 | **Strong** | `_run()` mixes 6 concerns in 137 lines | Extract `_tick()` method |
| 5 | **Medium** | Manual `FolderRuntime` reconstruction (12 fields) | Use `dataclasses.replace` |
| 6 | **Medium** | `latest_sample` untyped dict serialization | Extract serialization helper |
| 7 | **Low** | `RemoteIndexUpdated` subscribed but unhandled | Remove from `EVENT_TYPES` or add handler |
| 8 | **Low** | `is_inside` triple normalization | Cache normalized values |
| 9 | **Low** | `isRpcStatus` duplicated 4x | Extract to shared utility |
| 10 | **Low** | `prune_local_activity` dual contract | Pick mutate-or-transform |
| 11 | **Nit** | Dead `None` guards on `active_items` | Remove |
| 12 | **Nit** | Fire-and-forget without `void` prefix | Add `void` for clarity |
| 13 | **Nit** | Icon SVG if-chain vs record pattern | Consider unifying |

Items 1 and 2 are presumptive blockers per the review standard. The branch adds a lot of
correct, well-tested behavior — but the implementation packs too much into too few files
and layers, and the opportunity to decompose cleanly is strongest right now before the
code grows further.
