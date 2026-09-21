#!/usr/bin/env python3
"""The USB differential pair, measured off the board file and held to it.

USB_DP/USB_DN are the one impedance-controlled object on this board, and the
93.1 ohm in gen_pcb.STACKUP is the figure for two 0.3 mm tracks 0.2 mm apart
over the In1.Cu plane. That number describes the pair only where the two
tracks actually run side by side, so this checks that they do:

  * each net is ONE piece of copper (no dangling stub, no island);
  * neither net carries a via - the pair is routed on F.Cu end to end, and a
    via pair cannot hold the 0.2 mm gap;
  * the two nets are the same length, pad to pad, within SKEW_MAX;
  * the length of either net that is NOT running at the pair pitch beside
    the other is at most UNCOUPLED_MAX. The lead-in is uncoupled by
    construction - J1's pads interleave at 0.5 mm pitch, the TVS is a
    flow-through with its two channels 1.9 mm apart - and the fan into the
    module's 1.27 mm-pitch pads is too, which is where the budget goes.

Before the pair was routed as a pair (router.route_pair), the same board
measured 50.8 mm against 33.2 mm, over 8 and 5 vias, with 0% of either net
within a pitch of the other. That is the regression this exists to catch:
a placement change that strands the pair router's corridor fails here, on
the numbers, rather than being noticed by eye on a render.

Pure Python (the repo's sexp.py), no KiCad, so it runs in CI.

Usage: python3 check_usb_pair.py board.kicad_pcb
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sexp

PAIR = ("USB_DP", "USB_DN")
ENDS = (("J1", "USB_DP"), ("U1", "USB_DP"))  # the pair runs J1 -> U1
WIDTH, GAP = 0.3, 0.2                        # gen_pcb.USB_DIFF_WIDTH / _GAP
PITCH_TOL = 0.05        # mm; "side by side" means centre spacing within this of the pitch
# Budgets, each set from the first pair-routed board with a little room:
#   uncoupled 14.5 / 11.6 mm - the J1 link and escape (~7.5 mm, the connector's
#     0.5 mm pad pitch), the flow-through under U4 (~4.8 mm, its 1.9 mm column
#     spacing), the funnel into the pair and the fan into U1 (1.27 mm pitch);
#   skew 2.52 mm - 2.4 of it is the funnel: the outer line travels the 1.9 mm
#     column offset that the inner one does not. That is ~18 ps against a
#     Full-Speed bit of 83 ns and an edge of 4 ns or more; the pair it
#     replaces measured 10.2 mm pad to pad.
UNCOUPLED_MAX = 16.0    # mm per net
SKEW_MAX = 3.5          # mm pad to pad
COUPLED_MIN = 0.40      # fraction of each net's copper running at the pair pitch (47 / 53 % measured)


def kids(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def one(node, key):
    r = kids(node, key)
    return r[0] if r else None


def pad_centres(doc):
    """{(ref, net): [(x, y), ...]} for every pad on a PAIR net."""
    out = {}
    for fp in kids(doc, "footprint"):
        at = one(fp, "at")
        fx, fy = float(at[1]), float(at[2])
        rot = math.radians(float(at[3])) if len(at) > 3 else 0.0
        ref = [p for p in kids(fp, "property") if p[1] == "Reference"][0][2]
        for pad in kids(fp, "pad"):
            net = one(pad, "net")
            if net is None or net[-1] not in PAIR:
                continue
            pat = one(pad, "at")
            dx, dy = float(pat[1]), float(pat[2])
            # KiCad rotates a footprint's children anticlockwise on screen,
            # which with y down is this transform (checked against U1 pad 14
            # at rot 0 and J1's row at rot 180).
            px = fx + dx * math.cos(rot) + dy * math.sin(rot)
            py = fy - dx * math.sin(rot) + dy * math.cos(rot)
            out.setdefault((ref, net[-1]), []).append((px, py))
    return out


def copper(doc, net):
    segs, vias = [], []
    for s in kids(doc, "segment"):
        if one(s, "net")[1] != net:
            continue
        a, b = one(s, "start"), one(s, "end")
        segs.append(((float(a[1]), float(a[2])), (float(b[1]), float(b[2])),
                     float(one(s, "width")[1]), one(s, "layer")[1]))
    for v in kids(doc, "via"):
        if one(v, "net")[1] == net:
            at = one(v, "at")
            vias.append((float(at[1]), float(at[2])))
    return segs, vias


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def coupled_length(segs, other, pitch, tol, step=0.05):
    """Length of `segs` whose centreline sits `pitch` (+-tol) from `other`."""
    total = coupled = 0.0
    for (a, b, _w, _l) in segs:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / step))
        hit = 0
        for k in range(n):
            t = (k + 0.5) / n
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            d = min(seg_dist(p, c, d_) for (c, d_, _w2, _l2) in other)
            if abs(d - pitch) <= tol:
                hit += 1
        total += L
        coupled += L * hit / n
    return total, coupled


def path_length(segs, src, dst, eps=1e-3):
    """Shortest copper path from the point src to the point dst, or None.

    Every segment end that lands inside a pad is one node with every other
    end in that pad: two tracks meeting at different points on one pad are
    connected in copper and would be disconnected in a naive endpoint graph.
    Here that is handled by snapping ends within `eps` of each other and by
    treating src/dst (pad centres) as reachable from any end within the pad
    - the caller passes the pad half-extent as `eps` for those.
    """
    pts = []

    def node(p, tol):
        for i, q in enumerate(pts):
            if math.hypot(p[0] - q[0], p[1] - q[1]) <= tol:
                return i
        pts.append(p)
        return len(pts) - 1

    # A segment end that lands on another segment's interior is a T, and
    # that is exactly how the hand-drawn J1 link joins the escape - so split
    # every segment at the foreign ends lying on it before building the
    # graph, or the link reads as its own island.
    ends = [p for (a, b, _w, _l) in segs for p in (a, b)]
    split = []
    for (a, b, _w, _l) in segs:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        cuts = []
        for p in ends:
            if seg_dist(p, a, b) <= eps and \
               math.hypot(p[0] - a[0], p[1] - a[1]) > eps and \
               math.hypot(p[0] - b[0], p[1] - b[1]) > eps:
                t = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / (L * L)
                cuts.append((t, p))
        chain = [a] + [p for _t, p in sorted(cuts)] + [b]
        for c, d in zip(chain, chain[1:]):
            split.append((c, d, _w, _l))
    adj = {}
    for (a, b, _w, _l) in split:
        i, j = node(a, eps), node(b, eps)
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        adj.setdefault(i, []).append((j, L))
        adj.setdefault(j, []).append((i, L))
    return pts, adj


def dijkstra(adj, s, t):
    import heapq
    dist = {s: 0.0}
    q = [(0.0, s)]
    while q:
        d, u = heapq.heappop(q)
        if u == t:
            return d
        if d > dist.get(u, float("inf")):
            continue
        for v, L in adj.get(u, ()):
            nd = d + L
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(q, (nd, v))
    return None


def components(adj, n):
    seen, count = set(), 0
    for s in range(n):
        if s in seen:
            continue
        count += 1
        stack = [s]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(v for v, _L in adj.get(u, ()))
    return count


def main(path):
    doc = sexp.parse(open(path).read())[0]
    pads = pad_centres(doc)
    fails = []
    lengths = {}
    cop = {net: copper(doc, net) for net in PAIR}
    pitch = WIDTH + GAP
    for net in PAIR:
        segs, vias = cop[net]
        other = cop[PAIR[1] if net == PAIR[0] else PAIR[0]][0]
        if not segs:
            fails.append("%s: no tracks" % net)
            continue
        if vias:
            fails.append("%s: %d via(s) at %s" % (net, len(vias), vias))
        if any(l != "F.Cu" for (_a, _b, _w, l) in segs):
            fails.append("%s: copper on %s" % (net, sorted({l for (_a, _b, _w, l) in segs} - {"F.Cu"})))
        pts, adj = path_length(segs, None, None)
        nc = components(adj, len(pts))
        if nc != 1:
            fails.append("%s: copper is %d pieces, not one" % (net, nc))
        total, coupled = coupled_length(segs, other, pitch, PITCH_TOL)
        # pad-to-pad: the J1 pad nearest the escape and the module pad. A pad
        # centre may not be a segment end (the escape leaves the pad centre
        # here, but need not), so the nearest node within the pad counts.
        src = min(pads[("J1", net)], key=lambda p: p[1])          # J1's row
        dst = pads[("U1", net)][0]

        def nearest(p, r=0.8):
            best = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - p[0], pts[i][1] - p[1]))
            d = math.hypot(pts[best][0] - p[0], pts[best][1] - p[1])
            return best if d <= r else None
        s_node = min((nearest(p) for p in pads[("J1", net)] if nearest(p) is not None),
                     key=lambda i: dijkstra(adj, i, nearest(dst)) or float("inf"))
        L = dijkstra(adj, s_node, nearest(dst))
        if L is None:
            fails.append("%s: no copper path from J1 to U1" % net)
            L = float("nan")
        lengths[net] = L
        print("%s: %.2f mm of track, %.2f mm J1 -> U1, %d via(s), %.2f mm coupled "
              "(%.0f%%), %.2f mm not" % (net, total, L, len(vias), coupled,
                                          100.0 * coupled / total, total - coupled))
        if total - coupled > UNCOUPLED_MAX:
            fails.append("%s: %.2f mm uncoupled, max %.1f" % (net, total - coupled, UNCOUPLED_MAX))
        if coupled / total < COUPLED_MIN:
            fails.append("%s: only %.0f%% coupled, min %.0f%%" % (net, 100 * coupled / total, 100 * COUPLED_MIN))
    if len(lengths) == 2:
        skew = abs(lengths[PAIR[0]] - lengths[PAIR[1]])
        print("skew: %.2f mm (%.1f ps at ~6.5 ps/mm)" % (skew, skew * 6.5))
        if not skew <= SKEW_MAX:
            fails.append("skew %.2f mm, max %.1f" % (skew, SKEW_MAX))
    if fails:
        print("check_usb_pair: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("check_usb_pair: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb"))
