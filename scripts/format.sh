#!/usr/bin/env bash
# Auto-format C and web sources to match CI's format check.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> clang-format (C)"
find main components \( -path '*/assets/*' -prune \) -o \( -name '*.c' -o -name '*.h' \) -print \
    | xargs clang-format -i

echo "==> prettier + eslint --fix (web_ui)"
cd web_ui
npm run format
npm run lint:fix
