#!/usr/bin/env python3
"""Assert gen_jlc.py's JLC_PLACEMENT agrees with LCSC's real land patterns.

JLCPCB places each part with *its own* LCSC footprint, not ours: the CPL's
Mid X / Mid Y anchors LCSC's footprint origin and Rotation turns LCSC's pin 1.
So a correct CPL needs, per part, the rotation and the origin delta that make
LCSC's land pattern land on ours. gen_jlc.py carries those as a table; this
re-derives them from data and fails if the two disagree.

The derivation fits LCSC's pad centres (lcsc_pads.json, from EasyEDA's public
component API) onto the KiCad footprint's pad centres at each 90 degree step,
solving for the translation and reporting the worst per-pad residual. The
rotation with the smallest residual wins.

    python3 generator/check_jlc_placement.py            # verify the table
    python3 generator/check_jlc_placement.py --derive   # print it to paste

Two things the fit cannot see on its own, both of which have already produced
a wrong answer here, are handled explicitly:

  * Pad *numbering* is a library convention, not a physical fact. LCSC numbers
    an LED's anode 1; KiCad numbers its cathode 1. Fitting numbers alone would
    "correct" every LED by 180 degrees and mount all of them backwards - the
    parts are physically already aligned. PIN_REMAP states such differences,
    each one read off the LCSC symbol's own pin names.
  * A pad number that appears more than once can mean different things on each
    side (KiCad's SOT-223_TabPin2 numbers the tab 2, LCSC numbers it 4), so a
    number whose instances are not clustered is dropped from the fit rather
    than averaged into a meaningless centroid.

A land pattern that simply differs in pad *size* between the two libraries is
not a placement error - the part still centres correctly - so those are
reported as a residual warning and allowlisted in SHAPE_DIFFERS.
"""
import glob
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lcsc_pads
from design import COMPONENTS
from gen_jlc import JLC_PLACEMENT, LCSC, HAND_SOLDER, NOT_ASSEMBLED, jlc_placement

# LCSC pad number -> our pad number, where the two libraries number the same
# physical pin differently. Read off the LCSC symbol's pin names.
PIN_REMAP = {
    # LED symbols: LCSC pin 1 is the anode ("A" / "+"), KiCad's is the cathode.
    "C2296": {"1": "2", "2": "1"},   # 17-21SUYC/TR8, pins named +/-
    "C2297": {"1": "2", "2": "1"},   # 0805G green, pins named A/K
}

# Parts whose two libraries draw a different-sized land for the same package,
# so pads cannot coincide however the part is placed. Placement is still
# correct as long as the fitted translation is zero. An entry here that is no
# longer needed is an error, not a harmless leftover.
SHAPE_DIFFERS = {
    "C7471632": "we use the HandSoldering HC49-SD land, whose pads reach "
                "1.4 mm further out than LCSC's reflow-size ones",
}

STEPS = (0, 90, 180, 270)
FIT_TOL = 0.5      # mm, worst per-pad residual before we call the fit poor
OFFSET_TOL = 0.02  # mm, agreement required with the table's dx/dy
CLUSTER = 1.0      # mm, spread above which a repeated pad number is dropped

# Below this the two footprints share an origin and differ only in how big a
# land they draw around it, which no placement can fix - moving the part just
# trades an overhang on one row for an overhang on the opposite one. Quantising
# here rather than in the table keeps the two agreeing by construction. The
# real origin differences on this board are 0.48 mm and 1.57 mm, so the floor
# is nowhere near them.
OFFSET_FLOOR = 0.25


def find_footprint_dir():
    cand = [os.environ.get("KICAD_FOOTPRINT_DIR", ""),
            "/usr/share/kicad/footprints",
            "/usr/local/share/kicad/footprints",
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
            r"C:\Program Files\KiCad\10.0\share\kicad\footprints"]
    cand += sorted(glob.glob("/usr/share/kicad*/footprints"), reverse=True)
    for c in cand:
        if c and os.path.isdir(c):
            return c
    sys.exit("KiCad footprint libraries not found - set KICAD_FOOTPRINT_DIR")


FPBASE = find_footprint_dir()
PAD_RE = re.compile(r'\(pad\s+"([^"]*)"\s+(\S+)\s+\S+[^\n]*\n\s*\(at\s+'
                    r'([-\d.]+)\s+([-\d.]+)')


def kicad_pads(fpref):
    """-> [(pad number, x, y)] in the visual frame (y up), origin at the anchor."""
    lib, name = fpref.split(":", 1)
    path = os.path.join(FPBASE, lib + ".pretty", name + ".kicad_mod")
    with open(path) as fh:
        src = fh.read()
    return [(m.group(1), float(m.group(3)), -float(m.group(4)))
            for m in PAD_RE.finditer(src) if m.group(2) != "np_thru_hole"]


def rotate(pads, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(n, x * c - y * s, x * s + y * c) for n, x, y in pads]


def clustered_centroids(pads):
    """-> {number: (x, y)}, dropping numbers whose instances are far apart."""
    by = defaultdict(list)
    for n, x, y in pads:
        by[n].append((x, y))
    out = {}
    for n, pts in by.items():
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        if max(math.hypot(p[0] - cx, p[1] - cy) for p in pts) <= CLUSTER:
            out[n] = (cx, cy)
    return out


def fit_numbered(lcsc, kicad, deg):
    a, b = clustered_centroids(rotate(lcsc, deg)), clustered_centroids(kicad)
    common = sorted(set(a) & set(b))
    if len(common) < 2:
        return None
    dx = sum(b[n][0] - a[n][0] for n in common) / len(common)
    dy = sum(b[n][1] - a[n][1] for n in common) / len(common)
    resid = max(math.hypot(b[n][0] - a[n][0] - dx, b[n][1] - a[n][1] - dy)
                for n in common)
    return dx, dy, resid, "%d pin#" % len(common)


def fit_anonymous(lcsc, kicad, deg):
    """Nearest-neighbour translation fit, for libraries that share no pad names."""
    a, b = rotate(lcsc, deg), kicad
    dx = sum(p[1] for p in b) / len(b) - sum(p[1] for p in a) / len(a)
    dy = sum(p[2] for p in b) / len(b) - sum(p[2] for p in a) / len(a)
    pairs = []
    for _ in range(8):
        pairs = []
        for _, x, y in a:
            u, v = x + dx, y + dy
            m = min(b, key=lambda t: math.hypot(t[1] - u, t[2] - v))
            pairs.append((m[1] - x, m[2] - y))
        ndx = sum(p[0] for p in pairs) / len(pairs)
        ndy = sum(p[1] for p in pairs) / len(pairs)
        if abs(ndx - dx) < 1e-9 and abs(ndy - dy) < 1e-9:
            break
        dx, dy = ndx, ndy
    resid = max(math.hypot(p[0] - dx, p[1] - dy) for p in pairs)
    return dx, dy, resid, "%d shape" % len(a)


def derive(lcsc_part, fpref, pads):
    """-> (rotation, dx, dy, residual, how) mapping LCSC's land onto ours."""
    remap = PIN_REMAP.get(lcsc_part, {})
    lp = [(remap.get(n, n), x, y) for n, x, y in pads]
    kp = kicad_pads(fpref)
    if not lp or not kp:
        return None
    best = None
    for deg in STEPS:
        r = fit_numbered(lp, kp, deg) or fit_anonymous(lp, kp, deg)
        if best is None or r[2] < best[1][2]:
            best = (deg, r)
    deg, (dx, dy, resid, how) = best
    if math.hypot(dx, dy) < OFFSET_FLOOR:
        dx = dy = 0.0
    return deg, round(dx, 3), round(dy, 3), resid, how


def assembled():
    for ref, c in COMPONENTS.items():
        if ref in NOT_ASSEMBLED or ref in HAND_SOLDER:
            continue
        part = LCSC.get(ref)
        if part and part[0]:
            yield ref, part[0], c


def main(argv):
    parts = lcsc_pads.load()
    derived, missing, rows = {}, [], []
    for ref, lcsc, c in assembled():
        if lcsc not in parts:
            missing.append((ref, lcsc))
            continue
        d = derive(lcsc, c["fp"], [tuple(p) for p in parts[lcsc]["pads"]])
        if d is None:
            missing.append((ref, lcsc))
            continue
        derived.setdefault(lcsc, (d, c["fp"], ref))
        rows.append((ref, lcsc, c["fp"].split(":", 1)[1], d))

    if "--derive" in argv:
        print("JLC_PLACEMENT = {")
        for lcsc, ((deg, dx, dy, resid, how), fp, ref) in sorted(derived.items()):
            key = '"%s":' % lcsc
            print('    %-11s (%3d, %6.3f, %6.3f),   # %-5s %-36s resid %.3f (%s)'
                  % (key, deg, dx, dy, ref, fp.split(":", 1)[1][:36], resid, how))
        print("}")
        return 0

    bad, warn = [], []
    # The table is keyed by part number alone, so the same part on two
    # different footprints has no single right answer to record.
    footprints = defaultdict(set)
    for ref, lcsc, fp, _ in rows:
        footprints[lcsc].add(fp)
    for lcsc, fps in sorted(footprints.items()):
        if len(fps) > 1:
            bad.append("%-9s is placed on %d different footprints (%s) - "
                       "JLC_PLACEMENT cannot express that"
                       % (lcsc, len(fps), ", ".join(sorted(fps))))

    # Rotation and origin are facts about a land pattern, so they are checked
    # once per LCSC part rather than once per designator.
    for lcsc, ((deg, dx, dy, resid, how), fp, ref) in sorted(derived.items()):
        fp = fp.split(":", 1)[1]
        want = JLC_PLACEMENT.get(lcsc)
        if want is None:
            bad.append("%-9s (%s, %s) has no JLC_PLACEMENT entry" % (lcsc, ref, fp))
            continue
        wrot, wdx, wdy = want[:3]
        if deg != wrot % 360:
            bad.append("%-9s (%s, %s) rotation: table says %d, LCSC's land "
                       "fits at %d" % (lcsc, ref, fp, wrot, deg))
        if abs(dx - wdx) > OFFSET_TOL or abs(dy - wdy) > OFFSET_TOL:
            bad.append("%-9s (%s, %s) origin delta: table says (%.3f, %.3f), "
                       "fit says (%.3f, %.3f)" % (lcsc, ref, fp, wdx, wdy, dx, dy))
        if resid > FIT_TOL and lcsc not in SHAPE_DIFFERS:
            warn.append("%-9s (%s, %s) worst pad off by %.3f mm - land patterns "
                        "differ; confirm and add to SHAPE_DIFFERS"
                        % (lcsc, ref, fp, resid))

    # The table being right is no use if gen_jlc misapplies it, so check the
    # angle it actually emits for every designator.
    for ref, lcsc, fp, _ in rows:
        want = JLC_PLACEMENT.get(lcsc)
        if want is None:
            continue
        board_rot = COMPONENTS[ref]["at"][2]
        jrot = jlc_placement(lcsc, board_rot)[0]
        if jrot != (board_rot + want[0]) % 360:
            bad.append("%-5s gen_jlc emitted %.0f, expected %.0f"
                       % (ref, jrot, (board_rot + want[0]) % 360))

    stale = sorted(set(JLC_PLACEMENT) - set(derived))
    for lcsc in stale:
        bad.append("%-9s in JLC_PLACEMENT but on no assembled part" % lcsc)
    worst = {lcsc: d[3] for lcsc, (d, _, _) in derived.items()}
    for lcsc in sorted(SHAPE_DIFFERS):
        if lcsc not in derived:
            bad.append("%-9s in SHAPE_DIFFERS but on no assembled part" % lcsc)
        elif worst[lcsc] <= FIT_TOL:
            bad.append("%-9s in SHAPE_DIFFERS but its land now fits to %.3f mm "
                       "- drop the entry" % (lcsc, worst[lcsc]))
    for ref, lcsc in missing:
        bad.append("%-5s %-9s not in lcsc_pads.json - run "
                   "generator/lcsc_pads.py --refresh" % (ref, lcsc))

    for w in warn:
        print("warning: %s" % w)
    if bad:
        print("check_jlc_placement: %d problem(s)" % len(bad))
        for b in bad:
            print("  %s" % b)
        return 1
    corrected = sum(1 for lcsc, (d, _, _) in derived.items()
                    if d[0] or abs(d[1]) > OFFSET_TOL or abs(d[2]) > OFFSET_TOL)
    print("check_jlc_placement: OK - %d parts / %d LCSC land patterns fitted, "
          "%d need a correction" % (len(rows), len(derived), corrected))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
