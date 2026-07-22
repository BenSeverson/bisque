#!/usr/bin/env bash
# postCreateCommand for the Bisque dev container. Runtime, re-runnable setup —
# the network-dependent step (npm) lives here, mirroring the cloud
# session-start hooks. Re-runs on every container (re)create.
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

# Web UI deps (clean, lockfile-exact). Skips gracefully if web_ui is absent.
if [ -f web_ui/package.json ]; then
  echo "[postCreate] installing web_ui deps (npm ci)…"
  (cd web_ui && npm ci --no-audit --no-fund)
fi

# Readiness banner.
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true
echo "Bisque devcontainer ready:"
echo "  idf.py : $(idf.py --version 2>/dev/null || echo 'n/a')"
echo "  node   : $(node -v 2>/dev/null)  npm $(npm -v 2>/dev/null)"
echo "  claude : $(claude --version 2>/dev/null || echo 'CLI installed')"
echo "  kicad  : $(kicad-cli version 2>/dev/null || echo 'n/a')"
echo "Build: idf.py set-target esp32s3 && idf.py build  |  Full check: make ci"
