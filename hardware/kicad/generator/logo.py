#!/usr/bin/env python3
"""The Bisque flame, as silkscreen geometry.

The board wears the same mark as the rest of the project: the Lucide `flame`
the web UI draws in its header and `web_ui/public/favicon.svg` ships to the
browser tab. It is carried here as **the SVG path string itself**, not as a
table of traced points, so restyling the mark is a paste rather than a
re-trace - and `check_silk.py` asserts this copy still matches the favicon's,
because a second hand-authored copy of a shared asset is exactly the thing
that goes stale silently.

Silkscreen is one colour, so the orange->red gradient tile the web mark sits
on cannot come along, and a KiCad polygon has no holes to knock the flame out
of one with. What ports is the glyph drawn the way Lucide draws it - a closed
outline stroked at 2 units in a 24-unit box - which is a `gr_poly` with
`(fill no)` and a stroke width scaled from the height. Filling it instead was
considered and rejected: the inner curl closes up, and the result stops being
the brand mark.

`points()` implements the five path commands this one path uses (M q t a c)
and raises on anything else, so a pasted path that needs more fails loudly
rather than being silently truncated to the part that parsed.
"""
import math
import re

# Verbatim from web_ui/public/favicon.svg. Lucide's `flame`, ISC-licensed -
# see web_ui/ATTRIBUTIONS.md.
FLAME_PATH = ("M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 "
              "1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4")

# Lucide's own stroke-width, in the 24-unit viewBox. Keeping the ratio rather
# than picking a millimetre width is what makes the board's flame the same
# weight as the favicon's at any size.
STROKE_UNITS = 2.0

# Flattening steps per curve or arc. The coarsest segment this produces is a
# 24th of the big semicircular arc, whose radius grows to 7 units under SVG's
# out-of-range-radii rule: a sagitta of 7*(1-cos(pi/48)) = 0.015 units, which
# at an 11 mm glyph is 0.009 mm - two orders below what a silkscreen resolves.
SEGMENTS = 24

_TOKEN = re.compile(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_ARITY = {"M": 2, "Q": 4, "T": 2, "A": 7, "C": 6}


def _commands(d):
    """[(command, [args])], with SVG's implicit repetition expanded.

    The flame's three arcs are written as one `a` with three parameter sets,
    so repetition is not optional here.
    """
    toks = _TOKEN.findall(d)
    out, i = [], 0
    while i < len(toks):
        cmd = toks[i]
        if not cmd.isalpha():
            raise ValueError("expected a command at token %d of %r" % (i, d))
        arity = _ARITY.get(cmd.upper())
        if arity is None:
            raise ValueError("unsupported SVG path command %r in %r" % (cmd, d))
        i += 1
        first = True
        while i + arity <= len(toks) and not toks[i].isalpha():
            if not first and cmd.upper() == "M":
                raise ValueError("implicit lineto after M is not supported")
            out.append((cmd, [float(v) for v in toks[i:i + arity]]))
            i += arity
            first = False
        if first:
            raise ValueError("command %r has no arguments in %r" % (cmd, d))
    return out


def _quad(p0, p1, p2, n):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in (k / float(n) for k in range(1, n + 1))]


def _cubic(p0, p1, p2, p3, n):
    return [((1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0]
             + 3 * (1 - t) * t * t * p2[0] + t ** 3 * p3[0],
             (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1]
             + 3 * (1 - t) * t * t * p2[1] + t ** 3 * p3[1])
            for t in (k / float(n) for k in range(1, n + 1))]


def _angle(ux, uy, vx, vy):
    a = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy)
                                / (math.hypot(ux, uy) * math.hypot(vx, vy)))))
    return -a if ux * vy - uy * vx < 0 else a


def _arc(p0, rx, ry, phi_deg, large, sweep, p1, n):
    """SVG's endpoint-parameterised elliptical arc, per the F.6.5 formulas."""
    if p0 == p1:
        return []
    phi = math.radians(phi_deg)
    cs, sn = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p, y1p = cs * dx2 + sn * dy2, -sn * dx2 + cs * dy2
    rx, ry = abs(rx), abs(ry)
    # F.6.6: radii too small for the endpoints are scaled up, which is what
    # turns the flame's `a1 1 ... -14 0` into the r=7 semicircle it draws as.
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1.0:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den))
    if bool(large) == bool(sweep):
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cs * cxp - sn * cyp + (p0[0] + p1[0]) / 2.0
    cy = sn * cxp + cs * cyp + (p0[1] + p1[1]) / 2.0
    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    th0 = _angle(1.0, 0.0, ux, uy)
    dth = _angle(ux, uy, vx, vy)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    out = []
    for k in range(1, n + 1):
        t = th0 + dth * k / float(n)
        out.append((cx + rx * math.cos(t) * cs - ry * math.sin(t) * sn,
                    cy + rx * math.cos(t) * sn + ry * math.sin(t) * cs))
    return out


def points(d=FLAME_PATH, n=SEGMENTS):
    """Flatten `d` to a polyline in the path's own units."""
    p = (0.0, 0.0)
    out = []
    prev_quad_ctrl = None
    for cmd, a in _commands(d):
        rel = cmd.islower()

        def at(dx, dy, _p=None):
            base = _p if _p is not None else p
            return (base[0] + dx, base[1] + dy) if rel else (dx, dy)

        up = cmd.upper()
        if up == "M":
            p = at(a[0], a[1])
            out.append(p)
            prev_quad_ctrl = None
            continue
        if up == "Q":
            c, e = at(a[0], a[1]), at(a[2], a[3])
            out += _quad(p, c, e, n)
            prev_quad_ctrl, p = c, e
        elif up == "T":
            c = (p if prev_quad_ctrl is None
                 else (2 * p[0] - prev_quad_ctrl[0], 2 * p[1] - prev_quad_ctrl[1]))
            e = at(a[0], a[1])
            out += _quad(p, c, e, n)
            prev_quad_ctrl, p = c, e
        elif up == "C":
            c1, c2, e = at(a[0], a[1]), at(a[2], a[3]), at(a[4], a[5])
            out += _cubic(p, c1, c2, e, n)
            prev_quad_ctrl, p = None, e
        else:  # A
            e = at(a[5], a[6])
            out += _arc(p, a[0], a[1], a[2], a[3], a[4], e, n)
            prev_quad_ctrl, p = None, e
    return out


def flame(cx, cy, height, d=FLAME_PATH, n=SEGMENTS):
    """The flame centred on (cx, cy), `height` mm tall.

    Returns `(points_mm, stroke_width_mm)` - a closed polyline and the width
    it wants to be stroked at. The glyph's extent is measured off the
    flattened path rather than hard-coded, so the mark can be restyled
    without a second constant going stale.
    """
    pts = points(d, n)
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    scale = height / (max(ys) - min(ys))
    ox, oy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    return ([(cx + (x - ox) * scale, cy + (y - oy) * scale) for x, y in pts],
            STROKE_UNITS * scale)


if __name__ == "__main__":
    pts, w = flame(0.0, 0.0, 11.0)
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    print("%d points, %.2f x %.2f mm, stroke %.3f mm, closed=%s"
          % (len(pts), max(xs) - min(xs), max(ys) - min(ys), w,
             all(abs(a - b) < 1e-9 for a, b in zip(pts[0], pts[-1]))))
