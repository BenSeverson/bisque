#!/bin/bash
# Installs what the LVGL/SDL2 display simulator needs: libsdl2-dev from the
# Ubuntu archive, and LVGL pinned to the version in dependencies.lock.
#
# Worth doing unconditionally — unlike the firmware and PCB toolchains this
# needs no network-policy change (Ubuntu archive + github.com are both reachable
# by default), and it turns `make sim` / `make sim-verify` into a real local
# check. That matters for laptop-free development: the simulator is how a
# components/display/ change gets validated without flashing hardware, and it is
# one of the five test layers CI runs.
#
# Mirrors the ui-screenshots job in .github/workflows/build.yml, including
# reading the LVGL version from dependencies.lock rather than hardcoding it, so
# the simulator links the same LVGL the firmware does.
set -euo pipefail

HOOK_LIB="$(dirname "${BASH_SOURCE[0]}")/lib"
# shellcheck source=lib/preflight.sh
. "$HOOK_LIB/preflight.sh"

PREFIX='[sim deps]'
log() { printf '%s %s\n' "$PREFIX" "$*"; }

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

# Where the ESP-IDF component manager puts LVGL during a firmware build, and
# where this script clones it when there hasn't been one. They are deliberately
# different directories: managed_components/ belongs to the component manager,
# which aborts the firmware build on any component there that lacks the
# .component_hash it writes itself, and a git clone has no such file. Cloning
# into it — as this script used to — left a container where `make sim` worked
# and `idf.py build` could not configure at all.
LVGL_MANAGED="managed_components/lvgl__lvgl"
LVGL_STANDALONE="simulator/.lvgl"

# ── SDL2 ──────────────────────────────────────────────────────────────────
if ! pkg-config --exists sdl2 2>/dev/null && ! command -v sdl2-config >/dev/null 2>&1; then
    log "installing libsdl2-dev…"
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y -qq libsdl2-dev >/dev/null 2>&1 || {
        log "libsdl2-dev install failed — 'make sim' unavailable this session."
        exit 0
    }
fi

# ── LVGL ──────────────────────────────────────────────────────────────────
# Repair first. A container provisioned by an earlier version of this hook has a
# plain git clone sitting in managed_components/lvgl__lvgl — right sources, right
# version, but no .component_hash, which is precisely the state that makes
# `idf.py build` abort. Without this the version check below would accept it and
# report "ready", so pulling this fix would not actually fix such a container.
#
# The marker files are the component manager's own; anything there without one
# was not put there by the manager.
#
# Relocated rather than deleted: the sources are fine, they are merely in the
# wrong directory, and moving them keeps `make sim` working with no network and
# no re-clone.
if [ -f "$LVGL_MANAGED/lvgl.h" ] &&
    [ ! -f "$LVGL_MANAGED/.component_hash" ] &&
    [ ! -f "$LVGL_MANAGED/CHECKSUMS.json" ]; then
    log "unmanaged LVGL clone in ${LVGL_MANAGED} (no .component_hash) — it would break"
    log "  'idf.py build'; relocating it to ${LVGL_STANDALONE}."
    rm -rf "$LVGL_STANDALONE"
    mkdir -p "$(dirname "$LVGL_STANDALONE")"
    mv "$LVGL_MANAGED" "$LVGL_STANDALONE"
fi

# Same source and pin CI uses. If the ESP-IDF component manager later populates
# managed_components/ itself it will fetch this same version, so the two agree —
# and simulator/CMakeLists.txt prefers that copy, so the standalone clone below
# stops being used the moment there is a firmware build in the tree.
LVGL_VERSION="$(awk '/^  lvgl\/lvgl:/{f=1; next} f && /version:/{gsub(/"/,"",$2); print $2; exit}' \
    dependencies.lock 2>/dev/null || true)"
if [ -z "$LVGL_VERSION" ]; then
    log "could not read the LVGL version from dependencies.lock — skipping."
    exit 0
fi

# Validate the cache against the pin rather than just checking it exists.
# Container state outlives a dependencies.lock bump, so an existence-only fast
# path would keep building the simulator against the previous LVGL while CI
# used the new one — silently defeating the version parity this exists for.
#
# The version is read out of lv_version.h rather than from git metadata, because
# either directory may hold the copy: this script's git clone (tagged) or the
# component manager's extract (no .git). Checking the source means a
# manager-installed copy at the right version is accepted, and no second copy is
# cloned for it.
lvgl_cached_version() {
    local h="$1/lv_version.h"
    [ -f "$h" ] || return 1
    awk '/#define LVGL_VERSION_MAJOR/{maj=$3}
         /#define LVGL_VERSION_MINOR/{min=$3}
         /#define LVGL_VERSION_PATCH/{pat=$3}
         END{if (maj=="") exit 1; printf "%s.%s.%s", maj, min, pat}' "$h"
}

# Checked in the same order simulator/CMakeLists.txt resolves them.
for dir in "$LVGL_MANAGED" "$LVGL_STANDALONE"; do
    [ -f "$dir/lvgl.h" ] || continue
    cached="$(lvgl_cached_version "$dir" || true)"
    if [ "$cached" = "$LVGL_VERSION" ]; then
        log "ready (LVGL ${LVGL_VERSION} from ${dir}, SDL2 $(sdl2-config --version 2>/dev/null || echo ok))."
        exit 0
    fi
    log "LVGL in ${dir} is ${cached:-unreadable}, dependencies.lock pins ${LVGL_VERSION}."
done

if ! preflight_check "$PREFIX" \
    "github.com|git|https://github.com/lvgl/lvgl.git|LVGL sources for the display simulator"; then
    preflight_report_blocked "$PREFIX" "the LCD simulator"
    exit 0
fi

log "cloning LVGL v${LVGL_VERSION} for the simulator…"
rm -rf "$LVGL_STANDALONE"
mkdir -p "$(dirname "$LVGL_STANDALONE")"
git clone --depth 1 --branch "v${LVGL_VERSION}" \
    https://github.com/lvgl/lvgl.git "$LVGL_STANDALONE" >/dev/null 2>&1 || {
    log "LVGL clone failed — 'make sim' unavailable this session."
    exit 0
}
log "ready. Validate display changes with: make sim-verify && make sim"
