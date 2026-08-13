#!/usr/bin/env bash
# Raytraced board renders via kicad-cli (KiCad 9+). Usage: render-3d.sh [board] [outdir]
set -euo pipefail
BOARD="${1:-bisque-controller.kicad_pcb}"
OUT="${2:-3d}"
mkdir -p "$OUT"
R() { kicad-cli pcb render -o "$OUT/$1" --width 1600 --height 1200 \
       --quality high --floor "${@:2}" "$BOARD"; }
# Straight orthographic top and bottom only - no --perspective, no rotation.
# The angled iso/front views were dropped: they flatter the board but you
# cannot read a designator or check a footprint off them, which is what these
# renders actually get used for. Two views also halves the raytrace.
R board-3d-top.png    --rotate '0,0,0' --zoom 0.85
R board-3d-bottom.png --side bottom --rotate '0,0,0' --zoom 0.85
