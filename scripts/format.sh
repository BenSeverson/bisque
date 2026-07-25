#!/usr/bin/env bash
# Auto-format C and web sources to match CI's format check.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> clang-format (C)"
./scripts/c-sources.sh | xargs clang-format -i

echo "==> prettier + eslint --fix (web_ui)"
cd web_ui
npm run format
npm run lint:fix
