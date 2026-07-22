"""Behavioral tests for ``scripts/deck_screenshot.sh``.

The Deck runs a gamescope session where ``gamescopectl screenshot`` returns
exit 0 *before* the PNG exists, so the helper has to poll for a stable file
before copying it back. These tests drive the real script with stub ``ssh`` and
``scp`` binaries injected on ``PATH``, so no Steam Deck is required.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deck_screenshot.sh"

SSH_STUB = r"""#!/usr/bin/env bash
# Stub ssh. Logs argv, fakes a gamescope capture that appears after N polls.
printf '%s\n' "ssh $*" >>"$STUB_LOG"

args=("$@")
remote_cmd="${args[${#args[@]}-1]}"

if [[ "$remote_cmd" == "exit" ]]; then
  [[ "${STUB_UNREACHABLE:-0}" == "1" ]] && exit 255
  exit 0
fi

map() { printf '%s' "$STUB_REMOTE_ROOT$1"; }

if [[ "$remote_cmd" == *"gamescopectl screenshot"* ]]; then
  # Returns immediately; the file shows up later (or never).
  exit 0
fi

if [[ "$remote_cmd" == stat* ]]; then
  path="${remote_cmd##* }"
  count=$(cat "$STUB_COUNTER" 2>/dev/null || echo 0)
  count=$((count + 1))
  printf '%s' "$count" >"$STUB_COUNTER"
  appear="${STUB_APPEAR_AT:-0}"
  if [[ "$appear" != "0" && "$count" -ge "$appear" ]]; then
    local_path="$(map "$path")"
    mkdir -p "$(dirname "$local_path")"
    printf 'fake-png-bytes' >"$local_path"
    stat -c %s "$local_path"
    exit 0
  fi
  exit 1
fi

exit 0
"""

SCP_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "scp $*" >>"$STUB_LOG"
src="${@: -2:1}"
dest="${@: -1}"
remote_path="${src#*:}"
cp "$STUB_REMOTE_ROOT$remote_path" "$dest"
"""


@pytest.fixture
def deck(tmp_path: Path):
    """Stubbed Deck environment: fake ssh/scp on PATH plus a runner."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("ssh", SSH_STUB), ("scp", SCP_STUB)):
        target = bindir / name
        target.write_text(body)
        target.chmod(target.stat().st_mode | stat.S_IEXEC)

    log = tmp_path / "calls.log"
    log.write_text("")
    counter = tmp_path / "poll_count"
    remote_root = tmp_path / "remote"
    remote_root.mkdir()

    def run(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
        full_env = dict(os.environ)
        full_env["PATH"] = f"{bindir}{os.pathsep}{full_env['PATH']}"
        full_env.update(
            STUB_LOG=str(log),
            STUB_COUNTER=str(counter),
            STUB_REMOTE_ROOT=str(remote_root),
            DECK_POLL_INTERVAL="0.05",
            DECK_SCREENSHOT_TIMEOUT="2",
        )
        full_env.update(env)
        return subprocess.run(
            [str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=full_env,
            cwd=str(tmp_path),
        )

    run.log = log  # type: ignore[attr-defined]
    return run


def _log(deck) -> str:
    return deck.log.read_text()


def test_script_is_executable_and_strict() -> None:
    assert SCRIPT.exists(), f"{SCRIPT} is missing"
    assert os.access(SCRIPT, os.X_OK), "helper script must be executable"
    assert "set -euo pipefail" in SCRIPT.read_text()


def test_captures_and_copies_screenshot(deck, tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    result = deck(str(out), STUB_APPEAR_AT="2")

    assert result.returncode == 0, result.stderr
    assert out.read_text() == "fake-png-bytes"
    assert str(out) in result.stdout


def test_capture_waits_for_file_before_copying(deck, tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    deck(str(out), STUB_APPEAR_AT="3")

    calls = [line for line in _log(deck).splitlines() if line.strip()]
    stat_calls = [c for c in calls if " stat " in c]
    scp_index = next(i for i, c in enumerate(calls) if c.startswith("scp "))
    assert len(stat_calls) >= 3, f"expected repeated polling, got: {calls}"
    assert all(calls.index(c) < scp_index for c in stat_calls), "polling must precede the copy"


def test_screenshot_runs_with_graphical_runtime_dir(deck, tmp_path: Path) -> None:
    deck(str(tmp_path / "shot.png"), STUB_APPEAR_AT="1")

    capture = next(c for c in _log(deck).splitlines() if "gamescopectl screenshot" in c)
    assert "XDG_RUNTIME_DIR=/run/user/1000" in capture


def test_removes_remote_temp_file(deck, tmp_path: Path) -> None:
    deck(str(tmp_path / "shot.png"), STUB_APPEAR_AT="1")

    assert any("rm -f" in line and ".png" in line for line in _log(deck).splitlines()), _log(deck)


def test_unreachable_deck_fails_without_copying(deck, tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    result = deck(str(out), STUB_UNREACHABLE="1")

    assert result.returncode != 0
    assert "steamdeck" in (result.stdout + result.stderr)
    assert not out.exists()
    assert "scp " not in _log(deck)


def test_timeout_when_capture_never_appears(deck, tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    result = deck(str(out), STUB_APPEAR_AT="0", DECK_SCREENSHOT_TIMEOUT="1")

    assert result.returncode != 0
    assert not out.exists()
    assert "scp " not in _log(deck)


def test_honours_deck_host_override(deck, tmp_path: Path) -> None:
    deck(str(tmp_path / "shot.png"), STUB_APPEAR_AT="1", DECK_HOST="deck-two")

    assert "deck-two" in _log(deck)
    assert "steamdeck" not in _log(deck)


def test_defaults_output_path_under_out(deck, tmp_path: Path) -> None:
    result = deck(STUB_APPEAR_AT="1")

    assert result.returncode == 0, result.stderr
    written = list((tmp_path / "out").glob("deck-screenshot-*.png"))
    assert len(written) == 1, f"expected one default screenshot, got {written}"
