# Duplicate Backend Instances After Self-Update

## Problem Definition

After the 2026-06-12 self-update (f409b35 → newer dev build), two backend
processes remained alive indefinitely:

```
6270  1330  57:13  SDH-Ludusavi (/home/deck/homebrew/plugins/SDH-Ludusavi/main.py)
6278  1330  57:12  SDH-Ludusavi (/home/deck/homebrew/plugins/SDH-Ludusavi/main.py)
```

Decky journal evidence (v3.2.4, 17:35:55–56): after `browser._install`
re-enabled the file watcher, the zip-extraction file events triggered a
hot-reload storm — nine stop/start cycles in ~2 seconds — because the shipped
`plugin.json` carries the `debug` flag. Non-debug plugins skip
watchdog-triggered reloads entirely ("requested to not be re-loaded").

Under the storm, two concurrent `import_plugin` callers raced. Decky's
`import_plugin` has an `await context.utilities.get_setting("disabled_plugins")`
between entry and the duplicate check, and an `await stop()` inside the
incumbent branch, so two tasks can both reach
`self.plugins[name] = plugin.start()`. The second dict insert overwrites the
first wrapper: PID 6270 got "Loaded" but never "Shutting down" — orphaned
forever, while Decky owns only 6278.

Secondary observation (not fixed here): the mature pre-update instance needed
Decky's 5s SIGKILL backstop ("still alive 5 seconds after stop request"), i.e.
our unload path exceeds 5s; covered by Decky's backstop, tracked separately.

## Architecture Overview

Two independent defenses:

1. **Stop shipping the `debug` flag in release zips.**
   `scripts/package_plugin.py` already rewrites `plugin.json` inside the
   archive; for `--release` builds it now drops `debug` from `flags`. This
   removes the post-install reload storm — and with it the race trigger — for
   all updater-installed builds (stable + dev releases). Local non-release
   builds keep the flag because the push-to-deck dev loop relies on watchdog
   hot-reload.

2. **Startup singleton guard (`py_modules/sdh_ludusavi/singleton.py`).**
   On `_main`, the new backend scans `/proc` for strictly-older sibling
   instances — same uid, byte-identical `/proc/<pid>/cmdline` (Decky's
   setproctitle gives every instance of this plugin the same title) — and
   terminates them: SIGTERM, bounded wait, SIGKILL. The youngest instance is
   always the one Decky owns (last dict insert wins), so "newest survives" is
   the correct policy. This also cleans up already-leaked instances from prior
   upgrades on the next plugin start.

## Core Data Structures

- `SiblingProcess`: pid, start ticks (field 22 of `/proc/<pid>/stat`).
- Guard report dict: `{"status", "terminated", "killed", "skipped"}` for logs.

## Public Interfaces

- `singleton.find_stale_sibling_pids(proc_root, pid) -> list[int]`
- `singleton.terminate_stale_siblings(pids, *, kill_fn, sleep_fn, proc_root,
  term_timeout) -> dict`
- `singleton.enforce_single_instance(logger, *, proc_root, ...) -> dict` —
  never raises; called from `Plugin._main` before service startup via the
  RPC executor.

Safety constraints: only pids > 1, only strictly older (start ticks, pid)
than self, byte-identical cmdline, same uid, per-pid exception isolation.

## Dependency Requirements

Stdlib only (`os`, `signal`, `pathlib`, `time`). No new packages.

## Testing Strategy

- `tests/test_singleton.py` (RED first): fake `/proc` trees under `tmp_path`
  exercising match/ignore rules, ordering, signal escalation, and error
  isolation with injected `kill_fn`/`sleep_fn`.
- `tests/test_main.py`: `_main` invokes the guard before service startup.
- `tests/test_package_plugin.py`: release zips strip `debug` from
  `plugin.json` flags; local builds keep it.
