# Review — vendor-pyludusavi-030 (round 01)

Branch: `feat/vendor-pyludusavi-030`
Commit reviewed: `dc46459` (feat(pyludusavi): re-vendor pyludusavi 0.3.0 and update references)
Reviewed against: `docs/plans/2026-06-26_vendor-pyludusavi-030.md`

## Verdict

APPROVED. The pyludusavi 0.3.0 re-vendoring is complete and correct.

## What was verified

- Vendored `py_modules/pyludusavi/` source is **byte-identical** to the published
  `pyludusavi-0.3.0` PyPI wheel (`diff -r` clean).
- Exactly one dist-info remains: `py_modules/pyludusavi-0.3.0.dist-info/` (METADATA
  `Version: 0.3.0`); the `0.2.6` dist-info was removed.
- Dependency pin bumped to `pyludusavi>=0.3.0` in `pyproject.toml`; `uv.lock` updated to
  0.3.0.
- All hard-coded `0.2.6` references updated: `scripts/package_plugin.py`,
  `scripts/validate_plugin_zip.py`, and the version-asserting tests
  (`test_ludusavi.py` -> `__version__ == "0.3.0"`, `test_vendored_pyludusavi.py` timeout
  count `2 -> 1` for 0.3.0's collapsed discovery code, plus the dist-info path references
  in `test_protocol.py`, `test_package_plugin.py`, `test_validate_plugin_zip.py`).
- `tests/test_ludusavi_discovery.py` mock signatures widened to accept `path=None` —
  a benign, correct adjustment for 0.3.0's discovery code.
- No `py_modules/sdh_ludusavi/` adapter changes were required; the plugin never used the
  removed `add_game_alias` method.

## Gate status

Full quality gates green (run via `scripts/orchestration/run-quality-gates` and again by
the pre-commit hook on amend):

- Python: 647 passed, coverage 86.63% (>= 83% required).
- Frontend: 229 passed; `rollup` build and `tsc --noEmit` clean.
- `ruff check`/`format` clean; `ty` clean; packaging + supply-chain checks pass.

## Prior findings — resolved

Round-01 finding: the implementer had swept the unrelated untracked
`docs/prompt_templates/` files into the implementation commit, violating the plan's
atomic-scope guard. **Resolved** by orchestrator recovery — the tip commit was amended to
exclude those files (now `dc46459`); the files are preserved on disk as untracked work.
Working tree is clean apart from that intentional untracked directory.

## Finalization instructions

Finalize with remote push enabled so `dev` is pushed and the dev prerelease can be cut
against the merged commit:

```bash
ORCH_PUSH=1 GIT_EDITOR=true scripts/orchestration/finalize vendor-pyludusavi-030
```

This merges `feat/vendor-pyludusavi-030` into `dev` (`--no-ff`), pushes `dev`, deletes the
feature branch, and runs the `finalize-release` hook, which invokes
`scripts/request_dev_release.sh` at the `0.3.5` package version to dispatch
`dev-release.yml` (producing prerelease `v0.3.5-dev.SHORTSHA`). No `package.json` /
`plugin.json` bump is needed.

STATUS: APPROVED
