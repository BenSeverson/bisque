#!/usr/bin/env bash
# Raytraced board renders via kicad-cli (KiCad 9+).
# Usage: render-3d.sh [--force] [board] [outdir]
set -euo pipefail

FORCE=0
if [ "${1:-}" = "--force" ]; then FORCE=1; shift; fi
BOARD="${1:-bisque-controller.kicad_pcb}"
OUT="${2:-3d}"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
STAMP="$OUT/.render-stamp"
mkdir -p "$OUT"

# `make pcb` runs this on every build, and kicad-cli's raytracer is NOT
# deterministic: two runs over a byte-identical board differ in 5.6% of their
# channel bytes (mean delta 89, max 255 - sampling noise, not rounding). Left
# unguarded that is a ~900 KB binary diff in git on every full build, for a
# board nobody touched, which trains you to `git checkout 3d/` reflexively -
# and one day to do it over a real change.
#
# So the renders are content-addressed instead of re-run: hash everything that
# can change a pixel and skip when it matches. Same idea as the fixture
# manifest in tests/host/, and it works here for the same reason - the board
# build is reproducible, so an unchanged design hashes identically on any
# machine. The stamp is committed so a fresh clone skips too.
#
# The board file covers placement, silk and each footprint's model reference;
# 3dmodels/ covers the geometry those references point at; this script covers
# the view, zoom and quality flags below.
want_stamp() {
  python3 - "$SELF" "$BOARD" 3dmodels <<'PY'
import hashlib, pathlib, sys

h = hashlib.sha256()
paths = [pathlib.Path(p) for p in sys.argv[1:3]]
models = pathlib.Path(sys.argv[3])
if models.is_dir():
    paths += sorted(p for p in models.rglob("*") if p.is_file())
for p in paths:
    h.update(p.name.encode())
    h.update(p.read_bytes())
print(h.hexdigest())
PY
}

WANT="$(want_stamp)"
if [ "$FORCE" -eq 0 ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANT" ] &&
  [ -f "$OUT/board-3d-top.png" ] && [ -f "$OUT/board-3d-bottom.png" ]; then
  echo "$OUT/: up to date (board, models and render flags unchanged) - skipping raytrace"
  echo "  re-render anyway with: make pcb-render FORCE=1"
  exit 0
fi

R() { kicad-cli pcb render -o "$OUT/$1" --width 1600 --height 1200 \
  --quality high --floor "${@:2}" "$BOARD"; }
# Straight orthographic top and bottom only - no --perspective, no rotation.
# The angled iso/front views were dropped: they flatter the board but you
# cannot read a designator or check a footprint off them, which is what these
# renders actually get used for. Two views also halves the raytrace.
R board-3d-top.png    --rotate '0,0,0' --zoom 0.85
R board-3d-bottom.png --side bottom --rotate '0,0,0' --zoom 0.85

# Written last: an interrupted raytrace must not stamp a half-updated 3d/.
printf '%s\n' "$WANT" >"$STAMP"
