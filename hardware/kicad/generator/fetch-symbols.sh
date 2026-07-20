#!/usr/bin/env bash
# Fetch the KiCad 9 symbol libraries needed to regenerate the schematic.
# (~30 MB total; not checked into the repo. Footprints in fp/ ARE committed.)
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p sym
base="https://gitlab.com/kicad/libraries/kicad-symbols/-/raw/9.0.9.1"
for f in RF_Module Regulator_Linear Sensor_Temperature Device Connector \
         Connector_Generic Switch power Power_Protection Mechanical LED \
         Transistor_FET; do
  echo "  $f.kicad_sym"
  curl -sSL -o "sym/$f.kicad_sym" "$base/$f.kicad_sym"
done
echo "done."
