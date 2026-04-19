#!/usr/bin/env bash
# Prints the project version for firmware + web UI + iOS builds.
# Source of truth: annotated git tags `vMAJOR.MINOR.PATCH`.
# Honours $VERSION (explicit override, e.g. release workflow).
set -euo pipefail

if [ -n "${VERSION:-}" ]; then
    echo "$VERSION"
    exit 0
fi

if v=$(git describe --tags --always --dirty --match 'v*' 2>/dev/null); then
    echo "$v"
else
    echo "0.0.0-unknown"
fi
