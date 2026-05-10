# SDH-ludusavi Version Display

## Problem Definition

The Decky frontend already shows Ludusavi and rclone versions, but it does not
show the SDH-ludusavi plugin version. Release archives also do not validate that
the Decky plugin metadata and frontend package metadata agree on the release
version.

## Architecture Overview

Expose the plugin version from the Python backend as `sdh_ludusavi` in the
existing `get_versions()` payload. Keep external tool version lookup in the
adapter and add the plugin version at the service boundary so UI consumers have
one backend call for all version rows.

Version resolution will prefer Python package metadata only when it represents a
VCS development version, such as `0.1.dev104+...`. Packaged release builds will
read JSON metadata from `plugin.json` and `package.json`, which are included in
the Decky archive.

## Core Data Structures

- `Versions` frontend type gains optional `sdh_ludusavi`.
- Backend version payload gains `sdh_ludusavi: str`.
- Package metadata validation reads `plugin.json["version"]` and
  `package.json["version"]`.

## Public Interfaces

- `SDHLudusaviService.get_versions()` returns `sdh_ludusavi`, `ludusavi`, and
  `rclone` when external tools are available.
- The frontend `Versions` panel renders `SDH-ludusavi: <version>` above the
  Ludusavi and rclone rows.
- `scripts/package_plugin.py` fails before archive creation when JSON metadata
  versions are missing or mismatched.

## Dependency Requirements

No new runtime or development dependencies are required. Python metadata uses the
standard library `importlib.metadata`, and JSON metadata uses the standard
library `json` module.

## Testing Strategy

- Add resolver tests for development metadata precedence, release JSON
  precedence, and deterministic fallback behavior.
- Extend service tests to assert `sdh_ludusavi` is included in `get_versions()`.
- Extend frontend static tests to assert the type and row exist in the existing
  `Versions` panel.
- Extend package tests to assert `plugin.json` and `package.json` both carry
  matching `0.1.0` metadata, the archive includes both files with that metadata,
  and mismatched metadata is rejected.
