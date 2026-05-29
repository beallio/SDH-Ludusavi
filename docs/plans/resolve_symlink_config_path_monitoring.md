# Implementation Plan - Resolve Symlink Config Path Monitoring

## Problem Definition
When checking for configurations changes, the adapter gets the configuration path (e.g., `config.yaml`). If the user manages their configurations with a symlink (such as GNU Stow or a Dropbox dotfiles folder), the path points to the symlink.
If we call `.parent` on a symlinked path directly without resolving it first, it points to the symlink source folder instead of the target folder where the actual `config.yaml` and optional sibling files (`cache.yaml`, `manifest.yaml`) reside.
This causes the adapter to miss updates to the sibling files.

To resolve this issue, the configuration path must be resolved using `Path.resolve()` before getting the parent directory and checking for sibling config files.

---

## User Review Required
No breaking changes or user input are expected. The change preserves the existing behavior for standard paths while adding support for symlinked configurations.

---

## Open Questions
None.

---

## Proposed Changes

### sdh_ludusavi core

#### [MODIFY] [ludusavi.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/ludusavi.py)
Update `PyludusaviAdapter.get_config_mtime_ns` to call `.resolve()` on the configuration path.

```python
config_path = Path(config_path_str).resolve()
```

### tests

#### [MODIFY] [test_adapter_cache.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_adapter_cache.py)
- Refactor the stat syscall count test to tolerate extra stat syscalls from path resolution while ensuring sibling files are still stat'ed exactly once.
- Add `test_get_config_mtime_ns_resolves_symlinks` to test that a symlinked configuration path resolves correctly to the target folder containing sibling configuration files.

---

## Verification Plan

### Automated Tests
- Run style checks:
  ```bash
  ./run.sh uv run ruff check . --fix
  ./run.sh uv run ruff format .
  ./run.sh uv run ty check py_modules/sdh_ludusavi/
  ```
- Run the full test suite:
  ```bash
  ./run.sh uv run pytest
  ```

### Manual Verification
- Verify that symlinked configurations in typical environments correctly track sibling changes.
