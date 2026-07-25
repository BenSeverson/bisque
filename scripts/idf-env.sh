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

# Newest version first. Both GNU and BSD/macOS sort accept -V; degrade to
# lexical order rather than dropping every candidate if some minimal
# environment lacks it. Note that ESP-IDF's own export.sh calls `sort -V` and
# exits without it, so this fallback only ever buys discovery, not a build.
_idf_vsort() {
    if printf 'v1\n' | sort -V >/dev/null 2>&1; then
        sort -V -r
    else
        sort -r
    fi
}

# export.sh exports these three together, so their presence is what actually
# proves a shell is activated.
#
# `command -v idf.py` does NOT prove it. PATH is inherited by every child
# process, but the rest of the environment need not travel with it — a desktop
# app or agent launched from an already-activated terminal, `env` with a
# curated allowlist, or a Dockerfile that pins only `ENV PATH` all yield a
# shell that finds idf.py while IDF_PATH and friends are unset. Treating that
# as activated is how `make firmware` used to die in idf_component_manager:
#   TypeError: expected string or bytes-like object, got 'NoneType'
# — that is Version.coerce(os.getenv('ESP_IDF_VERSION')) on a NULL.
#
# Re-activating an already-good environment is only a few wasted seconds;
# skipping activation on a half-set-up one is a build failure, so this check
# errs toward re-running export.sh.
_idf_activated() {
    [ -n "${IDF_PATH:-}" ] &&
        [ -n "${IDF_PYTHON_ENV_PATH:-}" ] &&
        [ -n "${ESP_IDF_VERSION:-}" ] &&
        command -v idf.py >/dev/null 2>&1
}

# The `|| :` matters twice over: this runs last on the success path and a
# sourced script's status is its last command's, and zsh's `unset -f` returns
# non-zero for a name that is already gone — which under `set -e` (build.sh
# uses it) aborts the caller mid-source and breaks `. idf-env.sh && idf.py`.
_idf_cleanup() {
    unset -f _idf_vsort _idf_activated _idf_cleanup 2>/dev/null || :
}

_idf_root=""

# Nothing to do for a genuinely activated shell (interactive session, container
# env) as long as IDF_PATH still names the install that is on PATH — export.sh
# prepends $IDF_PATH/tools, so that entry is what identifies the active one.
# A caller who points IDF_PATH at a *different* install falls through and gets
# it activated, rather than silently building with the one already on PATH.
if _idf_activated; then
    case ":$PATH:" in
    *":$IDF_PATH/tools:"*)
        _idf_cleanup
        return 0 2>/dev/null || exit 0
        ;;
    esac
fi

if [ -n "${IDF_PATH:-}" ]; then
    # An explicit override outranks whatever happens to be on PATH — otherwise
    # a shell already activated for another install would silently build with
    # the wrong toolchain while IDF_PATH advertised the requested one.
    if [ ! -f "$IDF_PATH/export.sh" ]; then
        echo "idf-env: IDF_PATH is set to '$IDF_PATH', which has no export.sh." >&2
        echo "  Point it at an ESP-IDF install, or unset it to search the usual locations." >&2
        _idf_cleanup
        return 1 2>/dev/null || exit 1
    fi
    _idf_root=$IDF_PATH
else
    # idf.py can be on PATH without the environment being activated (see
    # _idf_activated). That install is the one the caller is expecting, so
    # prefer it over the location search below: idf.py lives at
    # $IDF_PATH/tools/idf.py, so its grandparent is the install root. A shim
    # elsewhere on PATH won't have export.sh there and falls through.
    _idf_py=$(command -v idf.py 2>/dev/null) || _idf_py=""
    if [ -n "$_idf_py" ]; then
        _c=$(dirname "$(dirname "$_idf_py")")
        if [ -f "$_c/export.sh" ]; then
            _idf_root=$_c
        fi
    fi
    unset _idf_py

    # Installs accumulate by version, so take the newest within each layout:
    #   ~/esp-idf              this repo's cloud installer, espressif/idf images
    #   ~/esp/...              the classic git-clone + install.sh layout
    #   ~/.espressif/v*/...    the ESP-IDF Installer / eim / IDE layout
    #   /opt/...               system-wide and Docker installs
    if [ -z "$_idf_root" ]; then
        for _c in \
            "$HOME/esp-idf" \
            $(ls -d "$HOME"/esp/v*/esp-idf 2>/dev/null | _idf_vsort) \
            "$HOME/esp/esp-idf" \
            $(ls -d "$HOME"/.espressif/v*/esp-idf 2>/dev/null | _idf_vsort) \
            "/opt/esp/idf" \
            "/opt/esp-idf"; do
            if [ -f "$_c/export.sh" ]; then
                _idf_root=$_c
                break
            fi
        done
    fi
    unset _c
fi

if [ -z "$_idf_root" ]; then
    echo "idf-env: no ESP-IDF install found." >&2
    echo "  Install it (https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/get-started/)" >&2
    echo "  or point IDF_PATH at an existing one, then re-run." >&2
    unset _idf_root
    _idf_cleanup
    return 1 2>/dev/null || exit 1
fi

# export.sh needs IDF_PATH set when the caller invokes it from outside the
# install tree.
IDF_PATH=$_idf_root
export IDF_PATH
unset _idf_root

# export.sh prints a banner we don't want in build logs, but discarding it
# outright leaves nothing to debug when activation fails, so keep it in a log
# and surface it only on failure. Note that a hard enough failure (no python3
# >= 3.10 on PATH, no `sort -V`) makes export.sh call `exit`, which tears down
# this shell before we get control back — that is ESP-IDF's behaviour and a
# sourced script cannot intercept it.
_idf_log="${TMPDIR:-/tmp}/idf-env-$$.log"
_idf_rc=0
. "$IDF_PATH/export.sh" >"$_idf_log" 2>&1 || _idf_rc=$?

# Only idf.py-on-PATH is fatal here: IDF_PYTHON_ENV_PATH and ESP_IDF_VERSION
# are what _idf_activated wants for next time, but older installs export
# fewer of them and still build fine. Those shells simply re-activate on every
# invocation instead of taking the no-op path.
if [ "$_idf_rc" -ne 0 ] || ! command -v idf.py >/dev/null 2>&1; then
    echo "idf-env: $IDF_PATH/export.sh did not put idf.py on PATH (exit $_idf_rc)." >&2
    sed 's/^/  | /' "$_idf_log" >&2
    echo "  Run '$IDF_PATH/install.sh esp32s3' to install the toolchain." >&2
    rm -f "$_idf_log"
    unset _idf_log _idf_rc
    _idf_cleanup
    return 1 2>/dev/null || exit 1
fi

rm -f "$_idf_log"
unset _idf_log _idf_rc
_idf_cleanup
