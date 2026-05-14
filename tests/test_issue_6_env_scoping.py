from __future__ import annotations
import os
import subprocess
import sys


def test_ld_library_path_not_mutated_globally():
    # We use a subprocess to ensure a clean environment for the import test
    code = """
import os
os.environ["LD_LIBRARY_PATH"] = "original_value"
import sdh_ludusavi.ludusavi
print(os.environ.get("LD_LIBRARY_PATH"))
"""
    # Set PYTHONPATH to include py_modules
    env = os.environ.copy()
    env["PYTHONPATH"] = "py_modules"

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)

    # Currently it will print an empty string (or nothing) because it's cleared
    # Proposed fix: it should print "original_value"
    assert result.stdout.strip() == "original_value"
