#!/usr/bin/env bash
mkdir -p -m 0700 /var/tmp/sdh_ludusavi
export CARGO_TARGET_DIR=/var/tmp/sdh_ludusavi/cargo-target
export UV_PROJECT_ENVIRONMENT=/tmp/sdh_ludusavi/.venv
export XDG_CACHE_HOME=/tmp/sdh_ludusavi/.cache
export PYTHONPYCACHEPREFIX=/tmp/sdh_ludusavi/__pycache__
export TMPDIR=/var/tmp/sdh_ludusavi
export PATH="/tmp/sdh_ludusavi/.venv/bin:$PATH"

if [[ "${1:-}" == cargo && ( " $* " == *" --target x86_64-unknown-linux-musl "* || " $* " == *" --target=x86_64-unknown-linux-musl "* ) ]]; then
    compiler="${CC_x86_64_unknown_linux_musl:-${CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER:-}}"
    if [[ -z "$compiler" ]]; then
        compiler="$(command -v musl-gcc || true)"
    fi
    if [[ -z "$compiler" ]] || ! command -v "$compiler" >/dev/null; then
        echo "musl-gcc is required: install musl-gcc on Fedora or musl-tools on Debian/Ubuntu." >&2
        exit 1
    fi
    export CC_x86_64_unknown_linux_musl="$compiler"
    export CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER="${CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER:-$compiler}"
fi

echo "Using environment: /tmp/sdh_ludusavi/.venv"
exec "$@"
