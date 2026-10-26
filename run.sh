#!/usr/bin/env bash
mkdir -p -m 0700 /var/tmp/sdh_ludusavi
export CARGO_TARGET_DIR=/var/tmp/sdh_ludusavi/cargo-target
export UV_PROJECT_ENVIRONMENT=/tmp/sdh_ludusavi/.venv
export XDG_CACHE_HOME=/tmp/sdh_ludusavi/.cache
export PYTHONPYCACHEPREFIX=/tmp/sdh_ludusavi/__pycache__
export TMPDIR=/var/tmp/sdh_ludusavi
export PATH="/tmp/sdh_ludusavi/.venv/bin:$PATH"

echo "Using environment: /tmp/sdh_ludusavi/.venv"
exec "$@"
