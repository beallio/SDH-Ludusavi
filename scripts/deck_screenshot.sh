#!/usr/bin/env bash
# Capture the Steam Deck's current screen and copy the PNG back here.
#
# The Deck runs a gamescope session, so grim/spectacle are not usable; the
# working path is `gamescopectl screenshot`. Two sharp edges it papers over:
# the SSH session is a tty session and needs XDG_RUNTIME_DIR pointed at the
# graphical one, and gamescopectl returns 0 before the PNG is written, so the
# file has to be polled until its size is stable.
set -euo pipefail

HOST="${DECK_HOST:-steamdeck}"
DECK_UID="${DECK_UID:-1000}"
TIMEOUT="${DECK_SCREENSHOT_TIMEOUT:-15}"
POLL_INTERVAL="${DECK_POLL_INTERVAL:-0.5}"
CONNECT_TIMEOUT="${DECK_SSH_CONNECT_TIMEOUT:-5}"

stamp="$(date -u +%Y%m%d-%H%M%S)"
output="${1:-out/deck-screenshot-${stamp}.png}"
remote="/tmp/deck-screenshot-$$-${stamp}.png"

if ! ssh -q -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" "$HOST" exit >/dev/null 2>&1; then
  echo "Steam Deck (${HOST}) not reachable over SSH." >&2
  exit 1
fi

echo "Requesting screenshot from ${HOST}..."
ssh "$HOST" "XDG_RUNTIME_DIR=/run/user/${DECK_UID} gamescopectl screenshot ${remote}"

cleanup() { ssh "$HOST" "rm -f ${remote}" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# gamescopectl writes asynchronously: wait for the file to appear and for its
# size to stop changing, so a half-written PNG is never copied.
deadline=$(($(date +%s) + TIMEOUT))
previous=""
size=""
while [[ "$(date +%s)" -lt "$deadline" ]]; do
  if size="$(ssh "$HOST" "stat -c %s ${remote}" 2>/dev/null)"; then
    if [[ -n "$size" && "$size" != "0" && "$size" == "$previous" ]]; then
      break
    fi
    previous="$size"
  fi
  size=""
  sleep "$POLL_INTERVAL"
done

if [[ -z "$size" ]]; then
  echo "Timed out after ${TIMEOUT}s waiting for ${remote} on ${HOST}." >&2
  exit 1
fi

mkdir -p "$(dirname "$output")"
scp -q "${HOST}:${remote}" "$output"

echo "$output"
