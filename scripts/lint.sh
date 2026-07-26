#!/usr/bin/env bash
# Run the same checks CI runs in the lint-web and lint-c jobs.
# Exits non-zero on any failure so this can gate a pre-push hook.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> clang-format --dry-run --Werror"
./scripts/c-sources.sh | xargs clang-format --dry-run --Werror

# cppcheck needs no ESP-IDF toolchain, just the binary, so it can run in the
# pre-push hook — and CI gates on it with --error-exitcode=1, so catching a
# finding here is strictly cheaper than catching it in the build job. Skipped
# with a note when not installed rather than failing: the hook must stay usable
# on a machine that has not installed it.
if command -v cppcheck >/dev/null 2>&1; then
    echo "==> cppcheck"
    make cppcheck
else
    echo "==> cppcheck: not installed, skipping (CI still gates on it)"
fi

echo "==> web_ui: typecheck + lint + format:check"
cd web_ui
npm run typecheck
npm run lint
npm run format:check
