#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web_ui"
SPIFFS_DIR="$SCRIPT_DIR/spiffs_data/www"

export BISQUE_VERSION="${BISQUE_VERSION:-$("$SCRIPT_DIR/scripts/version.sh")}"

# Build profile: release (default, -O2) or debug (-Og + LVGL perf/mem overlays).
# CMakeLists.txt reads BISQUE_PROFILE from env and inserts the matching
# sdkconfig.defaults.* file into SDKCONFIG_DEFAULTS, so we just need to export.
export BISQUE_PROFILE="${BISQUE_PROFILE:-release}"
case "$BISQUE_PROFILE" in
    release|debug) ;;
    *) echo "error: BISQUE_PROFILE must be 'release' or 'debug' (got '$BISQUE_PROFILE')" >&2; exit 1 ;;
esac

# IDF only merges sdkconfig.defaults when sdkconfig doesn't exist, and CMake
# caches SDKCONFIG_DEFAULTS in build/CMakeCache.txt. To make profile switches
# (and edits to the defaults files) actually take effect, clear sdkconfig and
# the build tree when the marker doesn't match — including when it's absent,
# which is the case after a stale/aborted build or after editing the defaults.
PROFILE_MARKER="$SCRIPT_DIR/.bisque_profile"
if [ ! -f "$PROFILE_MARKER" ] || [ "$(cat "$PROFILE_MARKER")" != "$BISQUE_PROFILE" ]; then
    prev=$([ -f "$PROFILE_MARKER" ] && cat "$PROFILE_MARKER" || echo "<none>")
    echo "--- Profile $prev -> $BISQUE_PROFILE; clearing sdkconfig + build/ to force defaults merge ---"
    rm -f "$SCRIPT_DIR/sdkconfig"
    rm -rf "$SCRIPT_DIR/build"
fi
echo "$BISQUE_PROFILE" > "$PROFILE_MARKER"

echo "=== Building Bisque $BISQUE_VERSION (profile: $BISQUE_PROFILE) ==="

# Step 1: Build web UI
echo "--- Building Web UI ---"
cd "$WEB_DIR"
npm ci
npm run build

# Step 2: Gzip assets for SPIFFS (remove originals to fit partition)
echo "--- Compressing web assets ---"
cd "$SPIFFS_DIR"
find . -type f \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.svg" \) \
    -exec gzip -9 -f {} \;

echo "--- Web UI built to $SPIFFS_DIR ---"
du -sh "$SPIFFS_DIR"

# Step 3: Build ESP-IDF firmware
echo "--- Building Firmware ---"
cd "$SCRIPT_DIR"
# shellcheck source=scripts/idf-env.sh
. "$SCRIPT_DIR/scripts/idf-env.sh"
idf.py build

echo "=== Build Complete ==="
echo "Flash with: idf.py flash monitor"
