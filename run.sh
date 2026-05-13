#!/usr/bin/env bash
export UV_PROJECT_ENVIRONMENT=/tmp/sdh_ludusavi/.venv
export XDG_CACHE_HOME=/tmp/sdh_ludusavi/.cache
export PYTHONPYCACHEPREFIX=/tmp/sdh_ludusavi/__pycache__
export TMPDIR=/tmp/sdh_ludusavi
export PYTHONPATH="py_modules:$PYTHONPATH"
export PATH="/tmp/sdh_ludusavi/.venv/bin:$PATH"

echo "Using environment: /tmp/sdh_ludusavi/.venv"
exec "$@"
