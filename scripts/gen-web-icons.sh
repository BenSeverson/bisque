#!/usr/bin/env bash
# Rasterize the web UI's PWA icons from their SVG sources.
#
# The outputs are committed under web_ui/public/ — this script only needs to run
# when web_ui/icons/*.svg changes, so it is deliberately not wired into
# build.sh or CI (which would put an SVG rasterizer on the critical path of
# every firmware build).
#
# favicon.svg is hand-written and shipped as-is; nothing here touches it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/web_ui/icons"
OUT="$ROOT/web_ui/public"

# Pick whatever rasterizer this machine has. rsvg-convert and cairosvg are the
# portable options; sips ships with macOS and needs no install, which is why it
# is here at all.
if command -v rsvg-convert >/dev/null 2>&1; then
    RASTERIZER=rsvg-convert
elif python3 -c "import cairosvg" >/dev/null 2>&1; then
    RASTERIZER=cairosvg
elif command -v sips >/dev/null 2>&1; then
    RASTERIZER=sips
else
    echo "error: need one of rsvg-convert, python3-cairosvg, or sips" >&2
    echo "  brew install librsvg   # or:  pip install cairosvg" >&2
    exit 1
fi
echo "Rasterizing with $RASTERIZER"

render() {  # render <source.svg> <size> <dest.png>
    local svg="$1" size="$2" dest="$3"
    case "$RASTERIZER" in
        rsvg-convert)
            rsvg-convert -w "$size" -h "$size" "$svg" -o "$dest"
            ;;
        cairosvg)
            python3 -c "import cairosvg,sys; cairosvg.svg2png(url=sys.argv[1], output_width=int(sys.argv[2]), output_height=int(sys.argv[2]), write_to=sys.argv[3])" \
                "$svg" "$size" "$dest"
            ;;
        sips)
            sips -s format png --resampleHeightWidth "$size" "$size" "$svg" --out "$dest" >/dev/null
            ;;
    esac
    printf "  %-24s %sx%s  %s bytes\n" "$(basename "$dest")" "$size" "$size" "$(wc -c < "$dest" | tr -d ' ')"
}

# PNG fallback for the favicon: Safari only gained SVG favicon support in 16.4,
# and the LAN clients here include whatever tablet is propped up in the studio.
# Rendered from favicon.svg, not app-icon.svg — favicon.svg is the variant with
# the heavier stroke and its own rounded corners, both of which a 32px tab icon
# needs and an OS-masked app icon does not.
render "$OUT/favicon.svg"           32 "$OUT/favicon-32.png"
# 180 is the size iOS actually asks for; anything else gets rescaled on device.
render "$SRC/app-icon.svg"         180 "$OUT/apple-touch-icon.png"
render "$SRC/app-icon.svg"         192 "$OUT/icon-192.png"
render "$SRC/app-icon.svg"         512 "$OUT/icon-512.png"
render "$SRC/app-icon-maskable.svg" 512 "$OUT/icon-maskable-512.png"

echo "Optimizing"
python3 "$ROOT/scripts/optimize_png.py" \
    "$OUT/favicon-32.png" "$OUT/apple-touch-icon.png" \
    "$OUT/icon-192.png" "$OUT/icon-512.png" "$OUT/icon-maskable-512.png"

echo "Wrote icons to $OUT"
