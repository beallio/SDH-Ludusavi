# Flatpak User Install Discovery

## Problem Definition

Runtime testing still reports that the Ludusavi Flatpak cannot be found. The backend
constructs `pyludusavi.Ludusavi(flatpak_id="com.github.mtkennerly.ludusavi")`, but
discovery only validates plain `flatpak run` candidates in the backend process
environment. If Ludusavi is installed as the Steam Deck user Flatpak and Decky's backend
has a different `HOME` or sparse environment, the app can remain invisible.

## Architecture Overview

Keep Ludusavi command discovery inside the vendored `pyludusavi` layer. Extend
`pyludusavi.Ludusavi` and `find_ludusavi()` with an optional `flatpak_user_home` value.
When present, discovery should try `flatpak run --user` candidates under that user home
before falling back to system/default Flatpak candidates. The SDH adapter should pass
Decky's user home to `pyludusavi` when Decky exposes it.

## Core Data Structures

- Ludusavi command prefix: still a list of command arguments, now allowed to include a
  leading `/usr/bin/env HOME=... XDG_DATA_HOME=... FLATPAK_USER_DIR=...` wrapper for
  user Flatpak discovery.
- Ludusavi client command prefix: used as the source of truth for rclone probing.

## Public Interfaces

No Decky frontend callable names or payloads change. The vendored Python API gains an
optional `flatpak_user_home` constructor argument for `pyludusavi.Ludusavi`; existing
callers remain compatible.

## Dependency Requirements

No new dependencies. Flatpak user-mode behavior uses the existing Flatpak CLI and
standard environment variables.

## Testing Strategy

Add red tests proving user-home Flatpak discovery prefers `flatpak run --user` with a
Decky-user environment, the SDH adapter passes Decky's user home into `pyludusavi`, and
rclone version probing reuses `pyludusavi`'s discovered command prefix instead of
performing separate Flatpak lookup.
