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

LVGL_DIR="managed_components/lvgl__lvgl"

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
# Same source and pin CI uses. If the ESP-IDF component manager later populates
# managed_components/ itself it will fetch this same version, so the two agree.
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
# The version is read out of lv_version.h rather than from git metadata,
# because this directory has two legitimate authors: this script (a git clone,
# tagged) and the ESP-IDF component manager during `idf.py build` (a plain
# extract, no .git). Checking the source means a manager-installed copy at the
# right version is accepted instead of being re-cloned on every session.
lvgl_cached_version() {
    local h="$LVGL_DIR/lv_version.h"
    [ -f "$h" ] || return 1
    awk '/#define LVGL_VERSION_MAJOR/{maj=$3}
         /#define LVGL_VERSION_MINOR/{min=$3}
         /#define LVGL_VERSION_PATCH/{pat=$3}
         END{if (maj=="") exit 1; printf "%s.%s.%s", maj, min, pat}' "$h"
}

if [ -f "$LVGL_DIR/lvgl.h" ]; then
    cached="$(lvgl_cached_version || true)"
    if [ "$cached" = "$LVGL_VERSION" ]; then
        log "ready (LVGL ${LVGL_VERSION}, SDL2 $(sdl2-config --version 2>/dev/null || echo ok))."
        exit 0
    fi
    log "cached LVGL is ${cached:-unreadable}, dependencies.lock pins ${LVGL_VERSION} — refreshing."
fi

if ! preflight_check "$PREFIX" \
    "github.com|git|https://github.com/lvgl/lvgl.git|LVGL sources for the display simulator"; then
    preflight_report_blocked "$PREFIX" "the LCD simulator"
    exit 0
fi

log "cloning LVGL v${LVGL_VERSION} for the simulator…"
rm -rf "$LVGL_DIR"
mkdir -p "$(dirname "$LVGL_DIR")"
git clone --depth 1 --branch "v${LVGL_VERSION}" \
    https://github.com/lvgl/lvgl.git "$LVGL_DIR" >/dev/null 2>&1 || {
    log "LVGL clone failed — 'make sim' unavailable this session."
    exit 0
}
log "ready. Validate display changes with: make sim-verify && make sim"
