#!/usr/bin/env bash
# Fetch the KiCad 9 symbol libraries needed to regenerate the schematic.
# (~30 MB total; not checked into the repo. Footprints in fp/ ARE committed.)
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p sym
base="https://gitlab.com/kicad/libraries/kicad-symbols/-/raw/9.0.9.1"
# Every lib named by a design.COMPONENTS entry, plus `power` for the rail
# ports. Six of these (Isolator, Jumper, Oscillator, Regulator_Switching,
# Sensor, Transistor_Array) were missing until 2026-09-21 - the list is only
# exercised on a machine with no KiCad installed, since _find_sym_base()
# prefers the installed library, so drift here is invisible locally. Check it
# against:  python3 -c "from design import COMPONENTS;
#                       print(sorted({d['lib'] for d in COMPONENTS.values()}))"
for f in RF_Module Regulator_Linear Regulator_Switching Sensor \
         Sensor_Temperature Device Connector Isolator Jumper Oscillator \
         Connector_Generic Connector_Generic_MountingPin Switch power 74xGxx \
         Power_Protection Mechanical LED Transistor_FET Transistor_Array; do
  echo "  $f.kicad_sym"
  curl -sSL -o "sym/$f.kicad_sym" "$base/$f.kicad_sym"
done
echo "done."
