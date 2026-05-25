#!/usr/bin/env bash
# Check if new/modified source files have matching test files
files=$(git diff --cached --name-only --diff-filter=ACM | grep "^py_modules/sdh_ludusavi/.*\.py$" || true)

for f in $files; do
  base=$(basename "$f" .py)
  test_file="tests/test_${base}.py"
  # Skip __init__.py and _version.py
  if [ "$base" == "__init__" ] || [ "$base" == "_version" ]; then continue; fi
  
  [[ "$f" != *.py ]] && continue

  if [[ ! -f "$test_file" ]]; then
    echo "❌ Missing test: $test_file for source file: $f"
    exit 1
  fi
done
