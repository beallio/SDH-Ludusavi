# Load/Unload Lifecycle Review 01

Date: 2026-08-25
Scope: read-only review. Findings were re-verified against the source and the
live device on 2026-08-25; F1 and F3 did not survive that check and are marked
RETRACTED in place. The source-level claims were then re-checked independently by
codex (see "Independent verification" below), which corrected four of them and
added F10-F12. Evidence is the live Deck plugin logs at
`/home/deck/homebrew/logs/SDH-Ludusavi` covering 2026-08-19 through 2026-08-25
(660 lines across five sessions), cross-read against `main.py`,
`py_modules/sdh_ludusavi/{gateway,registry,service,log_buffer}.py`,
`src/index.tsx`, `src/runtime/pluginRuntime.ts`,
`src/surfaces/autoSyncStatus{Surface,BrowserView}.*`,
`src/controllers/{gameLifecycleController,syncthingMonitor}.*`.

No files were modified.

---

## Summary of evidence

Every lifecycle pairing in the logs is unbalanced:

| event | count | paired event | count |
|---|---|---|---|
| `plugin_initializing` | 7 | `plugin_dismounting` | 2 |
| `lifecycle_source_started` | 7 | `lifecycle_source_disposed` | 2 |
| `qam_opened` | 9 | `qam_closed` | 4 |
| `qam_content_mounted` | 4 | `qam_content_unmounted` | 5 |
| `backend loaded` | 5 | `backend unloaded` | 3 |
| `Unload started` | 4 | `Unload ended` | 3 |

Noise accounting for the same 660 lines: 56 lines (8.5%) are
`refresh: Coercing status for X`, 40 lines (6%) are
`Task was destroyed but it is pending!` plus its `task:` continuation. Roughly
one line in seven carries no information.

---

## Findings

### F1. RETRACTED (partly on withdrawn reasoning) — the truncated unload is the update path

Originally filed as "an unload can be abandoned mid-flight, leaving launch gates
held." Verification on 2026-08-25 does not support that. What is true:

- `2026-08-23 15.11.35.log` really does lack `Unload ended`, and also lacks
  `Stopping event loop` — the other three sessions have both. That process was
  killed rather than shut down.
- `backend.stop()` really did run and reach `gateway.shutdown()`. Proven by the
  `backup path: unknown` line at 15:11:36,225: `executor.shutdown()` sets
  `_shutdown = True`, `_raise_if_shutdown()` then raises
  `LudusaviOperationCancelledError`, which subclasses `LudusaviError`
  (`ludusavi_executor.py:38`) and is swallowed by `get_diagnostics`'s
  `except (LudusaviError, KeyError, TypeError, ValueError): pass`, leaving
  `backup_path = "unknown"`.

What is **not** true:

- **No launch gate was held.** No game was running in that session, and there are
  no SIGSTOPped processes on the device. The mechanism exists; it never fired.
- **No launch gate was held** (repeated: this is the empirical finding that
  carries the retraction).

An earlier version of this retraction also argued "this was not a timeout,
because every wait inside `stop()` is bounded to low single-digit seconds, so
107 ms cannot be a deadline expiring." **That argument is invalid** and is
withdrawn — see F7 below. `service.stop()` has no global timer that kills the
Python backend at all; its executor timeouts kill Ludusavi subprocess groups.
A maximum is not a minimum, so 107 ms is equally consistent with a fast normal
teardown and with an external Decky deadline. The constants cannot distinguish
them.
- The kill is the plugin-update path, which `main.py` explicitly anticipates: the
  `DaemonThreadPool` comment states an in-flight RPC "must never keep the old
  plugin process alive after Decky's SystemExit during update/unload."

What still supports the retraction is empirical, not arithmetic: nothing was
held, no game was running, and a plugin update was in flight at that moment.

No action on the original "abandoned unload" framing. But see F10–F12, which are
genuine teardown defects found while re-verifying this one.

### F2. Untracked daemon thread in the gateway (downgraded)

`gateway.py:82` — `_log_ludusavi_diagnostics` fires a bare
`threading.Thread(target=run, daemon=True).start()`, not stored, not joined.

The original claim that this thread caused a hang is **wrong**: it completed at
15:11:36,225, 48 ms after `Unload started`, cancelled cleanly through the
mechanism described in F1. It blocked nothing.

What remains is real: `invalidate()` (`gateway.py:39`) resets
`_diagnostics_logged = False`, and `registry.py:151` calls `invalidate()` on
every forced refresh, so the probe re-runs per manual refresh. Visible in
`2026-08-24 21.34.15.log` at 21:34:17 and again at 21:34:21 for information that
had not changed.

The cost is larger than first stated. On a fresh adapter `ludusavi.py:437` runs
version discovery, config-path discovery, and `config_show()` — up to three
managed `flatpak run` subprocesses — and adapter construction verifies the
flatpak with a further `--version` call. Not one ~700 ms invocation.

**Fix.** Decouple diagnostics logging from cache invalidation — `invalidate()`
should drop the cached adapter without re-arming the log. See also F12, which
concerns the same function.

### F3. RETRACTED — `Task was destroyed` is a decky-wide teardown pattern

40 lines across the corpus, all naming `WSRouter._call_route()`, timed to
teardown. Originally attributed to this plugin's executor shutdown.

`SDH-PlayTime` and `Decky-Metadata` logs on the same device contain the same
message. It is not specific to this plugin, and `WSRouter` is decky's code, not
ours. Whether the pending routes are this plugin's RPC methods was not
established.

The one observation worth keeping: these are the only ERROR-level lines in 660
lines of this plugin's logs, so the ERROR channel carries no signal of its own.
That is a reason to be careful reading it, not a defect to fix here.

### F4. A native BrowserView is created just to service a no-op hide (wasted work, not a leak)

`autoSyncStatusBrowserView.ts` — `sync()` calls
`ensureAutoSyncStatusBrowserView()` as its first statement, *before* the
`if (!state.visible)` early return. And `autoSyncStatusSurface.tsx:239` —
`hide()` calls `statusView.sync()` unconditionally.

Observed on 2026-08-25 for a game the plugin had already decided to skip:

```
08:49:09,171  Status update: source=hide status=has_backup visible=false
              game=Brotato tracked=false result=skipped
08:49:09,174  Creating BrowserView via GamepadUIMainWindowInstance
08:49:09,175  BrowserView created: type=object
08:49:09,176  BrowserView normalized from m_browserView
```

Nothing was ever shown. The view is destroyed only in `statusView.destroy()`,
reached only via `runtime.dispose()`, reached only via `onDismount` — which per
the table above runs on roughly 2 of every 7 teardowns.

The original filing claimed each skipped `onDismount` therefore orphans a native
BrowserView. **Checked on 2026-08-25 and not supported.** Steam's CEF debugger
(`http://localhost:8080/json/list`) lists exactly one bare `about:blank` target,
and its DOM is `<div id="test_css_loaded">` — CSS Loader's, not ours. Steam's own
views (`MainMenu_uid2`, `QuickAccess_uid2`, `notificationtoasts_uid2`) all
enumerate normally, so ours would be expected to appear if it were alive. One was
created at 08:49:09 that morning and left no trace ~75 minutes later, so Steam
appears to reap it.

Caveats: it is not established that `CreateBrowserView` views always enumerate as
CDP targets, and the number of intervening UI reloads is unknown. There is no
accumulation, so this is wasted work per hide, not a leak.

**Fix.** Move the `!state.visible` check above `ensureAutoSyncStatusBrowserView()`
and return early when there is no view to hide. One-line reorder; removes the
wasted creation.

### F5. The post-game Syncthing watch ignores `tracked`; the pre-game one does not

`gameLifecycleController.tsx:351` gates the exit watch on
`autoSyncEnabledExit && !gameSyncDisabledExit`. The start path
(`:206`) gates on `autoSyncEnabled && !gameSyncDisabled && guardCandidate`,
where `guardCandidate = tracked || !isTrackingReady`. `tracked` is computed at
`:340`, three lines above the exit gate, and simply is not consulted.

The cost, from the Brotato exit at 08:50:02 — a game the backend rejected as
`unmatched_game` 4 ms later:

```
02,132  Syncthing watch allocated: generation=1 watch_id=null
02,134  Parsing Syncthing config using fallback regex XML parser
02,138  Skipped exit for Brotato: unmatched_game
02,144  Syncthing generation cancelled: reason=exit_handler_cleanup
02,147  Syncthing peer availability: phase=post_game configured=3 connected=3
02,151  Syncthing late watch allocation stopped: watch_id=9feb59d7-...
02,216  Syncthing peer completion started: phase=post_game ...
```

A config parse, three peer probes, and a full allocate/cancel/stop round trip —
~85 ms and three network calls — on every exit of every untracked game.

The teardown itself is correct; `allocateWatchBackground` handles the late
resolution properly. The waste is that the work is started at all.

The asymmetry only bites when tracking is ready. When `trackingReadiness` is not
`"ready"`, `guardCandidate` is true even for an untracked game, so both paths
allocate and the two behave identically. The Brotato trace above has
`tracking_readiness=ready`, which is why it diverged.

**Fix.** Add `&& guardCandidate` to the exit gate, matching the start path.
If post-game watching for untracked games is intentional, say so in a comment,
because the asymmetry currently reads as an oversight.

### F6. Every unlabelled log line is stamped `frontend:`, including backend lines

`log_buffer.py:95` — `log_msg = f"{operation or 'frontend'}: {message}"`.

So `frontend: Unload started`, `frontend: Startup reconciliation: ...`, and
`frontend: Tracked 13 game names/aliases` all come from Python. There is no way
to tell from a log line which side emitted it, which is the single biggest
obstacle to reading these files.

**Fix.** Default to `"backend"` in `log_buffer.log`, and have the frontend's
`Plugin.log` RPC pass `operation="frontend"` explicitly when the caller supplied
none. The RPC already receives the argument; only the default is wrong.

### F7. `_coerce_game_status` logs one DEBUG line per game, per call

`registry.py:280` logs inside a pure dict-to-dataclass mapper. It runs on cache
deserialization at startup (`registry.py:53`) and on an actual status refresh
(`registry.py:222`) — but **not** when `refresh_games()` takes its cached fast
path at `registry.py:138–149`, so "every refresh" overstates it. 9 games here,
56 lines across the corpus, 8.5% of total volume. It scales linearly with library size — a
200-game library emits 200 lines on every load and every refresh.

The lines carry no information; a failure would surface as an exception, not as
a missing line.

**Fix.** Delete it, or replace the whole loop with one
`Coerced N game statuses` line at the call site.

### F8. The update check reports itself twice in two vocabularies

From `2026-08-24 21.34.15.log`:

```
19,828  update:   check_start: trace_id=none, channel=development
19,829  update:   check_reuse: trace_id=none, channel=development, elapsed_ms=0
19,829  frontend: Update check started (version=0.4.6, force=False)
19,830  frontend: Update check cache hit (within 24h, ...), elapsed_ms=0
19,836  update:   check_success: trace_id=none, status=current, elapsed_ms=9
```

Two structured event streams — the `update:` trace-id events and the `frontend:`
prose events — narrate one cache hit. Both are useful designs; running both is
not.

**Fix.** Keep the `update:` trace-id stream (it carries correlation IDs) and
demote the prose duplicates to DEBUG.

### F9. Minor: dead call and misleading log text

- `autoSyncStatusSurface.tsx:227` (inside `hide()`, which begins at `:221`) —
  `statusView.setContext(currentAutoSyncStatusState)`
  is called immediately before `currentAutoSyncStatusState` is reassigned, then
  called again with the new value. The first call is dead.
- `syncthingMonitor.ts:136` logs `Syncthing watch allocated: ... watch_id=null`
  at the moment allocation is *requested*, and `:410` logs `Syncthing watch
  allocated:` again with the real ID. Two different events, same prefix. Rename
  the first to `watch requested`.
- `sdh_ludusavi.syncthing.config` logs `Parsing Syncthing config using fallback
  regex XML parser (ElementTree available: False)` at INFO on every parse — six
  times in the corpus. In the Decky runtime `ElementTree` is never available, so
  this is a constant, not an event. Log it once at startup.

---

### F10. Frontend teardown is fire-and-forget, with no backend admission gate

`index.tsx:286` calls `void lifecycleController.dispose()` and disposes the
runtime immediately after. The controller's `dispose()` awaits active lease
releases, but that promise is discarded. On the backend, `main.py:365` schedules
`stop()` through the same RPC pool, and there is no "unloading" admission flag
before the executor shutdown at `main.py:389`.

Failure scenario: frontend resume / stop-watch RPCs race backend unload, or queue
behind occupied workers. `stop()` takes its watch snapshot before a late
watch-start RPC completes, so that watch is created *after* `stop_all()` has run
and survives teardown.

**Fix.** Await `lifecycleController.dispose()` (or give it a bounded wait), and
have the backend reject new watch-start RPCs once unload has begun.

### F11. A retained launch gate also strands every Syncthing watcher thread

`service.py:180` — `stop()` returns early when `gateway.shutdown()` fails, and
returns again when `watchdog.stop()` fails. `_syncthing_watch_manager.stop_all()`
is only reached at `service.py:205`.

Failure scenario: one Ludusavi process refuses to reap, or one guarded callback
is still active. Retaining the launch gate in that situation is deliberate and
correct. Leaving every Syncthing watcher thread running is not — it buys no
fail-safe, and those threads outlive the teardown.

**Fix.** Move `stop_all()` above the early returns, or run it in a `finally`.
Watch cleanup is independent of gate retention.

### F12. `invalidate()` orphans the old adapter instead of shutting it down

`gateway.py:39` assigns `_adapter = None` without calling the outgoing adapter's
`shutdown()`.

Failure scenario: a forced refresh lands while the old adapter's diagnostics
thread is running a managed flatpak command. The gateway builds a replacement
adapter, and a later `service.stop()` shuts down only the replacement. The old
adapter's executor and its subprocess are outside the teardown chain entirely and
survive until their own timeout or process death.

This is the same function as F2 and should be fixed with it.

## Suggested sequencing

1. **F11 + F12** — teardown correctness. Both are small and both leave real
   resources running: stranded Syncthing threads on a retained gate, and an
   orphaned adapter plus subprocess on a forced refresh. Highest value here.
2. **F10** — the frontend/backend unload race. Larger than F11/F12 because it
   needs an admission flag on the backend, not just reordering.
3. **F4 + F5** — two small gating changes: one wasted native-view creation per
   hide, and ~85 ms plus three peer probes per exit of an untracked game while
   tracking is ready.
4. **F2** — decouple diagnostics logging from `invalidate()`; removes up to four
   redundant flatpak subprocesses per manual refresh. Do with F12.
5. **F6 + F7 + F8 + F9** — log hygiene, observability only. Worth doing before
   the next round of lifecycle debugging so the next set of logs is readable.

Items 1–4 change runtime behavior and need failing tests first per the project
TDD contract. F1 and F3 are retracted; no work follows from them.

## Independent verification (codex, 2026-08-25)

The eight source-level claims were re-checked by `codex exec -s read-only`
against commit `fa3aba8`. Results: F4, F6 (full chain), and F9 confirmed as
written. F5, F7, F2, and the `log_buffer` claim were partially corrected — those
corrections are folded into the findings above. The F1 retraction's *timing*
argument was refuted and is withdrawn in place; its empirical basis stands.
F10–F12 are codex's, found independently of the eight claims.

The correction worth naming: the claim that `config_show()` reaches the managed
executor — asserted here originally without tracing it — does hold
(`pyludusavi/main.py:119` calls `self.executor.execute`). But the failure is
timing-dependent rather than universal: version and config-path discovery must
complete before shutdown, with `config_show()` landing after, or the exception
escapes the `except` clause instead of being swallowed.

## Follow-up verification (2026-08-25)

Three items were originally left unverified. All three were checked.

- **Do the pending `WSRouter._call_route` tasks belong to this plugin?** Yes.
  `ps` on the device shows decky forking one process per plugin from loader PID
  63348, including `70778 SDH-Ludusavi (/home/deck/homebrew/plugins/SDH-Ludusavi/main.py)`.
  A `WSRouter` task written to this plugin's log runs in PID 70778 and can only
  dispatch to this plugin's methods. (`wsrouter.py` is not on disk; the loader is
  a PyInstaller bundle. The process model settles it without the source.)
- **Is the 7:2 init-to-dismount ratio entirely Steam UI reloads?** Yes, for the
  two re-inits without an intervening dismount. `Decky-Metadata` logged
  `steam patches installed attempts='2'` at 15:12:27,419 and `attempts='5'` at
  15:13:37,988 — about a second after this plugin's `plugin_initializing` at
  15:12:26,597 and 15:13:35,406. A second plugin re-patching at the same moments
  means the shared UI context reloaded. Duplicate `steam_notifications`
  subscriptions are therefore **not** a bug.
- **Does the BrowserView leak?** No evidence that it does. See F4, updated in
  place.

Tooling note: the device has neither `websocket-client` nor `websockets`, so the
CDP query used a small raw-frame WebSocket client pushed to `/tmp/cdp.py`.
