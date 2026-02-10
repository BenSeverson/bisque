#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web_ui"
SPIFFS_DIR="$SCRIPT_DIR/spiffs_data/www"

echo "=== Building Bisque ==="

# Step 1: Build web UI
echo "--- Building Web UI ---"
cd "$WEB_DIR"
npm ci
npm run build

# Step 2: Gzip assets for SPIFFS
echo "--- Compressing web assets ---"
cd "$SPIFFS_DIR"
find . -type f \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.svg" \) \
    -exec gzip -k -9 -f {} \;

echo "--- Web UI built to $SPIFFS_DIR ---"
du -sh "$SPIFFS_DIR"

# Step 3: Build ESP-IDF firmware
echo "--- Building Firmware ---"
cd "$SCRIPT_DIR"
idf.py build

echo "=== Build Complete ==="
echo "Flash with: idf.py flash monitor"
