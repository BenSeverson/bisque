#!/usr/bin/env bash
# Auto-format C and web sources to match CI's format check.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> clang-format (C)"
# Same guard as scripts/lint.sh: formatting zero files is silent success here
# too, and it is worse — you run `make format`, it reports nothing wrong, and
# the CI format check you were trying to satisfy still fails.
c_files="$(./scripts/c-sources.sh)"
if [ -z "$c_files" ]; then
    echo "no C sources found — the file list is broken, not clean" >&2
    exit 1
fi
echo "$c_files" | xargs clang-format -i

echo "==> prettier + eslint --fix (web_ui)"
cd web_ui
npm run format
npm run lint:fix
