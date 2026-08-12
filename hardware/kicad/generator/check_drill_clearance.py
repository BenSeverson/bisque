#!/usr/bin/env python3
"""Hole-to-hole (drill-to-drill) clearance checker.

Why this exists, when three other checkers already look at this board:

hole-to-hole is a *mechanical* constraint at the drill, not an electrical
one. The drill bit does not know what net the copper is on, so a 0.3 mm via
crowding a 0.6 mm slot breaks out in fab whether or not both are GND. Every
other check we own is net-aware and therefore blind to it:

  * KiCad DRC applies hole-to-hole, but the pair that started this
    (J1's USB-C shield slots vs the GND stitching vias beside them) is
    same-net and was reported as nothing at all in our 9.x run.
  * check_pcb.py skips same-net pairs by construction.
  * router.py had a hole-to-hole test, but it measured centre-to-centre
    against `drill/2` — i.e. it modelled every hole as a circle. An oval
    drill is a capsule: `(drill oval 0.6 1.7)` reaches 0.55 mm further along
    its long axis than a 0.6 mm round hole does, and that is exactly the
    0.078 mm web this checker was written to catch.

So: every drilled aperture on the board is modelled as a capsule (segment +
radius) and compared with every other one, regardless of net. Pairs of pads
inside the *same* footprint are excluded — that geometry ships from the
vendor library and is not ours to fix — everything else is fair game.

Usage: check_drill_clearance.py [board.kicad_pcb] [--min MM]
Exit status 1 on any violation.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import parse, find, find_all, num  # noqa: E402

# JLCPCB's published floor (Via Hole-to-Hole Spacing) is 0.20 mm. We hold
# 0.30 mm: the failure mode is a broken-out hole discovered at the fab, and
# the cost of the margin is a stitching via moving 0.4 mm.
MIN_HOLE_TO_HOLE = 0.30


class Aperture:
    """A drilled hole as a capsule: centre segment plus a radius."""
    __slots__ = ("owner", "label", "net", "x1", "y1", "x2", "y2", "r")

    def __init__(self, owner, label, net, cx, cy, dia, length, angle):
        self.owner, self.label, self.net = owner, label, net
        self.r = dia / 2.0
        half = max(0.0, (length - dia) / 2.0)
        a = math.radians(angle)
        # KiCad's y axis points down; positive rotation is counter-clockwise
        # on screen, which is this sign convention (matches gen_pcb.rot_xy).
        dx, dy = half * math.cos(a), -half * math.sin(a)
        self.x1, self.y1 = cx - dx, cy - dy
        self.x2, self.y2 = cx + dx, cy + dy

    def centre(self):
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def web(self, other):
        """Copper-free web between the two drilled apertures (mm)."""
        return _seg_seg_dist(self.x1, self.y1, self.x2, self.y2,
                             other.x1, other.y1, other.x2, other.y2) \
            - self.r - other.r


def _pt_seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-15 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _seg_seg_dist(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    # Degenerate-friendly and exact enough at this scale: the minimum of the
    # four endpoint-to-segment distances is the true distance for
    # non-intersecting segments, and intersecting ones give 0 from an
    # endpoint test only if they touch — so test intersection too.
    if _segments_cross(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
        return 0.0
    return min(_pt_seg_dist(ax1, ay1, bx1, by1, bx2, by2),
               _pt_seg_dist(ax2, ay2, bx1, by1, bx2, by2),
               _pt_seg_dist(bx1, by1, ax1, ay1, ax2, ay2),
               _pt_seg_dist(bx2, by2, ax1, ay1, ax2, ay2))


def _segments_cross(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    def sgn(x):
        return (x > 1e-15) - (x < -1e-15)

    def cross(ox, oy, px, py, qx, qy):
        return sgn((px - ox) * (qy - oy) - (py - oy) * (qx - ox))
    d1 = cross(bx1, by1, bx2, by2, ax1, ay1)
    d2 = cross(bx1, by1, bx2, by2, ax2, ay2)
    d3 = cross(ax1, ay1, ax2, ay2, bx1, by1)
    d4 = cross(ax1, ay1, ax2, ay2, bx2, by2)
    return d1 * d2 < 0 and d3 * d4 < 0


def _rot(lx, ly, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (lx * c + ly * s, -lx * s + ly * c)


def apertures(board):
    """Every drilled hole on the board, pads and vias alike."""
    out = []
    for fp in find_all(board, "footprint"):
        at = find(fp, "at")
        fx, fy = num(at[1]), num(at[2])
        frot = num(at[3]) if len(at) > 3 else 0.0
        ref = "?"
        for pr in find_all(fp, "property"):
            if len(pr) > 2 and str(pr[1]) == "Reference":
                ref = str(pr[2])
        for p in find_all(fp, "pad"):
            kind = str(p[2])
            if kind not in ("thru_hole", "np_thru_hole"):
                continue
            dr = find(p, "drill")
            if not dr or len(dr) < 2:
                continue
            if str(dr[1]) == "oval":
                dw, dh = num(dr[2]), num(dr[3])
            else:
                dw = dh = num(dr[1])
            if dw <= 0 and dh <= 0:
                continue
            pat = find(p, "at")
            lx, ly = num(pat[1]), num(pat[2])
            prot = num(pat[3]) if len(pat) > 3 else 0.0
            # a drill offset displaces the hole from the pad's copper centre
            off = find(dr, "offset")
            if off:
                ox, oy = _rot(num(off[1]), num(off[2]), prot)
                lx, ly = lx + ox, ly + oy
            gx, gy = _rot(lx, ly, frot)
            gx, gy = gx + fx, gy + fy
            dia, length = min(dw, dh), max(dw, dh)
            # long axis lies along x when dw > dh, else along y (+90 deg)
            angle = prot + frot + (0.0 if dw >= dh else 90.0)
            netn = find(p, "net")
            net = str(netn[2]) if netn and len(netn) > 2 else ""
            out.append(Aperture(ref, "%s pad %s" % (ref, str(p[1])), net,
                                gx, gy, dia, length, angle))
    for i, v in enumerate(find_all(board, "via")):
        at = find(v, "at")
        dr = find(v, "drill")
        d = num(dr[1]) if dr and len(dr) > 1 else 0.0
        if d <= 0:
            continue
        netn = find(v, "net")
        net = str(netn[1]) if netn and len(netn) > 1 else ""
        out.append(Aperture(None, "via@(%g,%g)" % (num(at[1]), num(at[2])),
                            net, num(at[1]), num(at[2]), d, d, 0.0))
    return out


def check(path, minimum=MIN_HOLE_TO_HOLE):
    board = parse(open(path).read())[0]
    aps = apertures(board)
    # Broad-phase bucket so this stays linear-ish on a 400-via board.
    bucket = 4.0
    grid = {}
    for a in aps:
        cx, cy = a.centre()
        grid.setdefault((int(cx // bucket), int(cy // bucket)), []).append(a)
    bad = []
    seen = set()
    for a in aps:
        cx, cy = a.centre()
        bx, by = int(cx // bucket), int(cy // bucket)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for b in grid.get((bx + i, by + j), ()):
                    if a is b:
                        continue
                    key = (id(a), id(b)) if id(a) < id(b) else (id(b), id(a))
                    if key in seen:
                        continue
                    seen.add(key)
                    # same-footprint pad pairs are vendor library geometry
                    if a.owner is not None and a.owner == b.owner:
                        continue
                    w = a.web(b)
                    if w < minimum:
                        bad.append((w, a, b))
    bad.sort(key=lambda t: t[0])
    print("check_drill_clearance: %d drilled apertures, minimum web %.3f mm"
          % (len(aps), minimum))
    for (w, a, b) in bad:
        print("  !! %.3f mm  %s [%s]  <->  %s [%s]"
              % (w, a.label, a.net or "-", b.label, b.net or "-"))
    if bad:
        print("FAIL: %d hole-to-hole violation(s) below %.2f mm"
              % (len(bad), minimum))
        return 1
    print("OK: no hole-to-hole violations")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    minimum = MIN_HOLE_TO_HOLE
    if "--min" in args:
        k = args.index("--min")
        minimum = float(args[k + 1])
        del args[k:k + 2]
    board = args[0] if args else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "bisque-controller.kicad_pcb")
    sys.exit(check(board, minimum))
