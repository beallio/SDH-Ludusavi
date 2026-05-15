# Plan: Sync pyludusavi to v0.2.2

## Problem Definition
SDH-ludusavi vendors `pyludusavi` under `py_modules/` so Decky can import it at
runtime without installing site packages. The vendored copy was `0.2.1` and
included SDH-specific edits inside upstream package files. The requested change
is to replace that vendor tree with the clean upstream `pyludusavi==0.2.2`
wheel and keep any SDH-specific behavior in first-party `sdh_ludusavi` code.

## Architecture Overview
The plugin continues to use `py_modules/pyludusavi/` as a runtime-vendored
third-party package and `py_modules/sdh_ludusavi/` as first-party backend code.
`PyludusaviAdapter` constructs upstream `pyludusavi.Ludusavi` with only the
upstream `flatpak_id` argument. SDH-specific subprocess environment handling is
applied by wrapping the constructed client's executor from first-party code.

## Core Data Structures
- `LudusaviExecutorEnvironment`: first-party proxy around a pyludusavi executor
  that injects an environment with `LD_LIBRARY_PATH=""` into each execution.
- Vendored package directories:
  - `py_modules/pyludusavi/`
  - `py_modules/pyludusavi-0.2.2.dist-info/`

## Public Interfaces
- `PyludusaviAdapter()` keeps the same service-facing behavior while using the
  clean upstream constructor: `Ludusavi(flatpak_id=FLATPAK_ID)`.
- `SDHLudusaviService.get_ludusavi_command()` uses upstream discovery with
  `find_ludusavi(explicit_flatpak_id=FLATPAK_ID)`.
- Plugin packaging includes `py_modules/pyludusavi-0.2.2.dist-info/`.

## Dependency Requirements
`pyproject.toml` and `uv.lock` already require and lock `pyludusavi==0.2.2`.
The vendored runtime files are copied from the resolved environment under
`/tmp/sdh_ludusavi/.venv` so no manual edits are made inside
`py_modules/pyludusavi/**`.

## Testing Strategy
Red tests first assert:
- `pyludusavi.__version__ == "0.2.2"`.
- Upstream discovery exposes only the clean `find_ludusavi` signature and no
  local patch helpers such as `_should_sudo` or `_flatpak_user_env`.
- `PyludusaviAdapter` passes only upstream-supported constructor arguments.
- SDH-owned executor wrapping injects `LD_LIBRARY_PATH=""`.
- Packaging and protocol tests reference `pyludusavi-0.2.2.dist-info`.

Validation commands:
- `./run.sh uv run ruff check . --fix`
- `./run.sh uv run ruff format .`
- `./run.sh uv run ty check py_modules/sdh_ludusavi/`
- `./run.sh uv run pytest`
- `pnpm run verify`
- `./run.sh uv run python scripts/package_plugin.py`

## Implementation Steps
1. Replace the vendored `pyludusavi` package and `dist-info` directory with the
   clean `0.2.2` files from the project virtual environment.
2. Update SDH adapter and service code to use upstream-only pyludusavi APIs.
3. Add first-party executor env injection for Ludusavi subprocess calls.
4. Update tests, packaging references, and session documentation.
