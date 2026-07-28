#!/usr/bin/env bash
# Run the same checks CI runs in the lint-web and lint-c jobs.
# Exits non-zero on any failure so this can gate a pre-push hook.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> clang-format --dry-run --Werror"
# Checked before use: xargs given no input still runs clang-format once, which
# reads its empty stdin and exits 0 — a clean bill of health over zero files.
# `set -o pipefail` above catches a failing find, but not an empty result.
c_files="$(find main components \( -path '*/assets/*' -prune \) -o \
    \( -name '*.c' -o -name '*.h' \) -print)"
if [ -z "$c_files" ]; then
    echo "no C sources found — the file list is broken, not clean" >&2
    exit 1
fi
echo "$c_files" | xargs clang-format --dry-run --Werror

echo "==> web_ui: typecheck + lint + format:check"
cd web_ui
npm run typecheck
npm run lint
npm run format:check
