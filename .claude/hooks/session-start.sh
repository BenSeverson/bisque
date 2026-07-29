#!/bin/bash
# SessionStart hook for Bisque — prepares a Claude Code web/cloud session.
#
# Goal: a cloud session that builds what CI builds, so the whole project can be
# developed from a browser or phone with no laptop involved. Everything except
# flashing and on-hardware testing is reproducible here.
#
# Each installer below checks whether the network policy allows the hosts it
# needs and, if not, prints exactly which hosts to allow. None of them work
# around a block — see docs/cloud-dev.md for why, and for the full allow-list.
set -euo pipefail

# Only run in the remote (web/cloud) container. On a laptop the developer
# already has their own environment, or uses .devcontainer/.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
HOOKS="$(dirname "$0")"

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

# cppcheck backs `make cppcheck`, one of the two static-analysis steps in the
# CI build job. It comes from the Ubuntu archive (no special network policy)
# and is small, so install it unconditionally rather than tying it to the
# ESP-IDF path — unlike clang-tidy, it does not need the IDF toolchain.
if ! command -v cppcheck >/dev/null 2>&1; then
    echo "[bisque session-start] installing cppcheck…"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cppcheck >/dev/null 2>&1 ||
        echo "[bisque session-start] cppcheck install failed — 'make cppcheck' unavailable."
fi

# Display simulator: SDL2 + LVGL. Needs no network-policy change, and is how
# components/display/ changes get validated without hardware.
bash "$HOOKS/install-sim-deps.sh" ||
    echo "[bisque session-start] sim deps step failed (non-fatal)."

# Firmware toolchain and PCB toolchain. Both are fast no-ops on a warm
# container and exit in a few seconds when their hosts are blocked.
bash "$HOOKS/install-esp-idf.sh" ||
    echo "[bisque session-start] esp-idf install step failed (non-fatal)."
bash "$HOOKS/install-kicad.sh" ||
    echo "[bisque session-start] kicad install step failed (non-fatal)."

# ── Capability summary ────────────────────────────────────────────────────
# Report what this specific session can actually do. The installers have
# already explained any blocked hosts in detail; this is the one-glance
# version so the state is obvious without scrolling back.
#
# Both predicates are functional (see lib/toolchain.sh): a leftover export.sh
# or the stock too-old kicad-cli must not be reported as a working toolchain.
# shellcheck source=lib/toolchain.sh
. "$HOOKS/lib/toolchain.sh"

have_idf=no
if toolchain_idf_ready; then have_idf=yes; fi
# clang-tidy needs esp-clang on top of an activatable IDF. Its install is
# non-fatal, so an IDF that activates does not by itself mean clang-tidy works.
have_clang_tidy=no
if [ "$have_idf" = yes ] && [ -d "$HOME/.espressif/tools/esp-clang" ]; then
    have_clang_tidy=yes
fi
# cppcheck's install is non-fatal too — report what is actually on PATH rather
# than what was attempted.
have_cppcheck=no
if command -v cppcheck >/dev/null 2>&1; then have_cppcheck=yes; fi
have_kicad=no
if toolchain_kicad_ready; then have_kicad=yes; fi
# Both LVGL locations count — simulator/CMakeLists.txt resolves either. A clean
# session that has never run a firmware build has only the standalone clone, and
# probing just managed_components/ would report the simulator unavailable while
# `make sim` works, steering display changes away from the validation they need.
have_sim=no
if { [ -f managed_components/lvgl__lvgl/lvgl.h ] || [ -f simulator/.lvgl/lvgl.h ]; } &&
    command -v sdl2-config >/dev/null 2>&1; then
    have_sim=yes
fi

echo "[bisque session-start] ready."
echo "  always:   web UI build/test/lint, host C tests (make test-host),"
echo "            clang-format, docs & SVG diagrams"
if [ "$have_cppcheck" = yes ]; then
    echo "  cppcheck: make cppcheck"
else
    echo "  cppcheck: UNAVAILABLE — install failed; see the log above"
fi
if [ "$have_sim" = yes ]; then
    echo "  display:  make sim / make sim-verify (LVGL+SDL2 simulator)"
else
    echo "  display:  simulator UNAVAILABLE — see docs/cloud-dev.md"
fi
if [ "$have_idf" = yes ] && [ "$have_clang_tidy" = yes ]; then
    echo "  firmware: idf.py build + make clang-tidy (matches CI)"
elif [ "$have_idf" = yes ]; then
    echo "  firmware: idf.py build (esp-clang missing — make clang-tidy unavailable)"
else
    echo "  firmware: UNAVAILABLE — see the installer output above"
fi
if [ "$have_kicad" = yes ]; then
    echo "  pcb:      kicad-cli + pcbnew generator"
else
    # Deliberately no cause named here. A blocked host is only one way this
    # fails, and the summary cannot tell which happened: a session with the
    # Launchpad hosts allowed still lost the pipeline to add-apt-repository
    # dying on a missing apt_pkg. The installer above prints the real reason —
    # blocked hosts with a fix, or the error it actually hit.
    echo "  pcb:      UNAVAILABLE — see the installer output above"
fi
echo "  bench:    flashing and on-hardware tests always need real hardware"
