#!/usr/bin/env python3
"""LCSC/EasyEDA land patterns for every part on the JLCPCB BOM.

JLCPCB's pick-and-place does not read our KiCad footprint. It places the part
using *LCSC's own* footprint for that part number, anchored at the CPL's
Mid X / Mid Y and turned by the CPL's Rotation. So the CPL is only correct if
we know how LCSC draws the land pattern — which rotation puts their pin 1 on
our pin 1, and where their footprint origin sits relative to ours.

That is a per-part fact, not a per-package one (see JLC_PLACEMENT in
gen_jlc.py), so it has to come from data. This module fetches the land pattern
from EasyEDA's public component API — the same library the JLCPCB assembly
preview renders — and caches the part of it we need in lcsc_pads.json:

    python3 generator/lcsc_pads.py --refresh     # re-fetch every BOM part
    python3 generator/lcsc_pads.py C7519         # show one part's pads

The cache is committed so check_jlc_placement.py runs offline and in CI. Only
pad centres are kept: they are what a placement is fitted from, and dropping
the silk/3D/symbol payload takes the file from ~600 KB to ~30 KB.

Coordinates are millimetres in the *visual* frame — x right, y up, origin at
the footprint's own origin — matching the frame the CPL is written in (KiCad's
y is negated on the way into a CPL). EasyEDA stores 10-mil units with y down,
which is where the 0.254 and the sign flip below come from.
"""
import json
import os
import subprocess
import sys

MIL10_MM = 0.254
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "lcsc_pads.json")
API = "https://easyeda.com/api/products/%s/components?version=6.4.19.5"


def _fetch(lcsc):
    """-> (package name, [(pad number, x, y), ...]) straight from EasyEDA."""
    out = subprocess.run(["curl", "-sS", "-m", "40", API % lcsc],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("curl failed for %s: %s" % (lcsc, out.stderr.strip()))
    doc = json.loads(out.stdout)
    if not doc.get("success"):
        raise RuntimeError("%s: EasyEDA returned no component" % lcsc)
    res = doc["result"]
    # A part's footprint lives in packageDetail; a bare footprint document (no
    # symbol) is its own dataStr.
    pkg = res.get("packageDetail") or res
    data = pkg["dataStr"]
    ox, oy = float(data["head"]["x"]), float(data["head"]["y"])
    pads = []
    for shape in data["shape"]:
        if not shape.startswith("PAD~"):
            continue
        f = shape.split("~")
        pads.append((f[8], round((float(f[2]) - ox) * MIL10_MM, 4),
                     round(-(float(f[3]) - oy) * MIL10_MM, 4)))
    name = data["head"].get("c_para", {}).get("package") or pkg.get("title", "?")
    return name, sorted(pads)


def load():
    """-> {lcsc: {"package": str, "pads": [[num, x, y], ...]}}"""
    with open(CACHE) as fh:
        return json.load(fh)["parts"]


def refresh(part_numbers):
    parts = {}
    for lcsc in sorted(part_numbers):
        name, pads = _fetch(lcsc)
        parts[lcsc] = {"package": name, "pads": [list(p) for p in pads]}
        print("  %-9s %-38s %2d pads" % (lcsc, name[:38], len(pads)))
    with open(CACHE, "w") as fh:
        json.dump({"_source": API % "<LCSC>", "parts": parts}, fh,
                  indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote %s (%d parts)" % (CACHE, len(parts)))


def main(argv):
    sys.path.insert(0, HERE)
    if "--refresh" in argv:
        from gen_jlc import LCSC, HAND_SOLDER, NOT_ASSEMBLED
        wanted = {p[0] for ref, p in LCSC.items()
                  if p[0] and ref not in HAND_SOLDER and ref not in NOT_ASSEMBLED}
        refresh(wanted)
        return 0
    parts = load()
    for lcsc in argv or sorted(parts):
        if lcsc not in parts:
            print("%s: not in %s (run --refresh)" % (lcsc, os.path.basename(CACHE)))
            return 1
        p = parts[lcsc]
        print("%s  %s" % (lcsc, p["package"]))
        for num, x, y in p["pads"]:
            print("   pad %-4s (%7.3f, %7.3f)" % (num, x, y))
    return 0


if __name__ == "__main__":
    sys.exit(main([a for a in sys.argv[1:] if not a.startswith("-")]
                  or sys.argv[1:]))
