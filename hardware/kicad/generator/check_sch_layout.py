#!/usr/bin/env python3
"""Assert nothing on the schematic sheet is drawn on top of anything else.

`check_sch_bounds.py` proved every item is *inside* the sheet. Containment is
not readability: the rev B schematic passed it while the 20-line NOTES block
printed straight through the AUX OUTPUT BANK header and over U6/J10, and half
the group headers sat inside their own parts. The netlist was perfect and the
PDF - the document a human reads before committing the board to fabrication -
was unreviewable.

So this one checks *occupancy*. Three collision classes, all net-independent:

  symbol <-> symbol   two parts drawn over each other
  text   <-> symbol   free text (group header / notes) printed over a part
  text   <-> text     two blocks of prose printed over each other

Extents are estimates, deliberately biased LARGER than the truth so a miss is
a false alarm rather than a silent overlap:

  * a symbol's extent is its library body (graphics + pin reach) unioned with
    the boxes of its visible Reference and Value fields;
  * a text's extent is line-count x line height by longest-line x char width
    at the emitted font size, anchored the way KiCad anchors it (horizontally
    per `justify`, vertically centred on the whole block).

Global labels and wires are deliberately NOT checked. They are dense by
design in this netlist-style schematic, and their real hazard - two stubs
landing on the same point and silently merging two nets - is what
`check_netlist.py` catches by round-tripping through KiCad.

Runs on plain parsing - no KiCad needed.
Usage: python3 check_sch_layout.py [schematic.kicad_sch]
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import parse, find, find_all, num

# Stroke-font metrics, in multiples of the font size. KiCad's newstroke
# advance runs about 0.6-0.75 em depending on the glyph and its interline is
# about 1.6 em; both of these round up from that so an estimated box is never
# smaller than what is actually plotted.
CHAR_W = 0.80
LINE_H = 1.70

# Two boxes touching exactly (a shared edge) is not an overlap. Require this
# much real interpenetration before reporting, so floating-point noise and
# deliberately abutting geometry stay quiet.
EPS = 0.05


def unescape(s):
    """KiCad string escapes -> the text actually plotted."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            c = s[i + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(c, c))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def text_box(txt, x, y, size, justify):
    """Sheet-coordinate box for a (possibly multi-line) text anchored at x,y."""
    lines = unescape(txt).split("\n") or [""]
    w = max(len(ln) for ln in lines) * size * CHAR_W
    h = len(lines) * size * LINE_H
    if "right" in justify:
        x0 = x - w
    elif "left" in justify:
        x0 = x
    else:
        x0 = x - w / 2.0
    # KiCad centres a multi-line block on the anchor unless told otherwise.
    if "top" in justify:
        y0 = y
    elif "bottom" in justify:
        y0 = y - h
    else:
        y0 = y - h / 2.0
    return (x0, y0, x0 + w, y0 + h)


def effects_of(item):
    """(font size, justify tokens) for an item's (effects ...), with defaults."""
    eff = find(item, "effects")
    size, just = 1.27, []
    if eff:
        font = find(eff, "font")
        if font:
            sz = find(font, "size")
            if sz:
                size = num(sz[2]) or num(sz[1]) or 1.27
        j = find(eff, "justify")
        if j:
            just = [str(t) for t in j[1:]]
    return size, just


def is_hidden(item):
    if any(str(x) == "hide" for x in item if not isinstance(x, list)):
        return True
    h = find(item, "hide")
    if h and str(h[1]) == "yes":
        return True
    eff = find(item, "effects")
    if eff:
        if any(str(x) == "hide" for x in eff if not isinstance(x, list)):
            return True
        h = find(eff, "hide")
        if h and str(h[1]) == "yes":
            return True
    return False


def _grow(box, pts):
    for (x, y) in pts:
        box[0] = min(box[0], x)
        box[1] = min(box[1], y)
        box[2] = max(box[2], x)
        box[3] = max(box[3], y)


def lib_body_box(sym):
    """Body extent of a library symbol, in symbol-local coords (y up).

    Graphics plus the full reach of every pin (connection point and the stem
    back to the body). Pin name/number text is not added: this generator hides
    pin numbers on passives and the names sit inside the body on everything
    else, so the graphics box already covers them.
    """
    box = [math.inf, math.inf, -math.inf, -math.inf]

    def walk(node):
        for x in node:
            if not isinstance(x, list) or not x:
                continue
            head = str(x[0])
            if head == "symbol":          # a unit
                walk(x)
            elif head == "rectangle":
                s, e = find(x, "start"), find(x, "end")
                _grow(box, [(num(s[1]), num(s[2])), (num(e[1]), num(e[2]))])
            elif head in ("polyline", "bezier"):
                pts = find(x, "pts")
                if pts:
                    _grow(box, [(num(p[1]), num(p[2]))
                                for p in find_all(pts, "xy")])
            elif head == "circle":
                c, r = find(x, "center"), find(x, "radius")
                cx, cy, rr = num(c[1]), num(c[2]), num(r[1])
                _grow(box, [(cx - rr, cy - rr), (cx + rr, cy + rr)])
            elif head == "arc":
                for k in ("start", "mid", "end"):
                    p = find(x, k)
                    if p:
                        _grow(box, [(num(p[1]), num(p[2]))])
            elif head == "text":
                at = find(x, "at")
                size, _ = effects_of(x)
                n = len(unescape(str(x[1])))
                _grow(box, [(num(at[1]) - n * size * CHAR_W / 2.0,
                             num(at[2]) - size * LINE_H / 2.0),
                            (num(at[1]) + n * size * CHAR_W / 2.0,
                             num(at[2]) + size * LINE_H / 2.0)])
            elif head == "pin":
                # A pin's `at` is its free CONNECTION point and its angle aims
                # from there back INTO the body, so the stem ends at
                # at + length*(cos a, sin a). Negating that instead - which
                # this did - grew every symbol one pin-length outward in every
                # direction that has a pin, straight through the corridor
                # where that pin's own stub and terminator live. Harmless
                # while only symbols were checked against symbols; the moment
                # rails became real power ports it reported 75 collisions
                # between parts and the ports on their own pins.
                at, ln = find(x, "at"), find(x, "length")
                px, py, pa = num(at[1]), num(at[2]), num(at[3])
                L = num(ln[1]) if ln else 0.0
                rad = math.radians(pa)
                _grow(box, [(px, py),
                            (px + L * math.cos(rad), py + L * math.sin(rad))])

    walk(sym)
    if box[0] is math.inf:
        return (-1.27, -1.27, 1.27, 1.27)
    return tuple(box)


def place(box, sx, sy, angle):
    """Symbol-local box (y up) -> sheet box (y down) at origin sx,sy / angle."""
    x0, y0, x1, y1 = box
    corners = []
    rad = math.radians(angle)
    ca, sa = math.cos(rad), math.sin(rad)
    for (lx, ly) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        rx, ry = lx * ca - ly * sa, lx * sa + ly * ca
        corners.append((sx + rx, sy - ry))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def overlap(a, b):
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    if ox > EPS and oy > EPS:
        return ox * oy
    return 0.0


def wires_of(doc):
    out = []
    for item in doc:
        if isinstance(item, list) and item and str(item[0]) == "wire":
            pts = find_all(find(item, "pts"), "xy")
            if len(pts) == 2:
                out.append(((num(pts[0][1]), num(pts[0][2])),
                            (num(pts[1][1]), num(pts[1][2]))))
    return out


def seg_touch(s, t):
    """Two axis-aligned segments that meet in a way a reader can misread.

    Not every shared point is a defect. A schematic crosses wires constantly
    and KiCad connects nothing where two wires merely cross, so a plain
    transversal crossing is fine - and check_netlist.py proves it stayed
    fine. What is not fine, and is what this reports:

      * an endpoint landing inside the other segment - a T that looks
        soldered and is not (or, if something names the point, silently is);
      * a collinear overlap - the same ink drawn twice.

    Two segments meeting end to end is a corner, and is how every elbow in
    here is drawn.
    """
    (ax, ay), (bx, by) = s
    (cx, cy), (dx, dy) = t
    ends_s, ends_t = {(ax, ay), (bx, by)}, {(cx, cy), (dx, dy)}
    s_h, t_h = abs(ay - by) < EPS, abs(cy - dy) < EPS
    if s_h == t_h:                                    # parallel
        if s_h:
            if abs(ay - cy) > EPS:
                return False
            lo1, hi1 = sorted((ax, bx))
            lo2, hi2 = sorted((cx, dx))
        else:
            if abs(ax - cx) > EPS:
                return False
            lo1, hi1 = sorted((ay, by))
            lo2, hi2 = sorted((cy, dy))
        return min(hi1, hi2) - max(lo1, lo2) > EPS    # overlap, not a touch
    px, py = (cx, ay) if s_h else (ax, cy)            # where they cross
    for rng, v in ((sorted((ax, bx)), px), (sorted((ay, by)), py),
                   (sorted((cx, dx)), px), (sorted((cy, dy)), py)):
        if not (rng[0] - EPS <= v <= rng[1] + EPS):
            return False
    if ends_s & ends_t:                               # a corner
        return False
    return any(abs(px - e[0]) < EPS and abs(py - e[1]) < EPS
               for e in ends_s | ends_t)


def junctions_of(doc):
    out = []
    for item in doc:
        if isinstance(item, list) and item and str(item[0]) == "junction":
            at = find(item, "at")
            out.append((num(at[1]), num(at[2])))
    return out


def _t_point(s, t):
    """Where two perpendicular segments meet, or None if they are parallel."""
    (ax, ay), (bx, by) = s
    (cx, cy), (dx, dy) = t
    s_h, t_h = abs(ay - by) < EPS, abs(cy - dy) < EPS
    if s_h == t_h:
        return None
    return (cx, ay) if s_h else (ax, cy)


def wire_hits(wires, junctions=()):
    """Wire pairs sharing a point that is not a shared endpoint.

    Every wire here is axis-aligned, so this is a box overlap on degenerate
    boxes. Two wires meeting end to end is how a corner is drawn and is fine;
    anything else is a crossing, and a crossing is either a silent short or a
    drawing that looks like one. Fusing a two-pin net into a real wire made
    this reachable for the first time: the TC1_P wire crossed J3's TC1_N stub
    and KiCad merged the nets where the label sat. check_netlist.py caught
    that one because it happened to short; a crossing that does not short is
    invisible to every other check we own.

    A T whose meeting point carries a declared junction is the one exception:
    that is a three-pin fused net's tap, drawn with a dot precisely so it
    reads as soldered - because it is. Collinear overlaps stay errors even
    at a junction; the same ink drawn twice explains nothing.
    """
    hits = []
    for i, s in enumerate(wires):
        for t in wires[i + 1:]:
            if not seg_touch(s, t):
                continue
            p = _t_point(s, t)
            if p is not None and any(abs(p[0] - jx) < EPS
                                     and abs(p[1] - jy) < EPS
                                     for jx, jy in junctions):
                continue
            hits.append((s, t))
    return hits


def collect(sch):
    doc = parse(open(sch).read())[0]
    libs = {}
    ls = find(doc, "lib_symbols")
    if ls:
        for s in find_all(ls, "symbol"):
            libs[str(s[1])] = lib_body_box(s)

    symbols, texts = [], []
    for item in doc:
        if not isinstance(item, list) or not item:
            continue
        head = str(item[0])
        if head == "symbol":
            at = find(item, "at")
            sx, sy = num(at[1]), num(at[2])
            ang = num(at[3]) if len(at) > 3 else 0.0
            lib_id = find(item, "lib_id")
            key = str(lib_id[1]) if lib_id else ""
            box = place(libs.get(key, (-1.27, -1.27, 1.27, 1.27)), sx, sy, ang)
            ref = key
            for p in find_all(item, "property"):
                if str(p[1]) == "Reference":
                    ref = str(p[2])
            # A symbol is its body AND its two visible fields, kept as three
            # separate parts rather than unioned into one rectangle. Unioning
            # cost this checker both directions: it could not see a field
            # printed over its own body (44 of them, "3.579545MHz" straight
            # through Y1's plates), and once rails became power ports it
            # reported every port that legitimately sits between a body and
            # the field lifted above it as a collision.
            symbols.append((ref, box, ref, "body"))
            for p in find_all(item, "property"):
                pname = str(p[1])
                if pname not in ("Reference", "Value") or is_hidden(p):
                    continue
                pat = find(p, "at")
                size, just = effects_of(p)
                symbols.append(("%s.%s" % (ref, pname),
                                text_box(str(p[2]), num(pat[1]), num(pat[2]),
                                         size, just), ref, "field"))
        elif head == "text":
            at = find(item, "at")
            size, just = effects_of(item)
            txt = str(item[1])
            first = unescape(txt).split("\n")[0][:44]
            texts.append(('text "%s"' % first,
                          text_box(txt, num(at[1]), num(at[2]), size, just),
                          None, "text"))
    return symbols, texts


def pairs(a, b, same):
    out = []
    for i, (na, ba, oa, ka) in enumerate(a):
        for j, (nb, bb, ob, kb) in enumerate(b):
            if same and j <= i:
                continue
            # A part's own Reference and Value are stacked 1.9 mm apart with
            # ~2.1 mm of estimated line height, so they always "overlap" each
            # other by a fraction of a millimetre. That pair is the one
            # same-symbol combination that is never a defect.
            if oa is not None and oa == ob and ka == "field" and kb == "field":
                continue
            area = overlap(ba, bb)
            if area:
                out.append((area, na, nb, ba, bb))
    out.sort(key=lambda t: (-t[0], t[1], t[2]))
    return out


def report(kind, hits, limit=25):
    if not hits:
        return 0
    print("\n%s: %d collision(s)" % (kind, len(hits)))
    for area, na, nb, ba, bb in hits[:limit]:
        print("  %-46s x %-46s  %.1f mm^2 overlap "
              "(a=[%.1f,%.1f]..[%.1f,%.1f] b=[%.1f,%.1f]..[%.1f,%.1f])"
              % (na, nb, area, ba[0], ba[1], ba[2], ba[3],
                 bb[0], bb[1], bb[2], bb[3]))
    if len(hits) > limit:
        print("  ... and %d more" % (len(hits) - limit))
    return len(hits)


def main(sch):
    symbols, texts = collect(sch)
    doc = parse(open(sch).read())[0]
    wires = wires_of(doc)
    junctions = junctions_of(doc)
    print("check_sch_layout: %d symbols, %d free-text blocks, %d wires in %s"
          % (len(symbols), len(texts), len(wires), os.path.basename(sch)))
    n = 0
    n += report("SYMBOL/SYMBOL", pairs(symbols, symbols, True))
    n += report("TEXT/SYMBOL", pairs(texts, symbols, False))
    n += report("TEXT/TEXT", pairs(texts, texts, True))
    hits = wire_hits(wires, junctions)
    if hits:
        print("\nWIRE/WIRE: %d crossing(s)" % len(hits))
        for a, b in hits[:25]:
            print("  %-34s x %s" % (a, b))
        n += len(hits)
    if n:
        print("\n%d overlapping pair(s) - the exported PDF is unreviewable" % n)
        return 1
    print("check_sch_layout: no symbol/text overlaps")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    os.pardir, "bisque-controller.kicad_sch")))
