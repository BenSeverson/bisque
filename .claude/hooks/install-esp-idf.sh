#!/bin/bash
# Installs the ESP-IDF firmware toolchain in a Claude Code cloud container so
# `idf.py build`, `make clang-tidy` and `make cppcheck` behave exactly as they
# do in CI and in the VS Code dev container.
#
# The target is parity, not "a build that completes". CI builds inside
# espressif/idf:v6.0.2 (.github/workflows/build.yml) and resolves managed
# components from the Espressif registry; this script reproduces that on a
# stock container. It installs the pinned IDF version, the esp32s3 tools, the
# Python environment under Espressif's own dependency constraints, and
# esp-clang for clang-tidy.
#
# It deliberately does NOT route around a restrictive network policy. Skipping
# the Python constraints, sideloading tools from mirrors, or vendoring the
# managed components all produce a toolchain that compiles something other than
# what CI compiles — which is worse than no toolchain, because it reports
# success. When a required host is blocked the script says which one and how to
# allow it, then exits cleanly so session startup stays fast.
set -euo pipefail

IDF_VERSION="${IDF_VERSION:-v6.0.2}"
IDF_TARGET="${IDF_TARGET:-esp32s3}"
IDF_DIR="${IDF_DIR:-$HOME/esp-idf}"

HOOK_LIB="$(dirname "${BASH_SOURCE[0]}")/lib"
# shellcheck source=lib/preflight.sh
. "$HOOK_LIB/preflight.sh"
# shellcheck source=lib/toolchain.sh
. "$HOOK_LIB/toolchain.sh"

PREFIX='[esp-idf install]'
log() { printf '%s %s\n' "$PREFIX" "$*"; }

# Constraints file for the pinned IDF minor. install.sh and export.sh both
# require it; its presence is what proves the Python env was resolved the way
# Espressif pins it rather than to whatever pip happened to pick.
idf_minor() { printf '%s' "${IDF_VERSION#v}" | cut -d. -f1,2; }
constraints_file() { printf '%s/.espressif/espidf.constraints.v%s.txt' "$HOME" "$(idf_minor)"; }

# ── Fast path ─────────────────────────────────────────────────────────────
# Container state is cached between sessions, so a good install must be a
# near-instant no-op.
if toolchain_idf_ready; then
    log "ESP-IDF $IDF_VERSION ready at $IDF_DIR."
    persist_only=1
else
    persist_only=0
    if [ -e "$IDF_DIR" ] && [ ! -f "$(constraints_file)" ]; then
        log "found an incomplete ESP-IDF at $IDF_DIR (missing dependency"
        log "constraints) — reinstalling so this container matches CI."
    fi
fi

if [ "$persist_only" = "0" ]; then
    # ── Preflight ─────────────────────────────────────────────────────────
    # Every host a CI-identical install and build actually touches. github.com
    # carries the IDF sources and, per tools.json, almost every tool archive;
    # the Espressif hosts carry the dependency constraints and the component
    # registry that `idf.py build` resolves idf_component.yml against.
    ASSET_URL="https://github.com/espressif/esp-idf/archive/refs/tags/${IDF_VERSION}.tar.gz"
    if ! preflight_check "$PREFIX" \
        "github.com|git|https://github.com/espressif/esp-idf.git|ESP-IDF sources" \
        "objects.githubusercontent.com|http|$ASSET_URL|GitHub release assets — most toolchain archives" \
        "dl.espressif.com|http|https://dl.espressif.com/dl/esp-idf/espidf.constraints.v$(idf_minor).txt|Python dependency constraints; some tool archives" \
        "api.components.espressif.com|http|https://api.components.espressif.com/api/components/espressif/cjson|component registry API — resolves idf_component.yml" \
        "components.espressif.com|http|https://components.espressif.com/|component downloads into managed_components/"; then
        preflight_report_blocked "$PREFIX" "the firmware build"
        log "Web UI, host C tests and clang-format all still work — see the table"
        log "in docs/cloud-dev.md for what runs without the firmware toolchain."
        exit 0
    fi
    log "all required hosts reachable — installing ESP-IDF $IDF_VERSION."

    # ── OS prerequisites ──────────────────────────────────────────────────
    # Only the IDF prereqs the base image lacks. libusb is needed even though
    # this container never flashes: install.sh verifies openocd by running it,
    # and openocd will not start without libusb. cppcheck matches the CI job.
    log "installing OS prerequisites via apt…"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq 2>/dev/null || true
    apt-get install -y -qq git wget flex bison gperf python3 python3-venv \
        cmake ninja-build ccache libffi-dev libssl-dev dfu-util \
        libusb-1.0-0 cppcheck >/dev/null
    log "OS prerequisites ready."

    # ── ESP-IDF ───────────────────────────────────────────────────────────
    if [ ! -d "$IDF_DIR/.git" ]; then
        log "cloning esp-idf $IDF_VERSION (shallow, recursive)…"
        rm -rf "$IDF_DIR"
        git clone --depth 1 -b "$IDF_VERSION" --recursive \
            https://github.com/espressif/esp-idf.git "$IDF_DIR"
    fi

    log "running install.sh $IDF_TARGET (downloads ~2 GB of tools)…"
    "$IDF_DIR/install.sh" "$IDF_TARGET"

    # esp-clang backs `make clang-tidy`. CI installs it the same way, on top of
    # the image, because it is not bundled with IDF.
    log "installing esp-clang for clang-tidy…"
    (
        . "$IDF_DIR/export.sh" >/dev/null 2>&1
        python "$IDF_DIR/tools/idf_tools.py" install esp-clang
    ) || log "warning: esp-clang install failed — 'make clang-tidy' will not work."

    # ── Verify ────────────────────────────────────────────────────────────
    # Report a broken install as broken. Silently handing back a container that
    # cannot build is exactly the failure mode this script exists to prevent.
    if ! toolchain_idf_ready; then
        log "ERROR: ESP-IDF installed but does not activate cleanly."
        log "Re-run this script, or see docs/cloud-dev.md for diagnosis."
        exit 1
    fi
    log "ESP-IDF $IDF_VERSION installed and verified."
fi

# ── Persist activation for the session ────────────────────────────────────
# CLAUDE_ENV_FILE is sourced into every shell the session spawns; sourcing
# export.sh there is what puts idf.py and the xtensa toolchain on PATH without
# each command having to activate first. Guard against stacking duplicates
# across repeated hook runs.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    src_line=". \"$IDF_DIR/export.sh\" >/dev/null 2>&1 || true"
    if ! grep -qF "$src_line" "$CLAUDE_ENV_FILE" 2>/dev/null; then
        printf '%s\n' "$src_line" >>"$CLAUDE_ENV_FILE"
        log "idf.py added to the session PATH."
    fi
fi

log "build with: idf.py set-target $IDF_TARGET && idf.py build"
