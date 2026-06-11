# Plan: Lazy Updater Release Validation + Syncthing Watch TTL

Status: ready for implementation
Date: 2026-06-11
Branch: work directly on `dev` (matches repo history; recent `feat(status)` commits land on `dev`).
Execution: **The implementing agent MUST run this plan via the `implementer` skill**
(`Skill: implementer`, pass this file as the plan). Follow the project protocol in
`CLAUDE.md`: handshake, strict TDD (red → green → refactor), `./run.sh` wrapper for
all tooling, atomic Conventional Commits, session log at the end.

Model guidance: use a Haiku-class model (e.g. via `Agent` with `model: "haiku"`) only
for mechanical, low-risk subtasks — drafting the session log, formatting docs,
summarizing test output. All code and test authoring must be done by the primary
(stronger) model. Do not delegate edits of `updater.py` or `watcher.py` to Haiku.

---

## Problem Definition

Two independent backend inefficiencies, fixed in two independent, separately
committed parts:

**Part A — Updater eager validation.**
`PluginUpdater.check_for_update` (`py_modules/sdh_ludusavi/updater.py:387`) fetches
the GitHub release list, then calls `validate_release_candidate(r, self._client)`
for **every** release (`updater.py:528-535`). Each call performs a manifest HTTP
fetch via `client.get_manifest(...)` (`updater.py:127`) with a 15-second default
timeout (`updater_client.py:58`, `timeout_seconds: float = 15.0`). A repo with 30
releases therefore costs up to 31 unauthenticated GitHub round-trips per check
(1 list + up to 30 manifests) and burns the 60-req/hour unauthenticated rate limit.
Since `select_candidate` (`updater.py:176`) picks the maximum candidate by a fixed
sort key anyway, we can do the free (local JSON) checks for all releases, sort by
that same key descending, then fetch manifests in that order and stop at the first
fully valid candidate, capped at 5 manifest fetches. Typical cost drops to 2
requests (1 list + 1 manifest) with an **identical selection result**.

**Part B — Syncthing watch TTL.**
`SyncthingWatch._run` (`py_modules/sdh_ludusavi/syncthing/watcher.py:104`) loops
`while not self.stop_event.is_set()`. Each `_tick` issues ~3 HTTP requests
(`get_connection_snapshot`, `get_folder_status`, `get_events` with a 1 s long-poll
— `DEFAULT_EVENT_TIMEOUT_SECONDS = 1.0` in `syncthing/_types.py:32`), i.e. ~3
req/s. Only the frontend enforces a duration cap (`MAX_WATCH_DURATION_MS = 120_000`,
`src/controllers/syncthingMonitor.ts:87`, enforced at `:467-474`). If the CEF/React
context dies mid-watch, nothing calls `stop_watch` and the thread polls until plugin
unload (`service.py:214` `stop_all`). Fix: give each watch a backend TTL deadline of
**180 s** (frontend cap + 60 s margin); the watch thread self-terminates and
deregisters from the manager when the deadline passes. No frontend change —
well-behaved clients stop at 120 s and never observe it.

### Corrections to the original writeup (verified against code — do NOT implement the writeup verbatim)

1. **Do not sort by `published_at` descending.** `select_candidate` does not pick
   the newest-published valid candidate; it picks the maximum by the sort key
   `(major, minor, patch, not is_dev, published_at)` (`updater.py:197-203`).
   Sorting by `published_at` alone would change behavior when an older version is
   published after a newer one (e.g. a back-published `v1.9.1` after `v2.0.0` would
   incorrectly win). Sort by **the exact same key, descending**; then "first valid
   in order" ≡ "max valid", and selection is provably identical.
2. **"Channel" is not fully checkable locally**, but the release's `prerelease`
   flag is a valid local proxy: validation rejects manifests where channel
   disagrees with prerelease (`updater.py:144-148`), and `ReleaseManifest.channel`
   is constrained to `{"stable", "dev"}` (`updater_models.py:115`). Therefore every
   *validated* candidate from a non-prerelease release has channel `"stable"` and
   every validated candidate from a prerelease has `"development"`. So when the
   preferred channel is `"stable"`, pre-filtering out `prerelease == True` releases
   before any manifest fetch is exactly equivalent to `select_candidate`'s
   post-fetch channel filter (`updater.py:187-188`).
3. **Do not "stamp `created_at`".** `SyncthingWatch` already has a wall-clock
   `self.started_at = time.time()` (`watcher.py:77`); leave it alone (it is not
   safe for durations — clock jumps). Add a separate **monotonic** deadline:
   `time.monotonic() + WATCH_TTL_SECONDS`.
4. The frontend already handles a non-`activity` poll result gracefully
   (`syncthingMonitor.ts:510-513`, logs "stopped by backend" and tears down), so a
   deregistered watch answering `{"status": "stopped"}` is safe even for a client
   that polls past the TTL.

---

## Architecture Overview

### Part A: split `validate_release_candidate` into a free stage and a paid stage

File: `py_modules/sdh_ludusavi/updater.py` only. No changes to
`updater_client.py`, `updater_models.py`, `service.py`, or any frontend file.

Current single function (`updater.py:97-173`) interleaves free local checks and
the manifest fetch. Split it:

1. **`prevalidate_release_candidate(release: object) -> PrevalidatedRelease | None`**
   — all checks that need only the release JSON (zero HTTP):
   - `as_string_key_mapping(release)` is not None (`updater.py:98-100`)
   - not `draft` (`updater.py:101-102`)
   - `tag_name` non-empty and starts with `"v"` (`updater.py:104-106`)
   - `parse_plugin_version(tag_name[1:])` succeeds (`updater.py:108-111`)
   - `assets` is a list (`updater.py:115-117`)
   - exactly one asset named `SDH-Ludusavi-{tag_name}.manifest.json`
     (`updater.py:113, 118-125`)
   - exactly one asset whose name ends with `.zip` (move this up from
     `updater.py:150-157` — it is also free; only the *name equality* with
     `manifest.asset_name` needs the manifest)

2. **`validate_prevalidated_candidate(pre: PrevalidatedRelease, client: ReleaseClient) -> UpdateCandidate | None`**
   — the single `client.get_manifest(...)` call plus every manifest-dependent
   check, byte-for-byte the same logic as today (`updater.py:127-173`):
   manifest fetch status 200, `parse_release_manifest`, `plugin_name`,
   `package_name`, `manifest.tag == tag_name`, `"v" + manifest.version == tag_name`,
   channel↔prerelease consistency, `zip_asset name == manifest.asset_name`, then
   construct the `UpdateCandidate` exactly as before (same fields, same
   `action="update"`).

3. **`validate_release_candidate(release, client)` is kept** with its existing
   signature and exact existing behavior, reimplemented as the composition:

   ```python
   def validate_release_candidate(release: object, client: ReleaseClient) -> UpdateCandidate | None:
       pre = prevalidate_release_candidate(release)
       if pre is None:
           return None
       return validate_prevalidated_candidate(pre, client)
   ```

   This keeps `revalidate()` (`updater.py:696`) and all existing tests
   (`tests/test_updater.py:97, 485, 628`) working unchanged.

4. **`check_for_update` replaces the validate-all loop (`updater.py:528-541`)** with:

   ```python
   prevalidated = []
   for r in resp.body:
       if not isinstance(r, dict):
           continue
       pre = prevalidate_release_candidate(r)
       if pre is None:
           continue
       if self._channel == "stable" and pre.prerelease:
           continue   # equivalence proven in Correction 2 above
       prevalidated.append(pre)

   # Identical ordering to select_candidate's get_sort_key (updater.py:197-200),
   # descending, so the first valid hit is exactly the candidate select_candidate
   # would have chosen from the full validated set.
   prevalidated.sort(
       key=lambda p: (p.version.major, p.version.minor, p.version.patch,
                      not p.version.is_dev, p.published_at),
       reverse=True,
   )

   candidates: list[UpdateCandidate] = []
   attempts = 0
   for pre in prevalidated:
       if attempts >= MAX_MANIFEST_FETCH_ATTEMPTS:
           self._log("warning",
                     f"Update check stopped after {MAX_MANIFEST_FETCH_ATTEMPTS} manifest validation attempts without a valid candidate")
           break
       attempts += 1
       c = validate_prevalidated_candidate(pre, self._client)
       if c:
           candidates.append(c)
           break
   ```

   Then `select_candidate(candidates, current_version, preferred_channel)` is
   called **unchanged** (`updater.py:543-546`) — it receives a 0- or 1-element
   list and still owns all upgrade/`action` decisions (`update`,
   `move_to_stable`, `downgrade_to_stable`). Everything after (result building,
   caching, logging) stays as is; update the "Parsed N valid candidate releases"
   log line (`updater.py:538-541`) to report prevalidated count and attempts used,
   e.g. `f"Prevalidated {len(prevalidated)} releases, manifest attempts={attempts}, valid={len(candidates)}"`.

5. **Module-level constant** near the top of `updater.py` (next to
   `_PENDING_INSTALL_MISMATCH_GRACE`):

   ```python
   MAX_MANIFEST_FETCH_ATTEMPTS = 5
   ```

6. **`PrevalidatedRelease`** — a frozen dataclass in `updater.py` (it is an
   internal pipeline type, not a wire model, so it does not belong in
   `updater_models.py`):

   ```python
   @dataclass(frozen=True)
   class PrevalidatedRelease:
       record: Mapping[str, object]      # the original release JSON mapping
       tag_name: str
       version: ParsedPluginVersion      # parsed from tag_name[1:]
       published_at: str                 # str(record.get("published_at", ""))
       prerelease: bool                  # bool(record.get("prerelease", False))
       manifest_asset: Mapping[str, object]
       zip_asset: Mapping[str, object]
   ```

   Add `from dataclasses import dataclass` to the imports. `ParsedPluginVersion`
   and `Mapping` are already imported.

**Deliberate, accepted behavior changes (document in commit message body):**
- If more than `MAX_MANIFEST_FETCH_ATTEMPTS` of the best-ranked prevalidated
  releases all fail manifest validation (broken/missing manifests), an older valid
  release that the old code would have found is no longer reachable and the check
  reports `current`. This is the intended cap; it self-heals on the next good
  release and prevents a string of malformed releases from recreating the old
  request storm.
- Manifest fetches that return 403/429 are still treated as "candidate invalid"
  (same as today — only `list_releases` has rate-limit cooldown handling). Do NOT
  add new rate-limit handling to manifest fetches; out of scope.

**Explicitly out of scope for Part A:** `revalidate()`, `GitHubReleaseClient`,
caching/cooldown logic, any frontend code.

### Part B: backend TTL on Syncthing watches

File: `py_modules/sdh_ludusavi/syncthing/watcher.py` only. No frontend change, no
`service.py` change.

1. **Constant**, next to the existing grace constants (`watcher.py:41-45`):

   ```python
   # Frontend enforces MAX_WATCH_DURATION_MS = 120_000 (syncthingMonitor.ts);
   # backend TTL = frontend cap + 60s margin so well-behaved clients never hit it.
   WATCH_TTL_SECONDS = 180.0
   ```

2. **`SyncthingWatch.__init__`** (`watcher.py:61-91`): add an optional deregister
   callback parameter and a monotonic deadline. Keep `started_at` untouched.

   ```python
   def __init__(
       self,
       watch_id: str,
       phase: str,
       game_name: str | None,
       app_id: str | None,
       folder: FolderSelection,
       api: SyncthingAPI,
       initial_snapshot: ConnectionSnapshot | None = None,
       on_expired: Callable[[str], None] | None = None,
   ) -> None:
       ...
       self.deadline_monotonic = time.monotonic() + WATCH_TTL_SECONDS
       self._on_expired = on_expired
   ```

   Add `Callable` to the `typing` import at `watcher.py:7`.

3. **`SyncthingWatch._run`** (`watcher.py:122-123`): replace the loop body

   ```python
   while not self.stop_event.is_set():
       self._tick(time.monotonic())
   ```

   with a deadline check at the top of each iteration:

   ```python
   while not self.stop_event.is_set():
       if time.monotonic() >= self.deadline_monotonic:
           logger.warning(
           "Syncthing watch %s exceeded %ss TTL without stop_watch; self-terminating (phase=%s)",
               self.watch_id, WATCH_TTL_SECONDS, self.phase,
           )
           self.latest_sample = {
               "status": "stopped",
               "watch_id": self.watch_id,
               "reason": "watch_ttl_expired",
           }
           self.stop_event.set()
           if self._on_expired is not None:
               self._on_expired(self.watch_id)
           return
       self._tick(time.monotonic())
   ```

   Rules the implementer must respect:
   - Deregister **only** on TTL expiry. Do NOT call `_on_expired` from the
     init-failure early return (`watcher.py:110-117`) or from the
     `no_connected_peers` terminal path (`watcher.py:133-146`): those watches must
     stay registered so `poll_watch` can deliver their terminal `failed` sample to
     the frontend (existing behavior, covered by existing tests).
   - `{"status": "stopped"}` (not `"failed"`) for TTL: it matches what
     `poll_watch` already returns for an unknown watch (`watcher.py:380`), and the
     frontend treats any non-`activity` status as a clean backend stop
     (`syncthingMonitor.ts:510-513`).

4. **`SyncthingWatchManager`**: pass the callback and add the deregistration
   method.

   In `start_watch` (`watcher.py:358-360`):

   ```python
   watch = SyncthingWatch(
       watch_id, phase, game_name, app_id, folder, api,
       initial_snapshot=snapshot,
       on_expired=self._deregister_expired_watch,
   )
   ```

   New method on the manager:

   ```python
   def _deregister_expired_watch(self, watch_id: str) -> None:
       with self.lock:
           self.watches.pop(watch_id, None)
   ```

   **Lock-ordering note (leave a short comment in the code):** `stop_watch` holds
   `self.lock` while calling `watch.stop()`, which joins the thread with
   `timeout=1.0` (`watcher.py:99-102`). If a TTL expiry races a `stop_watch`, the
   watch thread can block briefly acquiring `self.lock` inside
   `_deregister_expired_watch`; the join times out after ≤1 s, `stop_watch` pops
   and releases the lock, and the thread's `pop(..., None)` is then a harmless
   no-op. There is no deadlock because the join has a timeout — do NOT "fix" this
   by removing the join timeout or by mutating `self.watches` without the lock.

**Explicitly out of scope for Part B:** any change to `MAX_WATCH_DURATION_MS`,
`syncthingMonitor.ts`, poll cadence, `_tick` internals, or `stop_all`.

---

## Core Data Structures

- `PrevalidatedRelease` (new, frozen dataclass, `updater.py`) — fields listed above.
- `MAX_MANIFEST_FETCH_ATTEMPTS = 5` (new constant, `updater.py`).
- `WATCH_TTL_SECONDS = 180.0` (new constant, `watcher.py`).
- `SyncthingWatch.deadline_monotonic: float`, `SyncthingWatch._on_expired:
  Callable[[str], None] | None` (new attributes).

## Public Interfaces

Unchanged: `validate_release_candidate(release, client)` signature/behavior,
`select_candidate(...)`, `PluginUpdater.check_for_update(...)` RPC payloads,
`SyncthingWatchManager.start_watch/poll_watch/stop_watch/stop_all` signatures and
payloads. New additions are additive: two module functions and one dataclass in
`updater.py`; one optional keyword-only-by-position ctor param in `SyncthingWatch`
(default `None`, so existing direct constructions in tests keep working).

## Dependency Requirements

None. Standard library only (`dataclasses`, `time`, `threading`, `typing`). Do not
touch `pyproject.toml` or `uv.lock`.

---

## Testing Strategy (strict TDD — write each test, see it FAIL, then implement)

All tests run via `./run.sh uv run pytest`. Mock-client patterns to copy are in
`tests/test_updater.py` (e.g. `MockClient` at `:331-345`, which records
`get_manifest` calls) and `tests/test_watcher.py` (module-function patching for
`get_initial_folder_state_and_runtime`/`get_event_cursor`, direct `_run`/`_tick`
invocation — see `test_strict_folder_status_initialization_failure` at `:387` and
`test_watch_stops_when_final_relevant_peer_disconnects` at `:561`).

### Part A tests — add to `tests/test_updater.py` (or a new `tests/test_updater_lazy.py` if `test_updater.py` grows unwieldy)

Build a helper that fabricates a release dict with a given tag, `published_at`,
`prerelease`, and a correctly named manifest asset + one zip asset, and a mock
client whose `get_manifest` counts calls per URL and returns a valid manifest for
chosen tags and garbage for others. Then:

1. `test_check_for_update_fetches_one_manifest_when_newest_is_valid` — 10 releases,
   all prevalidatable, newest (by version) valid → result `available` with the
   newest tag; `get_manifest` called exactly **once**; `list_releases` once.
2. `test_check_for_update_falls_through_invalid_manifests` — newest release's
   manifest is garbage, second-newest valid → second-newest selected;
   `get_manifest` called exactly twice, newest first (assert call order).
3. `test_check_for_update_caps_manifest_attempts_at_five` — 6 releases with
   broken manifests ranked above 1 valid older release → result `current`
   (the valid one is never reached); `get_manifest` called exactly 5 times.
4. `test_check_for_update_orders_by_version_not_published_at` — release `v1.9.1`
   with `published_at` **later** than release `v2.0.0`; both valid → `v2.0.0`
   selected and its manifest fetched first. (This is the regression test for
   writeup-correction #1.)
5. `test_check_for_update_stable_channel_skips_prereleases_without_fetch` —
   channel `stable`; newest release is a prerelease (`prerelease: True`, `-dev.`
   tag) above a valid stable release → stable release selected; the prerelease's
   manifest URL never fetched.
6. `test_prevalidate_rejects_free_failures_without_fetch` — drafts, bad tag
   shapes, missing/duplicated manifest assets, zero/multiple zip assets all yield
   `prevalidate_release_candidate(...) is None` and zero `get_manifest` calls in a
   full `check_for_update` pass.
7. Existing tests (`test_validate_release_candidate*`, `test_check_for_update`,
   `test_revalidate_install_candidate`, `test_malformed_github_payloads`, etc.)
   must pass **unmodified** — they pin the composition function's behavior.

Note for tests 1-5: `check_for_update` consults a 24 h result cache
(`updater.py:426-449`) — either pass `force=True` or use a fresh `PluginUpdater`
per test, as the existing `test_check_for_update` does.

### Part B tests — add to `tests/test_watcher.py`

Keep tests deterministic: never sleep-and-hope; force the deadline into the past
and call `_run` (with the activity module functions patched as existing tests do)
or `_tick` directly on the calling thread.

1. `test_watch_self_terminates_after_ttl` — construct a `SyncthingWatch` with a
   recording `on_expired` callback, patch
   `get_initial_folder_state_and_runtime`/`get_event_cursor` to no-ops, set
   `watch.deadline_monotonic = time.monotonic() - 1`, call `watch._run()` directly.
   Assert: it returns (does not loop), `stop_event.is_set()`,
   `latest_sample == {"status": "stopped", "watch_id": ..., "reason": "watch_ttl_expired"}`,
   and the callback was called exactly once with the watch id.
2. `test_manager_poll_returns_stopped_after_ttl_deregistration` — start a watch
   through `SyncthingWatchManager.start_watch` with the existing mock fixtures,
   stop its thread, force `deadline_monotonic` into the past, run `watch._run()`
   synchronously (or invoke `_deregister_expired_watch` via the watch's callback),
   then assert `watch_id not in manager.watches` and
   `manager.poll_watch(watch_id) == {"status": "stopped", "watch_id": watch_id}`.
3. `test_watch_within_ttl_does_not_expire` — deadline in the future, run a couple
   of `_tick` iterations (existing pattern), assert `stop_event` not set, callback
   never called, watch still registered.
4. `test_no_connected_peers_terminal_watch_stays_registered` — regression guard:
   the peers-disconnected terminal path (`watcher.py:133-146`) must NOT trigger
   `on_expired`; the watch stays in `manager.watches` so its `failed` sample
   remains pollable. (Extend or mirror
   `test_watch_stops_when_final_relevant_peer_disconnects`.)
5. `test_watch_ttl_exceeds_frontend_cap` — assert
   `WATCH_TTL_SECONDS >= 120 + 30` (sanity-pins the "frontend cap + margin"
   relationship without hardcoding the exact margin).
6. Existing watcher tests construct `SyncthingWatch` without `on_expired` — they
   must pass unmodified (the param defaults to `None`).

---

## Step-by-Step Execution Order (for the implementer skill)

0. Protocol handshake (`pwd`, `ls`, `git status`, inspect `pyproject.toml`); confirm
   clean tree; `./run.sh uv run pytest` must be green before starting.
1. **Part A RED:** write Part A tests; run `./run.sh uv run pytest tests/test_updater.py`
   (and the new file if created); confirm the new tests FAIL for the expected
   reason (e.g. `get_manifest` call counts too high, `prevalidate_release_candidate`
   missing).
2. **Part A GREEN:** implement `PrevalidatedRelease`, `MAX_MANIFEST_FETCH_ATTEMPTS`,
   `prevalidate_release_candidate`, `validate_prevalidated_candidate`, recompose
   `validate_release_candidate`, rewrite the `check_for_update` candidate loop.
   Run the full suite.
3. **Part A REFACTOR + gates:** `./run.sh uv run ruff check . --fix`,
   `./run.sh uv run ruff format .` (targeted at touched files if unrelated dirty
   files exist), `./run.sh uv run ty check py_modules/sdh_ludusavi/`,
   `./run.sh uv run pytest`.
4. **Commit Part A:**
   `perf(updater): validate release manifests lazily, newest candidate first`
   — body must note the 5-attempt cap and the accepted behavior change.
5. **Part B RED:** write Part B tests; confirm they fail (no `WATCH_TTL_SECONDS`,
   no `on_expired`, loop never exits).
6. **Part B GREEN:** implement constant, ctor changes, `_run` deadline check,
   manager callback wiring, `_deregister_expired_watch`. Run the full suite.
7. **Part B REFACTOR + gates:** same four gate commands as step 3.
8. **Commit Part B:**
   `feat(syncthing): self-terminate watch threads after 180s backend TTL`
   — body must mention the frontend 120 s cap + margin rationale and the
   deregister-on-expiry-only rule.
9. **Docs:** README needs no change (no user-facing behavior/usage change — verify
   this judgment by skimming README's updater/Syncthing sections; if either
   documents request counts or watch lifetimes, update it). Write the session log
   `docs/agent_conversations/2026-06-11_updater_laziness_watch_ttl.md` (date, task
   objective, files modified, tests added, design decisions — include corrections
   #1/#2 above — results). Haiku may draft this log. Commit:
   `docs: agent session log for updater laziness and watch TTL`.
10. Definition of Done checklist from `CLAUDE.md` §16; confirm `git status` shows
    no generated artifacts and no unrelated files staged.

## Risks / Things a careless implementer will get wrong

- Sorting by `published_at` instead of the full version sort key (changes selection).
- Filtering stable channel by tag `-dev` suffix instead of the `prerelease` flag
  (the proven-equivalent proxy is `prerelease`; see Correction 2).
- Breaking `revalidate()` by changing `validate_release_candidate`'s signature or
  behavior instead of recomposing it.
- Counting attempts only on failures (the cap is on **fetches**, i.e. increments
  before each `validate_prevalidated_candidate` call).
- Calling `_on_expired` on every thread exit (breaks the `no_connected_peers` and
  init-failure terminal-sample contract).
- Using `time.time()` for the TTL deadline.
- Mutating `manager.watches` without `manager.lock`, or removing the
  `thread.join(timeout=1.0)` timeout while "fixing" the benign lock race.
- Sleeping in tests instead of forcing `deadline_monotonic` into the past.
- Running tooling without `./run.sh` (caches land inside Dropbox).
