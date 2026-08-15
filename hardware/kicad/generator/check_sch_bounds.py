#!/usr/bin/env python3
"""Assert every schematic item fits inside the declared sheet.

Every other checker in this directory validates *connectivity*, and
connectivity is complete no matter where a symbol sits on the page. That
blind spot let 57 of 141 symbols - the whole ADE7953 block, the ULN2003 aux
bank, the touch/watchdog/test-point rows - drift off the edge of the A3
sheet gen_sch.py declared. The netlist was perfect; the exported PDF, which
is a fab deliverable and the artifact a human actually reviews, was missing
roughly 40% of the circuit.

So this one checks geometry: parse the generated schematic, take the paper
size it declares, and require every placed item (symbol origin, global
label, free text, wire endpoint, no-connect) to sit inside it with a margin
that covers the symbol body and its label stubs.

Runs on kicad-cli-free plain parsing - no KiCad needed.
Usage: python3 check_sch_bounds.py <schematic.kicad_sch>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import parse, find, find_all, num

# Landscape (width, height) in mm for KiCad's named paper sizes.
PAPER = {
    "A5": (210.0, 148.0),
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "A": (279.4, 215.9),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
    "USLetter": (279.4, 215.9),
    "USLegal": (355.6, 215.9),
    "USLedger": (431.8, 279.4),
}

# Two different reservations, because the overhang is not symmetric.
#
# BORDER is KiCad's drawing frame: a 10 mm ruled border on all four sides
# that content must stay clear of on every side.
#
# REACH is the extra room the *maximum* side needs. A recorded coordinate is
# an anchor, not an extent: a global label sits at the end of its wire stub
# with its net name drawn outward from that point, so the rightmost/lowest
# item reaches further than its `at` says. 25 mm covers the longest net name
# gen_sch.py emits at 1.27 mm, and it also keeps content off the title block
# in the bottom-right corner.
BORDER = 10.0
REACH = 25.0

# Item types whose `at`/`pts` are absolute sheet coordinates. `lib_symbols`
# is skipped wholesale - the coordinates in there are symbol-local.
PLACED = ("symbol", "global_label", "label", "hierarchical_label", "text",
          "text_box", "junction", "no_connect", "wire", "polyline", "bus")


def points(item):
    """Absolute (x, y) sheet coordinates carried by one placed item."""
    out = []
    at = find(item, "at")
    if at:
        out.append((num(at[1]), num(at[2])))
    pts = find(item, "pts")
    if pts:
        for xy in find_all(pts, "xy"):
            out.append((num(xy[1]), num(xy[2])))
    return out


def label_of(item):
    kind = str(item[0])
    if kind == "symbol":
        for p in find_all(item, "property"):
            if str(p[1]) == "Reference":
                return str(p[2])
    for x in item[1:]:
        if isinstance(x, str) and not isinstance(x, type(item[0])):
            return kind + ' "' + x[:40] + '"'
    return kind


def main(sch):
    doc = parse(open(sch).read())[0]
    paper = find(doc, "paper")
    if not paper:
        sys.exit("no (paper ...) in %s" % sch)
    name = str(paper[1])
    if name == "User":
        w, h = num(paper[2]), num(paper[3])
    elif name in PAPER:
        w, h = PAPER[name]
        # KiCad writes `portrait` after the name to swap the axes.
        if any(str(x) == "portrait" for x in paper[2:]):
            w, h = h, w
    else:
        sys.exit("unknown paper size %r" % name)

    x0, y0 = BORDER, BORDER
    x1, y1 = w - BORDER - REACH, h - BORDER - REACH
    bad = []
    maxx = maxy = 0.0
    for item in doc:
        if not isinstance(item, list) or not item:
            continue
        if str(item[0]) not in PLACED:
            continue
        for (px, py) in points(item):
            maxx, maxy = max(maxx, px), max(maxy, py)
            if not (x0 <= px <= x1 and y0 <= py <= y1):
                bad.append((label_of(item), px, py))

    print("paper %s = %.1f x %.1f mm; usable box x %.1f..%.1f y %.1f..%.1f "
          "(border %.0f, label reach %.0f)"
          % (name, w, h, x0, x1, y0, y1, BORDER, REACH))
    print("content extends to x=%.1f y=%.1f" % (maxx, maxy))
    if bad:
        for ref, px, py in sorted(set(bad)):
            print("OFF-SHEET %s at (%.1f, %.1f)" % (ref, px, py))
        print("%d off-sheet items (%d distinct) - the exported PDF will clip"
              % (len(bad), len(set(r for r, _, _ in bad))))
        return 1
    print("check_sch_bounds: all placed items inside the sheet")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "bisque-controller.kicad_sch"))
