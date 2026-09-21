"""Grid autorouter (A*) for the bisque controller board.

Two ROUTING layers - 0 is F.Cu, 1 is B.Cu - on a board that is physically
4-layer: In1.Cu and In2.Cu carry the GND and +3V3 plane fills and never a
track, so the router has no reason to model them. Vias are through-hole,
which is exactly what lets a pad reach either plane with one hole; KiCad's
zone fill puts the antipads in.

Board mm coordinates. Obstacles are exact copper shapes (pads, routed
tracks/vias, keepouts, board margin) checked with true clearance (edge
distance >= CLEAR). Multi-terminal nets route incrementally: each terminal
connects to the growing net copper via A*.
"""
import heapq
import math
import os

# Comma-separated net names; each committed route prints its layer runs.
DEBUG_NETS = set(filter(None, os.environ.get("ROUTER_DEBUG", "").split(",")))

# 0.25 mm, not rev A's 0.4. Rev B adds a 0.5 mm-pitch QFN-28 (ADE7953) and two
# 0.65 mm-pitch TSSOP-14s (MAX31856), and a track can only leave pads that fine
# along the pad's own centreline - a 0.4 mm grid snaps the escape up to 0.2 mm
# off centre, which puts it inside the neighbouring pin's clearance and makes
# those pads simply unreachable. At 0.25 mm every 0.5 mm-pitch pad lands
# exactly on a grid line and the worst 0.65 mm-pitch error falls to 0.125 mm,
# which a 0.25 mm track clears.
#
# That is measured, not reasoned. The escape stubs mean the router no longer
# touches a fine-pitch pad directly, which looks like it should have retired
# the constraint - but gen_pcb._snap() lands every stub end on GRID, so a
# coarser grid walks the escape off the pad's centreline just the same. At
# 0.4 mm 14 nets fail to route and at 0.3 mm five do, in both cases on U7 and
# the two MAX31856s. Nor is the fine grid what costs the time: 0.3 mm takes
# 463 s against 0.25 mm's 144, because a net that cannot be routed exhausts
# the whole grid before it says so, several times a pass.
GRID = 0.25         # mm per cell
CLEAR = 0.2         # required copper-to-copper clearance
VIA_DIA = 0.6
VIA_DRILL = 0.3
BUCKET = 2.0

# Gap a via's copper must keep from any SMD pad, *including one on its own
# net*. Different-net pads are already covered by CLEAR; this exists for the
# same-net case, which clearance rules deliberately ignore and which DRC will
# never flag. An untented via inside a pad wicks solder out of the joint
# during reflow — the alternative fix, filled-and-capped via-in-pad, is a
# JLCPCB upcharge, and mask tenting cannot work because the pad's own mask
# opening exposes the barrel anyway.
VIA_PAD_GAP = 0.15

# Minimum web of laminate between two drilled apertures — via-to-via and
# via-to-pad-hole alike. This is a *mechanical* rule at the drill, so it
# applies regardless of net: same-net holes break out into each other exactly
# as readily as different-net ones, and no clearance rule (KiCad's included,
# in practice) will say a word about it. JLCPCB's published floor is 0.20 mm;
# 0.30 buys margin on a constraint whose failure mode is a broken-out hole
# found at the fab. See check_drill_clearance.py, which enforces the same
# number on the finished board.
HOLE_TO_HOLE = 0.30


class Shape:
    """Axis-aligned rect or circle, on layer set. net None = blocks all.

    A drilled pad also carries its *hole* geometry, which is not the same
    thing as its copper: `drill` is the hole diameter and (hx1,hy1)-(hx2,hy2)
    is the hole's centre segment, degenerate for a round hole and 1.1 mm long
    for the USB-C shield's `(drill oval 0.6 1.7)` slot. Modelling a slot as a
    circle of diameter 0.6 understates its reach by (1.7-0.6)/2 = 0.55 mm,
    which is how a 0.078 mm web to a GND stitching via got past this router.
    """
    __slots__ = ("net", "layers", "cx", "cy", "w", "h", "circle", "drill",
                 "hx1", "hy1", "hx2", "hy2", "bx0", "by0", "bx1", "by1")

    def __init__(self, net, layers, cx, cy, w, h, circle=False, drill=0.0,
                 drill_len=0.0, drill_ang=0.0, hole=None):
        self.net, self.layers = net, set(layers)
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.circle = circle
        self.drill = drill
        hcx, hcy = hole if hole is not None else (cx, cy)
        half = max(0.0, (drill_len - drill) / 2.0)
        a = math.radians(drill_ang)
        dx, dy = half * math.cos(a), -half * math.sin(a)
        self.hx1, self.hy1 = hcx - dx, hcy - dy
        self.hx2, self.hy2 = hcx + dx, hcy + dy
        # Bounding box over copper AND hole, cached because it is the reject
        # test in the router's hottest loop (see Router._clear_of). It is only
        # ever used to skip an exact dist()/hole_dist() that could not have
        # returned a violation, so an over-large box costs speed, never
        # correctness.
        hr = drill / 2.0
        self.bx0 = min(cx - w / 2.0, self.hx1 - hr, self.hx2 - hr)
        self.bx1 = max(cx + w / 2.0, self.hx1 + hr, self.hx2 + hr)
        self.by0 = min(cy - h / 2.0, self.hy1 - hr, self.hy2 - hr)
        self.by1 = max(cy + h / 2.0, self.hy1 + hr, self.hy2 + hr)

    def hole_dist(self, x, y):
        """Distance from (x, y) to this pad's drill aperture edge."""
        dx, dy = self.hx2 - self.hx1, self.hy2 - self.hy1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-15 else max(
            0.0, min(1.0, ((x - self.hx1) * dx + (y - self.hy1) * dy) / L2))
        px, py = self.hx1 + t * dx, self.hy1 + t * dy
        return math.hypot(x - px, y - py) - self.drill / 2.0

    def dist(self, x, y):
        if self.circle:
            return math.hypot(x - self.cx, y - self.cy) - self.w / 2.0
        dx = max(abs(x - self.cx) - self.w / 2.0, 0.0)
        dy = max(abs(y - self.cy) - self.h / 2.0, 0.0)
        return math.hypot(dx, dy)

    def reach(self):
        return (max(self.w, self.h) / 2.0)


class Seg:
    # `fixed` marks copper the router did not draw and may not remove: the
    # hand-seeded USB escapes, the fine-pitch fanout stubs and the plane-via
    # stubs. rip_up() deletes only what it can re-create.
    __slots__ = ("net", "layer", "x1", "y1", "x2", "y2", "w", "fixed",
                 "bx0", "by0", "bx1", "by1")

    def __init__(self, net, layer, x1, y1, x2, y2, w, fixed=False):
        self.net, self.layer = net, layer
        self.x1, self.y1, self.x2, self.y2, self.w = x1, y1, x2, y2, w
        self.fixed = fixed
        # See Shape's box: a cached reject bound, never an answer. miter_corners
        # shortens a segment in place and deliberately does not refresh this —
        # the stale box is larger than the copper, which only means the exact
        # dist() below runs on a few extra candidates.
        h = w / 2.0
        self.bx0, self.bx1 = min(x1, x2) - h, max(x1, x2) + h
        self.by0, self.by1 = min(y1, y2) - h, max(y1, y2) + h

    def dist(self, x, y):
        dx, dy = self.x2 - self.x1, self.y2 - self.y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((x - self.x1) * dx + (y - self.y1) * dy) / L2))
        px, py = self.x1 + t * dx, self.y1 + t * dy
        return math.hypot(x - px, y - py) - self.w / 2.0


class PairNet(object):
    """Two net names the clearance model treats as ONE net.

    route_pair() routes a differential pair as a single fat track down the
    pair's centreline, and while it does so neither member's copper - the
    hand-drawn escapes at J1, the pass-through under the TVS - may count as
    an obstacle. Every clearance test in this file is written `o.net == net`
    against a str, so rather than teach each of them about pairs this object
    answers that comparison for both names: `"USB_DP" == PairNet("USB_DP",
    "USB_DN")` is True, because str's __eq__ returns NotImplemented for a
    foreign type and Python then asks the PairNet. None (a no-net pad) and
    every other net compare unequal, exactly as they would against a str.
    Hashable, so it can key the blocked/via memo like a net name does.
    """
    __slots__ = ("a", "b")

    def __init__(self, a, b):
        self.a, self.b = a, b

    def __eq__(self, other):
        if isinstance(other, PairNet):
            return (self.a, self.b) == (other.a, other.b)
        return other == self.a or other == self.b

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.a, self.b))

    def __repr__(self):
        return "%s/%s" % (self.a, self.b)


class Router:
    def __init__(self, x0, y0, x1, y1, edge_margin=0.65):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.nx = int(round((x1 - x0) / GRID)) + 1
        self.ny = int(round((y1 - y0) / GRID)) + 1
        self.margin = edge_margin
        self.keepouts = []
        self.buckets = {}   # (bx,by) -> list of Shape/Seg
        # (bx,by) -> the 9 surrounding buckets flattened into one list. _near()
        # is entered ~21 M times a build and walks ~40 objects each time; doing
        # that as a generator over 9 dict lookups cost 833 M frame resumptions.
        self._near_cache = {}
        self.pads = []            # Shape, never removed
        self.result_tracks = []   # Seg (all routed, incl. seeds)
        self.result_vias = []     # (net, x, y, fixed)
        self._memo = {}
        self._memo_net = None
        self.fail_at = None
        self.fail_pos = {}   # net -> terminal that could not be reached

    # --- model ---
    def _insert(self, obj, x0, y0, x1, y1):
        pad = 1.2
        bx0 = int((x0 - pad) // BUCKET)
        bx1 = int((x1 + pad) // BUCKET)
        by0 = int((y0 - pad) // BUCKET)
        by1 = int((y1 + pad) // BUCKET)
        cache = self._near_cache
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                self.buckets.setdefault((bx, by), []).append(obj)
                # Every flattened list that reads this bucket is now stale.
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        cache.pop((bx + dx, by + dy), None)

    def add_pad(self, net, layers, cx, cy, w, h, circle=False, drill=0.0,
                drill_len=0.0, drill_ang=0.0, hole=None):
        s = Shape(net, layers, cx, cy, w, h, circle, drill=drill,
                  drill_len=drill_len, drill_ang=drill_ang, hole=hole)
        self.pads.append(s)
        self._insert(s, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    def add_keepout(self, x0, y0, x1, y1):
        """Rectangle no track or via may enter, whatever its net.

        The per-net `allow_nets` exemption this used to carry existed only
        for the opto-isolation barrier, whose isolated nets had to be the
        one thing routed through the band. Both the barrier and the optos
        are gone (see design.py's SSR block), so a keepout is now absolute
        and the only caller left is the module antenna keepout, which never
        wanted an exemption."""
        self.keepouts.append((x0, y0, x1, y1))

    def add_seg(self, net, layer, x1, y1, x2, y2, w, record=True, fixed=False):
        s = Seg(net, layer, x1, y1, x2, y2, w, fixed=fixed)
        self._insert(s, min(x1, x2) - w / 2, min(y1, y2) - w / 2,
                     max(x1, x2) + w / 2, max(y1, y2) + w / 2)
        if record:
            self.result_tracks.append(s)

    def add_via(self, net, x, y, record=True, fixed=False):
        s = Shape(net, (0, 1), x, y, VIA_DIA, VIA_DIA, circle=True,
                  drill=VIA_DRILL)
        self._insert(s, x - VIA_DIA / 2, y - VIA_DIA / 2, x + VIA_DIA / 2, y + VIA_DIA / 2)
        if record:
            self.result_vias.append((net, x, y, fixed))

    # --- rip-up support -----------------------------------------------------
    def reindex(self):
        """Rebuild the spatial index from pads + the current copper lists."""
        self.buckets = {}
        self._near_cache = {}
        self._memo, self._memo_net = {}, None
        for s in self.pads:
            self._insert(s, s.cx - s.w / 2, s.cy - s.h / 2,
                         s.cx + s.w / 2, s.cy + s.h / 2)
        for s in self.result_tracks:
            self._insert(s, min(s.x1, s.x2) - s.w / 2, min(s.y1, s.y2) - s.w / 2,
                         max(s.x1, s.x2) + s.w / 2, max(s.y1, s.y2) + s.w / 2)
        for (net, x, y, _fx) in self.result_vias:
            v = Shape(net, (0, 1), x, y, VIA_DIA, VIA_DIA, circle=True,
                      drill=VIA_DRILL)
            self._insert(v, x - VIA_DIA / 2, y - VIA_DIA / 2,
                         x + VIA_DIA / 2, y + VIA_DIA / 2)

    def snapshot(self):
        return (list(self.result_tracks), list(self.result_vias))

    def restore(self, snap):
        self.result_tracks, self.result_vias = list(snap[0]), list(snap[1])
        self.reindex()

    def rip_up(self, net):
        """Delete every piece of router-drawn copper on `net`."""
        self.result_tracks = [s for s in self.result_tracks
                              if s.net != net or s.fixed]
        self.result_vias = [v for v in self.result_vias
                            if v[0] != net or v[3]]
        self.reindex()

    def nets_near(self, x, y, radius):
        """Nets with removable copper within `radius` of (x, y), nearest
        first. Deterministic: ties break on the net name."""
        best = {}
        for s in self.result_tracks:
            if s.fixed:
                continue
            d = s.dist(x, y)
            if d < radius and (s.net not in best or d < best[s.net]):
                best[s.net] = d
        for (net, vx, vy, fx) in self.result_vias:
            if fx:
                continue
            d = math.hypot(vx - x, vy - y) - VIA_DIA / 2
            if d < radius and (net not in best or d < best[net]):
                best[net] = d
        return [n for (_d, n) in sorted((round(d, 4), n)
                                        for n, d in best.items())]

    def _near(self, x, y):
        """Every obstacle in the 3x3 block of buckets around (x, y).

        Returns a real list, not a generator: the callers below are the
        router's inner loop and a generator paid one frame resumption per
        object yielded.
        """
        key = (int(x // BUCKET), int(y // BUCKET))
        out = self._near_cache.get(key)
        if out is None:
            bx, by = key
            out = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    out += self.buckets.get((bx + dx, by + dy), ())
            self._near_cache[key] = out
        return out

    def cell_xy(self, i, j):
        return self.x0 + i * GRID, self.y0 + j * GRID

    def snap(self, x, y):
        return (int(round((x - self.x0) / GRID)), int(round((y - self.y0) / GRID)))

    def _begin(self, net):
        # Type-aware on purpose: a PairNet compares equal to either of its
        # member names, and a memo built for one member is not valid for
        # the pair (or the reverse) - the clearance semantics differ.
        if self._memo_net is None or type(self._memo_net) is not type(net) \
           or self._memo_net != net:
            self._memo = {}
            self._memo_net = net

    def blocked(self, net, width, i, j, layer):
        key = (net, i, j, layer, width)
        v = self._memo.get(key)
        if v is not None:
            return v
        r = self._blocked_raw(net, width, i, j, layer)
        self._memo[key] = r
        return r

    def _clear_of(self, net, x, y, layer, need, check_layer=True):
        # The bounding-box test is a pure reject: an obstacle whose box is
        # more than `need` away in x or in y is more than `need` away, full
        # stop, so skipping it cannot change the answer. It exists because
        # this is where the router spends its life — 12.7 M calls walking
        # ~40 obstacles each — and four float compares are an order of
        # magnitude cheaper than the dist() they replace for the ~90% of
        # bucket residents that are merely in the neighbourhood.
        for o in self._near(x, y):
            if o.net == net:
                continue
            if x < o.bx0 - need or x > o.bx1 + need or \
               y < o.by0 - need or y > o.by1 + need:
                continue
            if check_layer:
                if isinstance(o, Seg):
                    if o.layer != layer:
                        continue
                elif layer not in o.layers:
                    continue
            if o.dist(x, y) < need - 1e-9:
                return False
        return True

    def _blocked_raw(self, net, width, i, j, layer):
        x, y = self.cell_xy(i, j)
        half = width / 2.0
        need = half + CLEAR
        if (x - self.x0) < self.margin + half or (self.x1 - x) < self.margin + half \
           or (y - self.y0) < self.margin + half or (self.y1 - y) < self.margin + half:
            return True
        for k in self.keepouts:
            if k[0] - need < x < k[2] + need and k[1] - need < y < k[3] + need:
                return True
        return not self._clear_of(net, x, y, layer, need)

    def via_ok(self, net, i, j):
        key = (net, i, j, "via")
        v = self._memo.get(key)
        if v is not None:
            return v
        x, y = self.cell_xy(i, j)
        need = VIA_DIA / 2.0 + CLEAR
        r = True
        if (x - self.x0) < self.margin + VIA_DIA / 2 or (self.x1 - x) < self.margin + VIA_DIA / 2 \
           or (y - self.y0) < self.margin + VIA_DIA / 2 or (self.y1 - y) < self.margin + VIA_DIA / 2:
            r = False
        if r:
            for k in self.keepouts:
                if k[0] - need < x < k[2] + need and k[1] - need < y < k[3] + need:
                    r = False
                    break
        if r:
            # Three tests, one walk. Copper clearance (different-net only),
            # via-in-pad (SMD pads, any net) and hole-to-hole (drilled pads,
            # any net) used to each scan the neighbourhood separately; the
            # result is their AND, so interleaving them is the same answer for
            # a third of the traversal. via_ok is asked at nearly every node
            # A* pops — 4.3 M times a build — and its memo barely hits,
            # because a node is popped once.
            #
            # `need` (0.5 mm) is the largest of the three reach limits: the
            # pad gap is VIA_DIA/2 + 0.15 and the hole rule is HOLE_TO_HOLE +
            # VIA_DRILL/2 = 0.45 measured from the hole edge, which the
            # bounding box already contains. So one box test at `need`
            # rejects for all three.
            pad_need = VIA_DIA / 2.0 + VIA_PAD_GAP
            for o in self._near(x, y):
                if x < o.bx0 - need or x > o.bx1 + need or \
                   y < o.by0 - need or y > o.by1 + need:
                    continue
                if o.net != net and o.dist(x, y) < need - 1e-9:
                    r = False
                    break
                if isinstance(o, Shape):
                    if o.drill == 0.0:
                        # no via-in-pad: SMD pads block regardless of net
                        if o.dist(x, y) < pad_need:
                            r = False
                            break
                    # hole-to-hole clearance: applies regardless of net, and
                    # treats an oval drill as the capsule it is, not a circle
                    elif o.hole_dist(x, y) - VIA_DRILL / 2.0 < HOLE_TO_HOLE:
                        r = False
                        break
        self._memo[key] = r
        return r

    # --- routing ---
    def hop_clear(self, net, width, i, j, tx, ty, layer):
        """Is the final exact hop from grid node (i,j) to (tx, ty) legal?

        A* works on grid nodes, but a pad centre rarely lands on one, so
        _commit() finishes every route with a short free-hand segment from
        the last node to the true terminal. That segment used to be emitted
        unconditionally and was the *only* piece of copper on the board that
        no clearance check ever saw - it is what put `EN` 0.195 mm from U1
        pad 4 on the rung-2 board. Sampling it here, and only accepting a
        goal node whose hop passes, closes that hole.
        """
        x0, y0 = self.cell_xy(i, j)
        need = width / 2.0 + CLEAR
        d = math.hypot(tx - x0, ty - y0)
        n = max(1, int(d / 0.05))
        for k in range(n + 1):
            t = k / float(n)
            if not self._clear_of(net, x0 + (tx - x0) * t, y0 + (ty - y0) * t,
                                  layer, need):
                return False
        return True

    def _goal_nodes(self, net, width, tgt):
        """Grid nodes whose exact hop to `tgt` is clearance-legal.

        The snapped node itself stays exempt from `blocked` (it normally sits
        inside the target pad, which is own-net copper anyway); its eight
        neighbours are ordinary cells and must be free. Offering all nine
        rather than only the snapped one means a terminal whose own snap node
        cannot be reached legally is re-approached from a neighbour instead of
        silently emitting an illegal hop.
        """
        gi, gj = self.snap(tgt[0], tgt[1])
        out = []
        for di in (0, -1, 1):
            for dj in (0, -1, 1):
                i, j = gi + di, gj + dj
                if not (0 <= i < self.nx and 0 <= j < self.ny):
                    continue
                for l in tgt[2]:
                    if (di or dj) and self.blocked(net, width, i, j, l):
                        continue
                    if self.hop_clear(net, width, i, j, tgt[0], tgt[1], l):
                        out.append((i, j, l))
        return out

    # wrong_layer_cost was 0.4 in rev A - a 40% surcharge on every B.Cu step,
    # which kept the back layer as an escape hatch of last resort. That made
    # sense when B.Cu was mostly GND pour. On the 4-layer board the pour is
    # gone from both signal layers and B.Cu is genuinely empty, so at 0.10 the
    # router still prefers F.Cu but will run a whole net on the back rather
    # than fail.
    # via_cost was 14 in rev A, when a via had to punch through two GND pours.
    # It now punches two plane antipads instead, which the fill draws for free,
    # and the layer it reaches is empty. 4 grid steps (1 mm of detour at GRID
    # 0.25) is what a hop is actually worth here.
    def route(self, net, terminals, width, layer_pref=0, via_cost=4.0,
              wrong_layer_cost=0.10, allow_via=True, extra_srcs=()):
        """terminals: [(x, y, layers-tuple), ...]. First is the seed."""
        if len(terminals) < 2:
            return
        self._begin(net)
        srcs = {}
        tx, ty, tlay = terminals[0]
        i, j = self.snap(tx, ty)
        for l in tlay:
            srcs[(i, j, l)] = None
        for (ex, ey, el) in extra_srcs:
            ei, ej = self.snap(ex, ey)
            srcs[(ei, ej, el)] = None
        rest = list(terminals[1:])
        while rest:
            def key(t):
                return min(abs(t[0] - self.cell_xy(ii, jj)[0]) +
                           abs(t[1] - self.cell_xy(ii, jj)[1])
                           for (ii, jj, _l) in srcs)
            rest.sort(key=key)
            tgt = rest.pop(0)
            gx, gy = self.snap(tgt[0], tgt[1])
            goals = self._goal_nodes(net, width, tgt)
            path = None
            if goals:
                path = self._astar(net, width, srcs, (gx, gy), set(goals),
                                   via_cost, wrong_layer_cost, layer_pref,
                                   allow_via)
            if path is None:
                self.fail_at = (tgt[0], tgt[1])
                self.fail_pos[net] = self.fail_at
                gi, gj = self.snap(tgt[0], tgt[1])
                raise RuntimeError(
                    "route failed: net %s to (%.2f,%.2f) [%d goal node(s), "
                    "via_ok=%s, free neighbours F/B=%d/%d]"
                    % (net, tgt[0], tgt[1], len(goals),
                       self.via_ok(net, gi, gj),
                       sum(not self.blocked(net, width, gi + di, gj + dj, 0)
                           for di in (-1, 0, 1) for dj in (-1, 0, 1)),
                       sum(not self.blocked(net, width, gi + di, gj + dj, 1)
                           for di in (-1, 0, 1) for dj in (-1, 0, 1))))
            self._commit(net, width, path, tgt, srcs)

    DIRS = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
            (1, 1, 1.41421), (1, -1, 1.41421), (-1, 1, 1.41421), (-1, -1, 1.41421))

    @staticmethod
    def _octile(dx, dy):
        dx, dy = abs(dx), abs(dy)
        return max(dx, dy) + 0.41421 * min(dx, dy)

    def _astar(self, net, width, srcs, goal, goals, via_cost,
               wrong_layer_cost, layer_pref, allow_via, first_dir=None,
               last_dir=None):
        """Octilinear (45-degree) A*. Diagonal steps additionally require both
        adjacent orthogonal cells to be free so the trace body never clips an
        obstacle corner. Bend cost is graded: 45-degree turns are cheap,
        90-degree turns cost more, so paths come out straight or gently
        mitred rather than stair-stepped."""
        gx, gy = goal
        openq = []
        best = {}
        for (i, j, l) in srcs:
            heapq.heappush(openq, (self._octile(i - gx, j - gy), 0.0, (i, j, l)))
            best[(i, j, l)] = (0.0, None)
        visited = set()
        while openq:
            f, g, node = heapq.heappop(openq)
            if node in visited:
                continue
            visited.add(node)
            i, j, l = node[:3]
            # A goal is accepted when popped as itself (no last_dir) or as
            # the 4-tuple marker pushed below for an arrival in last_dir.
            if (len(node) == 4) or (last_dir is None and node in goals):
                path = [node[:3]]
                cur = node
                while best[cur][1] is not None:
                    cur = best[cur][1]
                    path.append(cur[:3])
                path.reverse()
                return path
            par = best[node][1]
            for di, dj, base in self.DIRS:
                # route_pair() pins the pair's first step to the direction
                # its hand-drawn lead-in already points: the two tracks are
                # offset perpendicular to the direction of travel, so the
                # first step decides where the lead-in has to have ended.
                if par is None and first_dir is not None and (di, dj) != first_dir:
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.nx and 0 <= nj < self.ny):
                    continue
                nnode = (ni, nj, l)
                if nnode in visited:
                    continue
                is_goal = nnode in goals
                # route_pair() can also pin the LAST step: the two tracks are
                # offset perpendicular to the arrival, and a pair arriving on
                # a diagonal fans into a pad row with its fans converging
                # below clearance before they open. A goal reached in any
                # other direction is only a node on the way to one reached
                # correctly, and is pushed as such (and clearance-checked as
                # such); the accepted arrival is a separate marker node so
                # that a wrong-direction visit does not consume it.
                accept = is_goal and (last_dir is None or (di, dj) == last_dir)
                if not (is_goal and last_dir is None) and \
                   self.blocked(net, width, ni, nj, l):
                    if not accept:
                        continue
                if di and dj:
                    # no corner-clipping between diagonal neighbours
                    if self.blocked(net, width, i + di, j, l) or                        self.blocked(net, width, i, j + dj, l):
                        continue
                step = base + (wrong_layer_cost if l != layer_pref else 0.0)
                if par is not None and par[2] == l:
                    pdi, pdj = i - par[0], j - par[1]
                    if (pdi, pdj) != (di, dj):
                        dot = pdi * di + pdj * dj
                        if dot > 0:
                            step += 0.08      # 45-degree turn
                        elif dot == 0:
                            step += 0.35      # 90-degree turn
                        else:
                            step += 1.5       # reversal / acute: avoid
                ng = g + step
                h = self._octile(ni - gx, nj - gy)
                if accept and last_dir is not None:
                    mark = (ni, nj, l, 1)
                    if mark not in visited:
                        old = best.get(mark)
                        if old is None or ng < old[0] - 1e-9:
                            best[mark] = (ng, node)
                            heapq.heappush(openq, (ng + h, ng, mark))
                    if self.blocked(net, width, ni, nj, l):
                        continue            # accepted as a goal, not as transit
                old = best.get(nnode)
                if old is None or ng < old[0] - 1e-9:
                    best[nnode] = (ng, node)
                    heapq.heappush(openq, (ng + h, ng, nnode))
            if allow_via:
                nnode = (i, j, 1 - l)
                # The track resumes at this node on the far layer, so that
                # node has to clear the track's own width - via_ok() only
                # answers for the 0.6 mm via barrel. Without this the first
                # segment after a via was never clearance-checked at its
                # start point, which at 0.25 mm tracks stayed inside the
                # via's own envelope and hid, and at rev A's 0.7 mm power
                # width put AUX_VP 0.172 mm from SJ1 pad 1.
                if nnode not in visited and self.via_ok(net, i, j) and \
                   not self.blocked(net, width, i, j, 1 - l):
                    ng = g + via_cost
                    old = best.get(nnode)
                    if old is None or ng < old[0] - 1e-9:
                        best[nnode] = (ng, node)
                        heapq.heappush(openq, (ng + self._octile(i - gx, j - gy),
                                               ng, nnode))
        return None

    def _commit(self, net, width, path, tgt, srcs):
        pts = [(self.cell_xy(i, j), l) for (i, j, l) in path]
        runs = []          # (layer, [xy...])
        cur_layer = pts[0][1]
        cur_pts = [pts[0][0]]
        for (xy, l) in pts[1:]:
            if l != cur_layer:
                runs.append((cur_layer, cur_pts))
                self.add_via(net, xy[0], xy[1])
                cur_layer = l
                cur_pts = [xy]
            else:
                cur_pts.append(xy)
        runs.append((cur_layer, cur_pts))
        if net in DEBUG_NETS:
            print("    DBG %s tgt=(%.3f,%.3f,%s) runs=%s" %
                  (net, tgt[0], tgt[1], tgt[2],
                   [(l, len(c), c[0], c[-1]) for l, c in runs]))
        for layer, coords in runs:
            if len(coords) < 2:
                continue
            simp = [coords[0]]
            for k in range(1, len(coords) - 1):
                x0, y0 = simp[-1]
                x1, y1 = coords[k]
                x2, y2 = coords[k + 1]
                if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-9:
                    continue
                simp.append(coords[k])
            simp.append(coords[-1])
            for a, b in zip(simp, simp[1:]):
                if a != b:
                    self.add_seg(net, layer, a[0], a[1], b[0], b[1], width)
        # exact hop to true terminal position
        lxy = pts[-1][0]
        llayer = pts[-1][1]
        if abs(lxy[0] - tgt[0]) > 1e-6 or abs(lxy[1] - tgt[1]) > 1e-6:
            self.add_seg(net, llayer, lxy[0], lxy[1], tgt[0], tgt[1], width)
        for node in path:
            srcs[node] = None
        # memo entries for own-net copper stay valid (own net never blocks self)


    # --- differential pair -------------------------------------------------
    def _pair_ends(self, pair, W, layer, cx, cy, radius):
        """Grid nodes within `radius` of (cx, cy) that a track of width W may
        occupy, nearest first. Ties break on (i, j) so the choice is
        deterministic."""
        i0, j0 = self.snap(cx, cy)
        span = int(math.ceil(radius / GRID))
        out = []
        for di in range(-span, span + 1):
            for dj in range(-span, span + 1):
                i, j = i0 + di, j0 + dj
                if not (0 <= i < self.nx and 0 <= j < self.ny):
                    continue
                x, y = self.cell_xy(i, j)
                d = math.hypot(x - cx, y - cy)
                if d > radius + 1e-9 or self.blocked(pair, W, i, j, layer):
                    continue
                out.append((round(d, 6), i, j))
        return [(i, j) for (_d, i, j) in sorted(out)]

    def _seg_clear(self, net, layer, need, a, b, step=0.05):
        """Sampled clearance of the segment a-b, as hop_clear() does it."""
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(d / step))
        for k in range(n + 1):
            t = k / float(n)
            if not self._clear_of(net, a[0] + (b[0] - a[0]) * t,
                                  a[1] + (b[1] - a[1]) * t, layer, need):
                return False
        return True

    @staticmethod
    def _simplify(pts):
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = out[-1], pts[k], pts[k + 1]
            if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-9:
                continue
            out.append(pts[k])
        out.append(pts[-1])
        return out

    def _pair_chamfer(self, pair, W, layer, pts, c=2 * GRID):
        """Cut every right angle in the centreline to a 45-degree chamfer of
        leg `c`, where the chamfer body clears foreign copper at the pair's
        full width.

        Offsetting a polyline moves copper: the outer track of a 90-degree
        corner is longer than the inner one by two offsets (0.5 mm here), and
        at 45 degrees by a fifth of that. miter_corners() would soften the
        corner afterwards, but one track at a time with its own leg length,
        which is how a matched pair picks up skew. Doing it on the centreline
        keeps both tracks the same shape. A chamfer that does not clear is
        left as the right angle it was.
        """
        out = [pts[0]]
        need = W / 2.0 + CLEAR
        for k in range(1, len(pts) - 1):
            p0, p1, p2 = out[-1], pts[k], pts[k + 1]
            u1 = (p1[0] - p0[0], p1[1] - p0[1])
            u2 = (p2[0] - p1[0], p2[1] - p1[1])
            l1, l2 = math.hypot(*u1), math.hypot(*u2)
            if l1 < 2 * c - 1e-9 or l2 < 2 * c - 1e-9 or \
               abs(u1[0] * u2[0] + u1[1] * u2[1]) > 1e-9 * l1 * l2 + 1e-9:
                out.append(p1)          # not a right angle, or too short
                continue
            a = (p1[0] - u1[0] / l1 * c, p1[1] - u1[1] / l1 * c)
            b = (p1[0] + u2[0] / l2 * c, p1[1] + u2[1] / l2 * c)
            if self._seg_clear(pair, layer, need, a, b):
                out.extend([a, b])
            else:
                out.append(p1)
        out.append(pts[-1])
        return out

    @staticmethod
    def _offset(pts, delta):
        """Polyline `pts` shifted by `delta` along its left normal, with
        mitred joins. Positive delta is the side where cross(dir, p) > 0."""
        def normal(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            return (-dy / L, dx / L)
        ns = [normal(a, b) for a, b in zip(pts, pts[1:])]
        out = [(pts[0][0] + delta * ns[0][0], pts[0][1] + delta * ns[0][1])]
        for k in range(1, len(pts) - 1):
            n1, n2 = ns[k - 1], ns[k]
            dot = n1[0] * n2[0] + n1[1] * n2[1]
            f = delta / (1.0 + dot)
            out.append((pts[k][0] + f * (n1[0] + n2[0]),
                        pts[k][1] + f * (n1[1] + n2[1])))
        out.append((pts[-1][0] + delta * ns[-1][0],
                    pts[-1][1] + delta * ns[-1][1]))
        return out

    @staticmethod
    def _seg_gap(s1, s2, step=0.05):
        """Centre-to-centre distance between two segments, sampled."""
        def pts(s):
            (ax, ay), (bx, by) = s
            n = max(1, int(math.hypot(bx - ax, by - ay) / step))
            return [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(n + 1)]
        best = float("inf")
        for (x, y) in pts(s1):
            d = Seg(None, 0, s2[0][0], s2[0][1], s2[1][0], s2[1][1], 0.0).dist(x, y)
            if d < best:
                best = d
        return best

    @staticmethod
    def _cross_side(a, b, p):
        """Sign of p relative to the directed line a->b (0 on the line)."""
        c = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        return 0 if abs(c) < 1e-9 else (1 if c > 0 else -1)

    @classmethod
    def _segs_cross(cls, a, b, c, d):
        """Proper crossing of segments a-b and c-d (shared endpoints don't
        count)."""
        s1, s2 = cls._cross_side(a, b, c), cls._cross_side(a, b, d)
        s3, s4 = cls._cross_side(c, d, a), cls._cross_side(c, d, b)
        return s1 * s2 < 0 and s3 * s4 < 0

    def route_pair(self, net_a, net_b, start, goal, width, gap, layer=0,
                   first_dir=None, last_dir=None, fan_r=2.0):
        """Route nets a and b as an edge-coupled pair on one layer.

        `start` and `goal` are ((xa, ya), (xb, yb)): where each net's copper
        is at the two ends - a hand-drawn lead-in's last point, a pad centre.
        The pair is found as ONE track of width 2*width+gap down the
        centreline (so clearance is checked for the pair's full envelope, and
        neither net's own copper counts - see PairNet), then split into two
        tracks `width` wide, `gap` apart, and each joined to its terminal by
        a straight fan. Which side each net takes is read off the geometry
        at both ends and has to agree, or the pair would need a crossover;
        that is reported rather than routed. No vias: a via pair cannot hold
        the gap, and the one pair on this board fits one layer.

        `first_dir` pins the first step, for a lead-in that already ends in
        a coupled straight; `last_dir` pins the last, so the pair meets a
        pad row square-on and its fans open from the pair pitch rather than
        first converging below it. The fans are validated for clearance and for not
        crossing each other or the other net's track; a start node whose fans
        fail is skipped for the next nearest, so the ends can be reshaped by
        moving copper rather than by editing this.

        Returns {net: [(x, y), ...]} - each track's polyline, fans included.
        Everything committed is `fixed`: rip-up may not touch it.
        """
        pair = PairNet(net_a, net_b)
        # The pair's own PADS stay obstacles while it SEARCHES. Only the
        # lead-in copper (Segs) is shared: a fat centreline that ran across
        # one member's pad would be one track over a foreign pad once split,
        # and the terminal pads are where the two tracks part company by
        # design - the fans make that last hop, one net at a time, and for
        # THAT test each pad has to be its own net again. So the pads are
        # relabelled around the search and restored around the validation.
        own_pads = [(o, o.net) for o in self.pads if o.net == pair]

        def hide_pads(hide):
            for o, net in own_pads:
                o.net = "__pair_pad__" if hide else net
            self._memo, self._memo_net = {}, pair

        try:
            return self._route_pair(pair, net_a, net_b, start, goal, width,
                                    gap, layer, first_dir, last_dir, fan_r,
                                    hide_pads)
        finally:
            hide_pads(False)
            self._memo, self._memo_net = {}, None

    def _route_pair(self, pair, net_a, net_b, start, goal, width, gap, layer,
                    first_dir, last_dir, fan_r, hide_pads):
        hide_pads(True)
        W = 2 * width + gap
        d = (width + gap) / 2.0
        (a0, b0), (a1, b1) = start, goal
        c0 = ((a0[0] + b0[0]) / 2.0, (a0[1] + b0[1]) / 2.0)
        c1 = ((a1[0] + b1[0]) / 2.0, (a1[1] + b1[1]) / 2.0)
        starts = self._pair_ends(pair, W, layer, c0[0], c0[1], fan_r)
        goals = self._pair_ends(pair, W, layer, c1[0], c1[1], fan_r)
        if not starts or not goals:
            raise RuntimeError("pair %s: no free node within %.2f mm of %s"
                               % (pair, fan_r, "start" if not starts else "goal"))
        gi, gj = self.snap(c1[0], c1[1])
        need = width / 2.0 + CLEAR
        why = []
        for (si, sj) in starts:
            # A* stops at whichever goal node is cheapest, and the cheapest is
            # often the wrong one: a node the pair reaches with both terminals
            # on the same side, or from which a fan would cross the other
            # track. So a goal that fails validation is struck off and the
            # search re-run from the same start, until the set is exhausted.
            goal_set = set((i, j, layer) for (i, j) in goals)
            while goal_set:
                hide_pads(True)
                path = self._astar(pair, W, {(si, sj, layer): None}, (gi, gj),
                                   goal_set, 0.0, 0.0, layer, False,
                                   first_dir=first_dir, last_dir=last_dir)
                if path is None:
                    # Free space is one connected thing: a goal this start
                    # cannot reach, no neighbouring start can either.
                    why.append("no path from (%.2f, %.2f) to %d goal(s)"
                               % (self.cell_xy(si, sj) + (len(goal_set),)))
                    raise RuntimeError("pair %s route failed: %s"
                                       % (pair, "; ".join(why[-6:])))
                goal_set.discard(path[-1])
                pts = self._simplify([self.cell_xy(i, j) for (i, j, _l) in path])
                pts = self._pair_chamfer(pair, W, layer, pts)
                hide_pads(False)
                # Which side of the centreline each net rides: the assignment
                # with the shorter fans. A side test at each end was tried
                # first and is wrong for a pair arriving on a diagonal, where
                # both pads lie to one side of the extended centreline and
                # the fans simply open by different amounts. Whether the
                # fans cross is tested below, and that is the real question.
                def fans(sign):
                    tr = {net_a: self._offset(pts, sign * d),
                          net_b: self._offset(pts, -sign * d)}
                    L = sum(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in
                            ((a0, tr[net_a][0]), (b0, tr[net_b][0]),
                             (tr[net_a][-1], a1), (tr[net_b][-1], b1)))
                    return L, tr
                tracks = min((fans(1), fans(-1)), key=lambda t: t[0])[1]
                ok = True
                for net, term0, term1 in ((net_a, a0, a1), (net_b, b0, b1)):
                    tr = tracks[net]
                    other = tracks[net_b if net is net_a else net_a]
                    # fans: terminal -> first track point, last track point -> terminal
                    for (fa, fb, first) in ((term0, tr[0], True), (tr[-1], term1, False)):
                        if math.hypot(fb[0] - fa[0], fb[1] - fa[1]) < 1e-6:
                            continue
                        # Checked as the net itself, not the pair: near the
                        # terminals the other net's pads and lead-in are
                        # foreign copper this fan must clear.
                        if not self._seg_clear(net, layer, need, fa, fb):
                            ok = False
                            why.append("%s fan (%.2f,%.2f)-(%.2f,%.2f) not clear"
                                       % ((net,) + fa + fb))
                        ends = (other[0], other[1]) if first else (other[-2], other[-1])
                        if self._segs_cross(fa, fb, ends[0], ends[1]):
                            ok = False
                            why.append("%s fan crosses the other track" % net)
                    for p, q in zip(tr, tr[1:]):
                        if not self._seg_clear(net, layer, need, p, q):
                            ok = False
                            why.append("%s track (%.2f,%.2f)-(%.2f,%.2f) not clear"
                                       % ((net,) + p + q))
                            break
                if ok:
                    # The two fans at one end against each other: neither is
                    # in the model yet, so this is the only test they get.
                    for label, fa, fb in (
                            ("start", (a0, tracks[net_a][0]), (b0, tracks[net_b][0])),
                            ("goal", (tracks[net_a][-1], a1), (tracks[net_b][-1], b1))):
                        if self._segs_cross(fa[0], fa[1], fb[0], fb[1]):
                            ok = False
                            why.append("%s fans cross" % label)
                        elif self._seg_gap(fa, fb) < width + CLEAR - 1e-9:
                            ok = False
                            why.append("%s fans %.2f mm apart" % (label, self._seg_gap(fa, fb)))
                if not ok:
                    if net_a in DEBUG_NETS or net_b in DEBUG_NETS:
                        print("    DBG pair start (%.2f, %.2f) rejected: %s"
                              % (self.cell_xy(si, sj) + ("; ".join(why[-4:]),)))
                    continue
                out = {}
                for net, term0, term1 in ((net_a, a0, a1), (net_b, b0, b1)):
                    poly = [term0] + tracks[net] + [term1]
                    poly = [p for k, p in enumerate(poly)
                            if k == 0 or math.hypot(p[0] - poly[k - 1][0],
                                                    p[1] - poly[k - 1][1]) > 1e-6]
                    for p, q in zip(poly, poly[1:]):
                        self.add_seg(net, layer, p[0], p[1], q[0], q[1], width,
                                     fixed=True)
                    out[net] = poly
                self._memo, self._memo_net = {}, None
                return out
        raise RuntimeError("pair %s route failed: %s" % (pair, "; ".join(why[:6])))

    # --- post-pass: 45-degree mitering of remaining right-angle corners ---
    def miter_corners(self, max_miter=1.0, min_miter=0.25):
        """Replace 90-degree corners between exactly two same-net segments
        with a 45-degree chamfer. Each chamfer is validated against the full
        obstacle model (which still holds the un-mitred copper of every other
        net, so validation is conservative); applied chamfers are inserted
        into the model so later chamfers see them."""
        from collections import defaultdict
        # A chamfer pulls BOTH segment ends away from the corner, so anything
        # that was joined to the copper *at* the corner is left behind. The
        # "exactly two segments" test below covers a third track, but not a
        # via or a pad, and a via sitting on a mitred corner is silently
        # orphaned: its track keeps its net, so nothing but KiCad's own
        # connectivity pass notices (it was two of the dangling vias and the
        # 7.4 mm stranded SSR_EN track on the first 4-layer build).
        via_pts = {(round(v[1], 3), round(v[2], 3)) for v in self.result_vias}
        byend = defaultdict(list)
        for s in self.result_tracks:
            byend[(round(s.x1, 3), round(s.y1, 3), s.layer)].append((s, 1))
            byend[(round(s.x2, 3), round(s.y2, 3), s.layer)].append((s, 2))
        applied = 0
        new_segs = []
        for (px, py, layer), ends in byend.items():
            if len(ends) != 2:
                continue
            (sa, ea), (sb, eb) = ends
            if sa is sb or sa.net != sb.net or abs(sa.w - sb.w) > 1e-6:
                continue
            if (px, py) in via_pts:
                continue
            if any(isinstance(o, Shape) and o.net == sa.net and o.drill == 0.0
                   and o.dist(px, py) <= 0.0 for o in self._near(px, py)):
                continue        # corner lands on its own pad

            def other(s, e):
                return (s.x1, s.y1) if e == 2 else (s.x2, s.y2)

            ax, ay = other(sa, ea)
            bx, by = other(sb, eb)
            va = (ax - px, ay - py)
            vb = (bx - px, by - py)
            la = math.hypot(*va)
            lb = math.hypot(*vb)
            if la < 1e-6 or lb < 1e-6:
                continue
            if abs(va[0] * vb[0] + va[1] * vb[1]) > 1e-6 * la * lb + 1e-9:
                continue  # not a right angle
            m = min(max_miter, la * 0.5, lb * 0.5)
            if m < min_miter:
                continue
            ua = (va[0] / la, va[1] / la)
            ub = (vb[0] / lb, vb[1] / lb)
            pax, pay = px + ua[0] * m, py + ua[1] * m
            pbx, pby = px + ub[0] * m, py + ub[1] * m
            # validate the chamfer body against foreign copper
            need = sa.w / 2.0 + CLEAR - 0.005
            ok = True
            for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                sxp = pax + (pbx - pax) * t
                syp = pay + (pby - pay) * t
                if not self._clear_of(sa.net, sxp, syp, layer, need):
                    ok = False
                    break
            if not ok:
                continue
            # shorten both segments to the chamfer points
            if ea == 1:
                sa.x1, sa.y1 = pax, pay
            else:
                sa.x2, sa.y2 = pax, pay
            if eb == 1:
                sb.x1, sb.y1 = pbx, pby
            else:
                sb.x2, sb.y2 = pbx, pby
            ch = Seg(sa.net, layer, pax, pay, pbx, pby, sa.w)
            self._insert(ch, min(pax, pbx) - sa.w, min(pay, pby) - sa.w,
                         max(pax, pbx) + sa.w, max(pay, pby) + sa.w)
            new_segs.append(ch)
            applied += 1
        self.result_tracks.extend(new_segs)
        return applied
