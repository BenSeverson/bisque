#!/bin/bash
# Installs the ESP-IDF v6.0.2 toolchain for esp32s3 so `idf.py build` works in
# the cloud container. Mirrors what .github/workflows/build.yml does in CI.
#
# This builds firmware only — flashing/monitoring still needs physical kiln
# hardware. The install is ~2 GB; container state is cached after the hook
# completes, so this is a slow first run and a fast no-op afterwards.
#
# REQUIRES a network policy that allows Espressif hosts (dl.espressif.com,
# *.espressif.com, api.components.espressif.com). Until that's enabled the
# component registry and tool downloads are blocked, so this script detects the
# block and exits cleanly without slowing the session — see docs/cloud-dev.md.
set -euo pipefail

IDF_VERSION="${IDF_VERSION:-v6.0.2}"
IDF_TARGET="${IDF_TARGET:-esp32s3}"
IDF_DIR="$HOME/esp-idf"

log() { printf '[esp-idf install] %s\n' "$*"; }

# --- Fast path: already installed → just persist env and exit. -------------
if [ -f "$IDF_DIR/export.sh" ] && [ -d "$HOME/.espressif/tools" ]; then
  log "already installed at $IDF_DIR — skipping download."
  persist_only=1
else
  persist_only=0

  # --- Preflight: is the Espressif network policy enabled yet? ------------
  # The component manager resolves deps from api.components.espressif.com; the
  # build needs it. Without -f, curl exits 0 for ANY HTTP reply (even 403) and
  # non-zero only on a connection-level failure — exactly the signal we want:
  # under the default policy this host hard-blocks (no reply => non-zero exit),
  # and once allow-listed it answers (exit 0).
  if ! curl -s -o /dev/null --max-time 8 \
       https://api.components.espressif.com/api/components/espressif/cjson 2>/dev/null; then
    log "Espressif component registry unreachable (network policy not allowing"
    log "*.espressif.com yet). Skipping firmware toolchain install — build stays"
    log "CI-only. Enable the policy and restart the session to install it."
    exit 0
  fi
  log "component registry reachable — proceeding with install."
fi

# --- OS prerequisites (idempotent; apt skips already-installed packages). --
if [ "$persist_only" = "0" ]; then
  # Only the IDF prereqs not already in the base image. apt-get update may
  # partial-fail on blocked third-party PPAs (deadsnakes/ondrej) — the main
  # Ubuntu archive still refreshes, so tolerate that with `|| true`.
  log "installing OS prerequisites via apt…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq -o APT::Update::Error-Mode=any 2>/dev/null || \
    apt-get update -qq 2>/dev/null || true
  apt-get install -y -qq git wget flex bison gperf python3 python3-venv \
    cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0 >/dev/null
  log "OS prerequisites ready."

  # --- Clone + install ESP-IDF (shallow, version-pinned, recursive). -------
  if [ ! -d "$IDF_DIR/.git" ]; then
    log "cloning esp-idf $IDF_VERSION (shallow, recursive)…"
    git clone --depth 1 -b "$IDF_VERSION" --recursive \
      https://github.com/espressif/esp-idf.git "$IDF_DIR"
  fi
  log "running esp-idf install.sh for $IDF_TARGET (downloads ~2 GB of tools)…"
  "$IDF_DIR/install.sh" "$IDF_TARGET"
  log "esp-idf toolchain installed."
fi

# --- Persist env so `idf.py` is on PATH for the whole session. -------------
# CLAUDE_ENV_FILE is sourced into the session shell; sourcing export.sh is the
# canonical way to expose idf.py + the tool paths. Guard against duplicates so
# repeated hook runs don't stack the line.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  src_line='[ -f "$HOME/esp-idf/export.sh" ] && . "$HOME/esp-idf/export.sh" >/dev/null 2>&1 || true'
  if ! grep -qF "$src_line" "$CLAUDE_ENV_FILE" 2>/dev/null; then
    printf '%s\n' "$src_line" >> "$CLAUDE_ENV_FILE"
    log "added esp-idf export.sh to session env ($CLAUDE_ENV_FILE)."
  fi
fi

log "done. Build with: idf.py set-target $IDF_TARGET && idf.py build"
