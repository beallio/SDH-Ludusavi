# Plan: Sync pyludusavi to v0.2.3 env support

## Problem Definition
SDH-ludusavi currently vendors `pyludusavi==0.2.2` and wraps the client's
executor to inject subprocess environment values. `pyludusavi==0.2.3` adds a
first-class `env` constructor argument, so the plugin should use that upstream
API and remove the local executor proxy.

## Architecture Overview
The plugin continues to vendor `pyludusavi` under `py_modules/` for Decky
runtime imports. `PyludusaviAdapter` owns the SDH-specific environment override
map and passes it directly to `pyludusavi.Ludusavi(flatpak_id=..., env=...)`.
Direct launcher discovery uses the same helper so Flatpak verification sees the
same environment.

## Core Data Structures
- `_ludusavi_env()`: returns an environment override map for Ludusavi subprocess
  calls without mutating `os.environ`.
- Vendored package directories:
  - `py_modules/pyludusavi/`
  - `py_modules/pyludusavi-0.2.3.dist-info/`

## Public Interfaces
- `PyludusaviAdapter()` keeps the same service-facing behavior while
  constructing `Ludusavi(flatpak_id=FLATPAK_ID, env=_ludusavi_env())`.
- `SDHLudusaviService.get_ludusavi_command()` calls
  `find_ludusavi(explicit_flatpak_id=FLATPAK_ID, env=_ludusavi_env())`.
- Plugin packaging includes `py_modules/pyludusavi-0.2.3.dist-info/`.

## Dependency Requirements
Update `pyproject.toml`, `uv.lock`, and vendored runtime files to
`pyludusavi==0.2.3`. Use the clean upstream wheel contents; do not patch files
inside `py_modules/pyludusavi/**`.

## Testing Strategy
Red tests first assert:
- `pyludusavi.__version__ == "0.2.3"`.
- `PyludusaviAdapter` passes `flatpak_id` and `env` to the upstream
  constructor.
- `_ludusavi_env()` adds `XDG_RUNTIME_DIR=/run/user/1000` when absent, clears
  `LD_LIBRARY_PATH` with an empty override when present, and leaves
  `os.environ` unchanged.
- Launcher discovery passes the same env override map.
- Packaging and protocol tests reference `pyludusavi-0.2.3.dist-info`.

Validation commands:
- `./run.sh uv run ruff check . --fix`
- `./run.sh uv run ruff format .`
- `./run.sh uv run ty check py_modules/sdh_ludusavi/`
- `./run.sh uv run pytest`
- `pnpm run verify`
- `./run.sh uv run python scripts/package_plugin.py`
