# Deck Screenshot Helper

## Problem Definition

Capturing the Steam Deck's current screen during plugin development is ad hoc.
The Deck runs a gamescope session, so the usual Wayland tools are unavailable:
`grim` is not installed and `spectacle` cannot attach to the gamescope
compositor. The working path is `gamescopectl screenshot <path>`, but it has two
sharp edges:

- it requires `XDG_RUNTIME_DIR=/run/user/1000` when invoked over SSH (the SSH
  session is a `tty` session, not the graphical one), and
- it returns exit code 0 immediately and writes the PNG asynchronously, so a
  naive `ssh ... && scp ...` races and reports a missing file.

A helper script should encapsulate the remote invocation, the wait-for-file
poll, the copy back, and remote cleanup.

## Architecture Overview

A single Bash script, `scripts/deck_screenshot.sh`, in the same style as
`scripts/post_commit.sh`:

1. Resolve the output path (positional arg, default
   `out/deck-screenshot-<UTC timestamp>.png`).
2. Probe reachability with `ssh -q -o BatchMode=yes -o ConnectTimeout=<n>
   <host> exit`; exit non-zero with a clear message when the Deck is offline.
3. Run `gamescopectl screenshot <remote tmp path>` with `XDG_RUNTIME_DIR` set.
4. Poll the remote path until the file exists and its size is stable between
   two samples, bounded by a timeout, so a partially written PNG is never
   copied.
5. `scp` the file back, then `rm -f` the remote temp file.
6. Print the local path on stdout as the last line so callers can capture it.

No Python, no new dependencies: this is operator tooling that must run even when
the project virtualenv is absent, so it is invoked directly rather than through
`./run.sh`.

## Core Data Structures

None. Configuration is environment variables with defaults:

- `DECK_HOST` (default `steamdeck`) — SSH host alias.
- `DECK_UID` (default `1000`) — used to build `XDG_RUNTIME_DIR`.
- `DECK_SCREENSHOT_TIMEOUT` (default `15`) — seconds to wait for the PNG.
- `DECK_SSH_CONNECT_TIMEOUT` (default `5`) — SSH connect timeout for the probe.

## Public Interfaces

```
scripts/deck_screenshot.sh [output_path]
```

Exit codes: `0` success, `1` Deck unreachable or capture timed out.
Stdout: progress lines plus the final local path.

## Dependency Requirements

Host: `bash`, `ssh`, `scp` (already required by `scripts/post_commit.sh`).
Deck: `gamescopectl` (ships with SteamOS in Game Mode).

## Testing Strategy

`tests/test_deck_screenshot.py` drives the real script with a stub `ssh`/`scp`
pair injected on `PATH`, so no Deck is needed on CI:

- unreachable Deck (stub `ssh ... exit` fails) → non-zero exit, message names
  the host, no `scp` attempted;
- happy path where the stub creates the "remote" file only on the second poll →
  exit 0, local file present, remote cleanup command issued;
- capture never appears → non-zero exit before the copy, bounded by
  `DECK_SCREENSHOT_TIMEOUT`;
- the `gamescopectl` invocation carries `XDG_RUNTIME_DIR=/run/user/<uid>`;
- `DECK_HOST` override is honoured.

A static check asserts the script is executable and uses `set -euo pipefail`,
matching the conventions of the other scripts in `scripts/`.
