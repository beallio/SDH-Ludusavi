# Plan: Update pyludusavi to 0.2.2

## Problem Definition
Update the `pyludusavi` dependency from `0.2.1` to `0.2.2` to pull in recent improvements or fixes.

## Strategy
1.  Update the dependency version in `pyproject.toml`.
2.  Run `uv sync` to update `uv.lock`.
3.  Verify the update by running tests.

## Testing Strategy
1.  Run the full validation suite (ruff, ty, pytest).
2.  Specifically check `tests/test_version.py` or similar if they check dependency versions.

## Steps
1.  Modify `pyproject.toml` to require `pyludusavi>=0.2.2`.
2.  Run `./run.sh uv sync`.
3.  Run `./run.sh uv run pytest`.
