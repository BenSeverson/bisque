"""Every footprint either has a 3D model that RESOLVES, or is on the list.

The failure mode this exists for is silence. `kicad-cli pcb render` exits 0,
prints "Loading 3D models...", and omits any part whose model it cannot find;
a missing body reads as a footprint with no part fitted, which is also a thing
that happens on purpose. Six footprints on this board have needed a vendored
model so far and the sixth (F1) shipped in a committed render before anyone
saw it, because the reference LOOKED satisfied: KiCad's Fuse.3dshapes exists
and holds 0402 through 1210 - just not the 1812 this board uses.

Deliberately text-only, no pcbnew, so it runs in CI with the other portable
checkers. A model path is a string in the board file and resolving it is
string work; needing KiCad to answer "does this file exist" would have kept
the check out of CI, which is where the drift happens.

Usage: python3 check_3dmodels.py <board.kicad_pcb>
"""
import os
import re
import sys

# Footprints that legitimately have no 3D body. Every one is a feature of the
# copper or the drill, not a part: nothing is fitted, so nothing is missing.
# Keep this keyed on the FOOTPRINT name rather than the reference - a new test
# point should be silently fine, a new IC should not.
NO_BODY_EXPECTED = {
    "Fiducial_1mm_Mask2mm",
    "MountingHole_3.2mm_M3_Pad_Via",
    "SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
    "TestPoint_Pad_D1.0mm",
}

VARS = ("KICAD10_3DMODEL_DIR", "KICAD9_3DMODEL_DIR", "KICAD8_3DMODEL_DIR")
DEFAULT_KICAD_3D = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"


def kicad_3dmodel_dir():
    for v in VARS:
        if os.environ.get(v):
            return os.environ[v]
    for p in (DEFAULT_KICAD_3D,
              "/usr/share/kicad/3dmodels",
              "/usr/local/share/kicad/3dmodels"):
        if os.path.isdir(p):
            return p
    return None


def main(board_path):
    proj = os.path.dirname(os.path.abspath(board_path))
    k3d = kicad_3dmodel_dir()
    text = open(board_path, errors="ignore").read()

    # Walk balanced (footprint ...) blocks; each holds its reference in a
    # property and zero or more (model "path" ...) children.
    missing, nobody, checked = [], [], 0
    for m in re.finditer(r'\(footprint\s+"([^"]+)"', text):
        i = m.start()
        depth, j = 0, i
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blk = text[i:j + 1]
        fp = m.group(1).split(":", 1)[-1]
        rm = re.search(r'\(property "Reference"\s+"([^"]*)"', blk)
        ref = rm.group(1) if rm else "?"
        models = re.findall(r'\(model\s+"([^"]+)"', blk)
        if not models:
            if fp not in NO_BODY_EXPECTED:
                nobody.append((ref, fp))
            continue
        for path in models:
            checked += 1
            real = path.replace("${KIPRJMOD}", proj)
            for v in VARS:
                if k3d:
                    real = real.replace("${%s}" % v, k3d)
            if "${" in real:
                continue                       # unresolvable var, not our call
            if not os.path.exists(real):
                missing.append((ref, fp, path))

    for ref, fp, path in sorted(missing):
        print("  MISSING MODEL  %-6s %-46s %s" % (ref, fp, path))
    for ref, fp in sorted(nobody):
        print("  NO MODEL AT ALL %-6s %s" % (ref, fp))
    if missing or nobody:
        print("check_3dmodels: %d unresolvable, %d with no model - vendor it "
              "under 3dmodels/ and add a MODEL_FIXUP entry, or add the "
              "footprint to NO_BODY_EXPECTED if nothing is fitted"
              % (len(missing), len(nobody)))
        return 1
    print("check_3dmodels: OK - %d model reference(s) resolve, "
          "%d footprint(s) legitimately bodyless" % (checked, len(NO_BODY_EXPECTED)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
