"""DRC-lite for the generated .kicad_pcb (independent of the generator).

Checks:
  1. copper-to-copper clearance between different nets (segments, vias, pads)
  2. per-net connectivity (tracks/vias/pads touching), GND allowed via zone
  3. no copper inside the antenna keepout (except the module's own courtyard
     region is copper-free anyway)
  4. copper-to-board-edge margin
  5. courtyard overlaps between footprints
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all, num

MIN_CLEAR = 0.198
EDGE_CLEAR = 0.4


class Item:
    __slots__ = ("kind", "net", "layers", "x1", "y1", "x2", "y2", "w", "h",
                 "circle", "ref")

    def __repr__(self):
        return "%s[%s %s@(%.2f,%.2f)]" % (self.kind, self.ref, self.net,
                                          self.x1, self.y1)


def rot_xy(lx, ly, rot):
    a = math.radians(rot)
    c, s = round(math.cos(a)), round(math.sin(a))
    return (lx * c + ly * s, -lx * s + ly * c)


def seg_seg_dist(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    def pt_seg(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    def orient(ox, oy, px, py, qx, qy):
        v = (px - ox) * (qy - oy) - (py - oy) * (qx - ox)
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)

    o1 = orient(ax1, ay1, ax2, ay2, bx1, by1)
    o2 = orient(ax1, ay1, ax2, ay2, bx2, by2)
    o3 = orient(bx1, by1, bx2, by2, ax1, ay1)
    o4 = orient(bx1, by1, bx2, by2, ax2, ay2)
    if o1 != o2 and o3 != o4 and o1 != 0 and o3 != 0:
        return 0.0
    return min(pt_seg(ax1, ay1, bx1, by1, bx2, by2),
               pt_seg(ax2, ay2, bx1, by1, bx2, by2),
               pt_seg(bx1, by1, ax1, ay1, ax2, ay2),
               pt_seg(bx2, by2, ax1, ay1, ax2, ay2))


def item_dist(a, b):
    """Distance between copper edges of two items (<=0 means touching)."""
    if a.kind == "seg" and b.kind == "seg":
        d = seg_seg_dist(a.x1, a.y1, a.x2, a.y2, b.x1, b.y1, b.x2, b.y2)
        return d - a.w / 2 - b.w / 2
    if a.kind != "seg" and b.kind != "seg":
        # pad/via vs pad/via
        if a.circle and b.circle:
            return math.hypot(a.x1 - b.x1, a.y1 - b.y1) - a.w / 2 - b.w / 2
        # approx: sample rect corners + center distance via rect expansion
        return rect_rect_dist(a, b)
    if b.kind == "seg":
        a, b = b, a
    # a=seg, b=pad/via
    if b.circle:
        d = pt_seg_d(b.x1, b.y1, a) - b.w / 2 - a.w / 2
        return d
    # sample along segment, rect distance
    steps = max(2, int(math.hypot(a.x2 - a.x1, a.y2 - a.y1) / 0.15))
    dmin = 1e9
    for k in range(steps + 1):
        t = k / float(steps)
        px = a.x1 + (a.x2 - a.x1) * t
        py = a.y1 + (a.y2 - a.y1) * t
        dx = max(abs(px - b.x1) - b.w / 2, 0.0)
        dy = max(abs(py - b.y1) - b.h / 2, 0.0)
        dmin = min(dmin, math.hypot(dx, dy))
    return dmin - a.w / 2


def pt_seg_d(px, py, s):
    dx, dy = s.x2 - s.x1, s.y2 - s.y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((px - s.x1) * dx + (py - s.y1) * dy) / L2))
    return math.hypot(px - (s.x1 + t * dx), py - (s.y1 + t * dy))


def rect_rect_dist(a, b):
    dx = max(abs(a.x1 - b.x1) - a.w / 2 - b.w / 2, 0.0)
    dy = max(abs(a.y1 - b.y1) - a.h / 2 - b.h / 2, 0.0)
    # circle vs rect approx
    if a.circle or b.circle:
        # conservative: treat circle as rect of same bbox
        pass
    return math.hypot(dx, dy)


def load(src):
    doc = parse(open(src).read())[0]
    items = []
    courtyards = {}
    edges = []
    for g in find_all(doc, "gr_line"):
        if str(find(g, "layer")[1]) == "Edge.Cuts":
            s, e = find(g, "start"), find(g, "end")
            edges.append((num(s[1]), num(s[2]), num(e[1]), num(e[2])))
    for s in find_all(doc, "segment"):
        it = Item()
        it.kind = "seg"
        st, en = find(s, "start"), find(s, "end")
        it.x1, it.y1, it.x2, it.y2 = num(st[1]), num(st[2]), num(en[1]), num(en[2])
        it.w = num(find(s, "width")[1])
        it.h = it.w
        it.circle = False
        it.layers = {0 if str(find(s, "layer")[1]) == "F.Cu" else 1}
        it.net = int(find(s, "net")[1])
        it.ref = "seg"
        items.append(it)
    for v in find_all(doc, "via"):
        it = Item()
        it.kind = "via"
        at = find(v, "at")
        it.x1, it.y1 = num(at[1]), num(at[2])
        it.x2, it.y2 = it.x1, it.y1
        it.w = num(find(v, "size")[1])
        it.h = it.w
        it.circle = True
        it.layers = {0, 1}
        it.net = int(find(v, "net")[1])
        it.ref = "via"
        items.append(it)
    for fp in find_all(doc, "footprint"):
        at = find(fp, "at")
        fx, fy = num(at[1]), num(at[2])
        frot = num(at[3]) if len(at) > 3 else 0.0
        ref = ""
        for pr in find_all(fp, "property"):
            if pr[1] == "Reference":
                ref = str(pr[2])
        for ft in find_all(fp, "fp_text"):
            if str(ft[1]) == "reference":
                ref = str(ft[2])
        # courtyard bbox
        cx0, cy0, cx1, cy1 = 1e9, 1e9, -1e9, -1e9
        for key in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
            for e in find_all(fp, key):
                lay = find(e, "layer")
                if not lay or str(lay[1]) != "F.CrtYd":
                    continue
                ptlist = []
                for pk in ("start", "end", "center", "mid"):
                    pt = find(e, pk)
                    if pt:
                        ptlist.append((num(pt[1]), num(pt[2])))
                pts = find(e, "pts")
                if pts:
                    ptlist += [(num(p[1]), num(p[2])) for p in find_all(pts, "xy")]
                for (lx, ly) in ptlist:
                    gx, gy = rot_xy(lx, ly, frot)
                    cx0 = min(cx0, fx + gx)
                    cy0 = min(cy0, fy + gy)
                    cx1 = max(cx1, fx + gx)
                    cy1 = max(cy1, fy + gy)
        if cx0 < 1e8 and ref not in ("U1",):  # U1 courtyard includes antenna zone
            courtyards[ref] = (cx0, cy0, cx1, cy1)
        for p in find_all(fp, "pad"):
            lay = find(p, "layers")
            laystr = " ".join(str(e) for e in lay[1:]) if lay else ""
            if "Cu" not in laystr:
                continue
            pat = find(p, "at")
            lx, ly = num(pat[1]), num(pat[2])
            pa = (num(pat[3]) if len(pat) > 3 else 0.0)
            gx, gy = rot_xy(lx, ly, frot)
            size = find(p, "size")
            w, h = num(size[1]), num(size[2])
            if abs((pa % 180) - 90) < 1:
                w, h = h, w
            it = Item()
            it.kind = "pad"
            it.x1, it.y1 = fx + gx, fy + gy
            it.x2, it.y2 = it.x1, it.y1
            it.w, it.h = w, h
            it.circle = str(p[3]) == "circle"
            kind = str(p[2])
            it.layers = {0, 1} if kind in ("thru_hole", "np_thru_hole") else {0}
            netn = find(p, "net")
            if kind == "np_thru_hole":
                it.net = -2  # blocks everything
            elif netn is None:
                it.net = -1  # unconnected pad: unique-ish (treated foreign)
            else:
                it.net = int(netn[1])
            it.ref = "%s.%s" % (ref, p[1])
            items.append(it)
    netnames = {0: ""}
    for n in find_all(doc, "net"):
        netnames[int(n[1])] = str(n[2])
    return items, netnames, courtyards, edges, doc


def main(src):
    items, netnames, courtyards, edges, doc = load(src)
    xs = [e for ed in edges for e in (ed[0], ed[2])]
    ys = [e for ed in edges for e in (ed[1], ed[3])]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    problems = []

    # bucket items
    B = 3.0
    buckets = {}
    for idx, it in enumerate(items):
        x0 = min(it.x1, it.x2) - it.w / 2
        x1 = max(it.x1, it.x2) + it.w / 2
        y0 = min(it.y1, it.y2) - it.h / 2
        y1 = max(it.y1, it.y2) + it.h / 2
        for bx in range(int(x0 // B), int(x1 // B) + 1):
            for by in range(int(y0 // B), int(y1 // B) + 1):
                buckets.setdefault((bx, by), []).append(idx)

    # 1. clearance
    checked = set()
    worst = {}
    for blist in buckets.values():
        for i in range(len(blist)):
            for j in range(i + 1, len(blist)):
                a, b = items[blist[i]], items[blist[j]]
                key = (min(blist[i], blist[j]), max(blist[i], blist[j]))
                if key in checked:
                    continue
                checked.add(key)
                if a.net == b.net and a.net >= 0:
                    continue
                # NC pads (-1) vs each other: both unconnected, still keep apart
                if not (a.layers & b.layers):
                    continue
                d = item_dist(a, b)
                if d < MIN_CLEAR:
                    problems.append("clearance %.3f: %s (%s) vs %s (%s)"
                                    % (d, a, netnames.get(a.net, a.net),
                                       b, netnames.get(b.net, b.net)))

    # 2. connectivity per net
    from collections import defaultdict
    bynet = defaultdict(list)
    for idx, it in enumerate(items):
        if it.net > 0:
            bynet[it.net].append(idx)
    gnd = [k for k, v in netnames.items() if v == "GND"]
    gndnum = gnd[0] if gnd else -99
    for netn, idxs in sorted(bynet.items()):
        if netn == gndnum:
            continue
        parent = list(range(len(idxs)))

        def findp(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                a, b = items[idxs[i]], items[idxs[j]]
                if not (a.layers & b.layers):
                    continue
                if item_dist(a, b) < 0.02:
                    pi, pj = findp(i), findp(j)
                    if pi != pj:
                        parent[pi] = pj
        roots = {findp(i) for i in range(len(idxs))}
        if len(roots) > 1:
            groups = defaultdict(list)
            for i in range(len(idxs)):
                groups[findp(i)].append(items[idxs[i]].ref)
            problems.append("net %s split into %d islands: %s"
                            % (netnames[netn], len(roots),
                               [g[:10] for g in groups.values()]))

    # 3. keepout (from U1)
    k = None
    for fp in find_all(doc, "footprint"):
        pr = {p[1]: p[2] for p in find_all(fp, "property")}
        for ft in find_all(fp, "fp_text"):
            if str(ft[1]) == "reference":
                pr["Reference"] = str(ft[2])
        if pr.get("Reference") == "U1":
            at = find(fp, "at")
            fx, fy = num(at[1]), num(at[2])
            k = (fx - 24, by0, fx + 24, fy - 6.8)
    for it in items:
        if k is None or it.net == 0:
            continue
        x0 = min(it.x1, it.x2) - it.w / 2
        x1 = max(it.x1, it.x2) + it.w / 2
        y0 = min(it.y1, it.y2) - it.h / 2
        y1 = max(it.y1, it.y2) + it.h / 2
        if it.kind in ("seg", "via"):
            if x1 > k[0] and x0 < k[2] and y1 > k[1] and y0 < k[3]:
                problems.append("keepout violation: %s %s" % (it, netnames.get(it.net)))

    # 4. edge clearance
    for it in items:
        x0 = min(it.x1, it.x2) - it.w / 2
        x1 = max(it.x1, it.x2) + it.w / 2
        y0 = min(it.y1, it.y2) - it.h / 2
        y1 = max(it.y1, it.y2) + it.h / 2
        if it.kind == "pad" and it.ref.startswith("H"):
            continue
        if x0 < bx0 + EDGE_CLEAR or x1 > bx1 - EDGE_CLEAR \
           or y0 < by0 + EDGE_CLEAR or y1 > by1 - EDGE_CLEAR:
            problems.append("edge clearance: %s" % it)

    # 5. courtyard overlaps
    refs = sorted(courtyards)
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            a, b = courtyards[refs[i]], courtyards[refs[j]]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox > 0.05 and oy > 0.05:
                problems.append("courtyard overlap: %s vs %s (%.1fx%.1f mm)"
                                % (refs[i], refs[j], ox, oy))

    print("checked %d copper items" % len(items))
    if problems:
        print("%d PROBLEMS:" % len(problems))
        for p in problems[:80]:
            print("  -", p)
        return 1
    print("ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
