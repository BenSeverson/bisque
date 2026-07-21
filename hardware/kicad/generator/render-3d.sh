#!/usr/bin/env bash
# Raytraced board renders via kicad-cli (KiCad 9+). Usage: render-3d.sh [board] [outdir]
set -euo pipefail
BOARD="${1:-bisque-controller.kicad_pcb}"
OUT="${2:-3d}"
mkdir -p "$OUT"
R() { kicad-cli pcb render -o "$OUT/$1" --width 1600 --height 1200 \
       --quality high --floor "${@:2}" "$BOARD"; }
R board-3d-iso.png   --perspective --rotate '-40,0,30' --zoom 0.9
R board-3d-front.png --perspective --rotate '-75,0,0'  --zoom 0.95
R board-3d-top.png   --rotate '0,0,0' --zoom 0.85
R board-3d-back.png  --side bottom --rotate '30,0,-20' --perspective --zoom 0.9
