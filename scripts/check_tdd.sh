#!/usr/bin/env bash
set -euo pipefail

# Rust unit-test modules are the final #[cfg(test)] mod tests in each source file;
# dedicated *_tests.rs files and tests/contract/ are also test changes.
python3 - <<'PY'
import re
import subprocess
import sys
from pathlib import PurePosixPath


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=False).stdout


def sections(path, content):
    if path.endswith(("_test.rs", "_tests.rs")):
        return b"", content
    match = re.search(rb"(?m)^\s*#\[cfg\(test\)\]\s*\n\s*mod\s+tests\s*\{", content)
    if match is None:
        return content, b""
    return content[:match.start()], content[match.start():]


paths = git("diff", "--cached", "--name-only", "--diff-filter=ACDMR", "-z", "--", "backend/src/", "tests/contract/").decode().split("\0")
test_changed = any(path.startswith("tests/contract/") for path in paths)
production_changed = False
for path in paths:
    if not path.startswith("backend/src/") or PurePosixPath(path).suffix != ".rs":
        continue
    before = git("show", f"HEAD:{path}")
    after = git("show", f":{path}")
    old_code, old_tests = sections(path, before)
    new_code, new_tests = sections(path, after)
    production_changed |= old_code != new_code
    test_changed |= old_tests != new_tests
if production_changed and not test_changed:
    print("Rust production changes require a unit-test region or contract-test change in the same commit.", file=sys.stderr)
    sys.exit(1)
PY
