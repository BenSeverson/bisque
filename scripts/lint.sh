#!/usr/bin/env bash
# Run the same checks CI runs in the lint-web and lint-c jobs.
# Exits non-zero on any failure so this can gate a pre-push hook.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> clang-format --dry-run --Werror"
find main components \( -path '*/assets/*' -prune \) -o \( -name '*.c' -o -name '*.h' \) -print \
    | xargs clang-format --dry-run --Werror

echo "==> web_ui: typecheck + lint + format:check"
cd web_ui
npm run typecheck
npm run lint
npm run format:check
