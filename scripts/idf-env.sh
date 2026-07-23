# shellcheck shell=sh
# Source this to put ESP-IDF on PATH:
#
#     . ./scripts/idf-env.sh && idf.py build
#
# A plain `idf.py` only works in a shell that has already sourced ESP-IDF's
# export.sh. Interactive shells usually have, via a get_idf alias or a line in
# ~/.zshrc — but non-interactive ones (agent tool calls, git hooks, CI, `make`
# recipes) read no rc files and get a fresh shell each time, so they never do.
# This script finds a local install and activates it, and no-ops when the
# environment is already set up.
#
# Set IDF_PATH to override the search. Sourced by build.sh and the Makefile;
# cloud sessions are handled separately by .claude/hooks/install-esp-idf.sh.

# Already active (interactive shell, container env, or a PATH shim) — done.
if command -v idf.py >/dev/null 2>&1; then
    return 0 2>/dev/null || exit 0
fi

_idf_root=""

# Explicit override wins.
if [ -n "${IDF_PATH:-}" ] && [ -f "$IDF_PATH/export.sh" ]; then
    _idf_root=$IDF_PATH
else
    # Newest first within each layout, since installs accumulate by version:
    #   ~/esp-idf              this repo's cloud installer, espressif/idf images
    #   ~/esp/...              the classic git-clone + install.sh layout
    #   ~/.espressif/v*/...    the ESP-IDF Installer / eim / IDE layout
    #   /opt/...               system-wide and Docker installs
    for _c in \
        "$HOME/esp-idf" \
        $(ls -d "$HOME"/esp/v*/esp-idf 2>/dev/null | sort -V -r) \
        "$HOME/esp/esp-idf" \
        $(ls -d "$HOME"/.espressif/v*/esp-idf 2>/dev/null | sort -V -r) \
        "/opt/esp/idf" \
        "/opt/esp-idf"; do
        if [ -f "$_c/export.sh" ]; then
            _idf_root=$_c
            break
        fi
    done
    unset _c
fi

if [ -z "$_idf_root" ]; then
    echo "idf-env: no ESP-IDF install found." >&2
    echo "  Install it (https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/get-started/)" >&2
    echo "  or point IDF_PATH at an existing one, then re-run." >&2
    unset _idf_root
    return 1 2>/dev/null || exit 1
fi

# export.sh needs IDF_PATH set when the caller invokes it from outside the
# install tree, and prints a banner we don't want in build logs.
IDF_PATH=$_idf_root
export IDF_PATH
unset _idf_root

if ! . "$IDF_PATH/export.sh" >/dev/null 2>&1 || ! command -v idf.py >/dev/null 2>&1; then
    echo "idf-env: $IDF_PATH/export.sh did not put idf.py on PATH." >&2
    echo "  Run '$IDF_PATH/install.sh esp32s3' to install the toolchain." >&2
    return 1 2>/dev/null || exit 1
fi
