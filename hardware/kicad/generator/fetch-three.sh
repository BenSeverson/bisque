#!/usr/bin/env bash
# Fetch three.min.js (needed by render_3d.py) from the npm registry.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
npm pack three@0.160.0 --pack-destination "$tmp" >/dev/null
tar -xzf "$tmp"/three-0.160.0.tgz -C "$tmp" package/build/three.min.js
mv "$tmp"/package/build/three.min.js three.min.js
rm -rf "$tmp"
echo "three.min.js ready ($(wc -c < three.min.js) bytes)"
