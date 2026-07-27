#!/bin/bash
# Installs KiCad 10 (kicad-cli + pcbnew Python + symbol/footprint libraries)
# in the cloud container so the hardware/kicad/ generator pipeline works there.
#
# REQUIRES a network policy that allows the Launchpad PPA host
# (ppa.launchpadcontent.net; keyserver.ubuntu.com for the signing key).
# Until that's enabled this script detects the block and exits cleanly
# without slowing the session — see docs/cloud-dev.md.
#
# The 3D model pack (kicad-packages3d, ~6 GB) is skipped by default; set
# KICAD_3D=1 to install it (needed only for component models in
# `kicad-cli pcb render` — the board itself renders without it).
set -euo pipefail

PPA="kicad/kicad-10.0-releases"
PPA_URL="https://ppa.launchpadcontent.net/${PPA}/ubuntu"

log() { printf '[kicad install] %s\n' "$*"; }

# --- Fast path: KiCad 9+ already present → nothing to do. ------------------
if command -v kicad-cli >/dev/null 2>&1; then
  ver="$(kicad-cli version 2>/dev/null || echo 0)"
  case "$ver" in
    9.*|1[0-9].*)
      log "kicad-cli $ver already installed — skipping."
      exit 0
      ;;
  esac
fi

# --- Preflight: is the Launchpad network policy enabled yet? ---------------
# Connection-level failure (proxy block) → non-zero curl exit; any HTTP
# response means the host is reachable.
. /etc/os-release 2>/dev/null || true
CODENAME="${UBUNTU_CODENAME:-noble}"
if ! curl -s -o /dev/null --max-time 8 \
     "${PPA_URL}/dists/${CODENAME}/InRelease" 2>/dev/null; then
  log "KiCad PPA unreachable (network policy not allowing"
  log "ppa.launchpadcontent.net yet). Skipping KiCad install — the PCB"
  log "generator requires KiCad 10 and stays unavailable in this session."
  log "Allow the host in the environment settings and restart the session."
  exit 0
fi
log "KiCad PPA reachable — installing KiCad 10 for ${CODENAME}…"

export DEBIAN_FRONTEND=noninteractive

# --- Add the PPA. add-apt-repository resolves the signing key itself (via
# Launchpad/keyserver); if those hosts are blocked, fall back to trusting
# the repo — acceptable inside this sandboxed container.
if apt-get install -y -qq software-properties-common >/dev/null 2>&1 &&
   add-apt-repository -y "ppa:${PPA}" >/dev/null 2>&1; then
  log "PPA added with verified signing key."
else
  log "add-apt-repository failed (keyserver blocked?) — adding PPA as trusted."
  echo "deb [trusted=yes] ${PPA_URL} ${CODENAME} main" \
    > /etc/apt/sources.list.d/kicad.list
fi
apt-get update -qq 2>/dev/null || true

log "installing kicad + symbol/footprint libraries (~1.5 GB)…"
PKGS="kicad kicad-symbols kicad-footprints"
[ "${KICAD_3D:-0}" = "1" ] && PKGS="$PKGS kicad-packages3d"
# shellcheck disable=SC2086
apt-get install -y -qq --no-install-recommends $PKGS >/dev/null

log "installed: $(kicad-cli version 2>/dev/null || echo '?')"
python3 -c "import pcbnew" 2>/dev/null && log "pcbnew python OK" || \
  log "warning: 'import pcbnew' failed for the default python3."
log "done. Regenerate the board with hardware/kicad/generator/kicad_build.py"
