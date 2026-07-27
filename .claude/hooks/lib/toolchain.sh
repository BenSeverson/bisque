#!/bin/bash
# "Is this toolchain actually usable?" predicates. Source, don't run.
#
# Shared by the installers and by the session-start summary so they can never
# disagree about what this container can do. Both checks are functional rather
# than presence-based, because presence is not the interesting question:
# $HOME/esp-idf/export.sh exists after a failed install, and Ubuntu ships a
# kicad-cli that is several major versions too old for the board generator.
# Reporting either as "available" sends someone off to build with a toolchain
# that will fail or, worse, silently produce the wrong artifact.

# Minimum KiCad major version the hardware/kicad generator supports.
# kicad_build.py exits outright below 10:
#     _major = int(pcbnew.Version().split(".")[0])
#     if _major < 10: sys.exit("kicad_build.py requires KiCad 10+ ...")
# so accepting 9 here would report the PCB pipeline ready and then fail on the
# very command the summary advertises.
KICAD_MIN_MAJOR=10

# toolchain_idf_ready — true if ESP-IDF activates cleanly. Reads $IDF_DIR
# (defaulting to ~/esp-idf) rather than taking an argument, so every caller
# checks the same location the installer wrote to.
#
# Runs in a subshell with IDF_PYTHON_CHECK_CONSTRAINTS unset on purpose: that
# variable is the documented escape hatch for a missing constraints file, and
# honouring it here would let a container that cannot reach dl.espressif.com
# pass as a good install while resolving Python deps differently from CI.
# Activating covers the venv, the tool paths and the constraints file at once.
toolchain_idf_ready() (
    idf_dir="${IDF_DIR:-$HOME/esp-idf}"
    [ -f "$idf_dir/export.sh" ] || return 1
    unset IDF_PYTHON_CHECK_CONSTRAINTS
    . "$idf_dir/export.sh" >/dev/null 2>&1 && command -v idf.py >/dev/null 2>&1
)

# toolchain_kicad_ready — true if kicad-cli is new enough AND pcbnew imports.
#
# The generator drives pcbnew through the system python3, so a working
# kicad-cli alone is not enough.
toolchain_kicad_ready() {
    command -v kicad-cli >/dev/null 2>&1 || return 1
    local major
    major="$(kicad-cli version 2>/dev/null | cut -d. -f1)"
    case "$major" in
    '' | *[!0-9]*) return 1 ;;
    esac
    [ "$major" -ge "$KICAD_MIN_MAJOR" ] || return 1
    python3 -c "import pcbnew" >/dev/null 2>&1
}
