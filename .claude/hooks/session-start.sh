#!/bin/bash
# SessionStart hook for Bisque — prepares a Claude Code web/cloud session.
#
# Installs the web UI toolchain so the web dashboard build, its Vitest suite,
# and the typecheck/lint/format checks all work out of the box. clang-format
# ships in the base image, so the C formatting checks already work without setup.
#
# Intentionally NOT installed: the ESP-IDF firmware build + flash and the
# clang-tidy / cppcheck static analysis. Those need the multi-GB Espressif
# toolchain (and flashing needs real kiln hardware), so they stay CI/bench
# concerns — see CLAUDE.md.
set -euo pipefail

# Only run in the remote (web/cloud) container. On a laptop the developer
# already has their own environment set up.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

echo "[bisque session-start] installing web UI toolchain (npm install)…"
if [ -f web_ui/package.json ]; then
  # npm install (not ci) so the cached container can reuse node_modules across
  # sessions; idempotent — a warm cache makes this a fast no-op.
  (cd web_ui && npm install --no-audit --no-fund)
  echo "[bisque session-start] web_ui deps ready."
else
  echo "[bisque session-start] web_ui/package.json not found — skipping npm install."
fi

if command -v clang-format >/dev/null 2>&1; then
  echo "[bisque session-start] clang-format: $(clang-format --version | head -n1)"
else
  echo "[bisque session-start] clang-format missing — C format checks unavailable."
fi

echo "[bisque session-start] ready. In-container: web_ui build/test/lint, C clang-format,"
echo "  docs & SVG diagrams. Needs a bench: idf.py firmware build/flash + on-hardware tests."
