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
# which a 0.25 mm track clears. The cost is ~2.5x the cells and a slower route.
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


class Shape:
    """Axis-aligned rect or circle, on layer set. net None = blocks all."""
    __slots__ = ("net", "layers", "cx", "cy", "w", "h", "circle", "drill")

    def __init__(self, net, layers, cx, cy, w, h, circle=False, drill=0.0):
        self.net, self.layers = net, set(layers)
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.circle = circle
        self.drill = drill

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
    __slots__ = ("net", "layer", "x1", "y1", "x2", "y2", "w", "fixed")

    def __init__(self, net, layer, x1, y1, x2, y2, w, fixed=False):
        self.net, self.layer = net, layer
        self.x1, self.y1, self.x2, self.y2, self.w = x1, y1, x2, y2, w
        self.fixed = fixed

    def dist(self, x, y):
        dx, dy = self.x2 - self.x1, self.y2 - self.y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((x - self.x1) * dx + (y - self.y1) * dy) / L2))
        px, py = self.x1 + t * dx, self.y1 + t * dy
        return math.hypot(x - px, y - py) - self.w / 2.0


class Router:
    def __init__(self, x0, y0, x1, y1, edge_margin=0.65):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.nx = int(round((x1 - x0) / GRID)) + 1
        self.ny = int(round((y1 - y0) / GRID)) + 1
        self.margin = edge_margin
        self.keepouts = []
        self.buckets = {}   # (bx,by) -> list of Shape/Seg
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
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                self.buckets.setdefault((bx, by), []).append(obj)

    def add_pad(self, net, layers, cx, cy, w, h, circle=False, drill=0.0):
        s = Shape(net, layers, cx, cy, w, h, circle, drill=drill)
        self.pads.append(s)
        self._insert(s, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    def add_keepout(self, x0, y0, x1, y1, allow_nets=()):
        """Rectangle no track or via may enter, except for `allow_nets`.

        The exemption exists for the opto-isolation barrier: the band is a
        pour keepout in KiCad (see kicad_build.add_zones) and must equally be
        a *routing* keepout here, or a plane via lands inside it and DRC
        reports it. But the isolated SSR*_A/B nets have to
        cross it - the whole point is that their copper is the only copper in
        there - so they are exempted by name rather than by geometry."""
        self.keepouts.append((x0, y0, x1, y1, frozenset(allow_nets)))

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
        bx, by = int(x // BUCKET), int(y // BUCKET)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in self.buckets.get((bx + dx, by + dy), ()):
                    yield o

    def cell_xy(self, i, j):
        return self.x0 + i * GRID, self.y0 + j * GRID

    def snap(self, x, y):
        return (int(round((x - self.x0) / GRID)), int(round((y - self.y0) / GRID)))

    def _begin(self, net):
        if self._memo_net != net:
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
        for o in self._near(x, y):
            if o.net == net:
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
            if net in k[4]:
                continue
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
                if net in k[4]:
                    continue
                if k[0] - need < x < k[2] + need and k[1] - need < y < k[3] + need:
                    r = False
                    break
        if r:
            r = self._clear_of(net, x, y, 0, need, check_layer=False)
        if r:
            # no via-in-pad: SMD pads (drill == 0) block regardless of net
            for o in self._near(x, y):
                if isinstance(o, Shape) and o.drill == 0.0 and \
                   o.dist(x, y) < VIA_DIA / 2.0 + VIA_PAD_GAP:
                    r = False
                    break
        if r:
            # hole-to-hole clearance: applies regardless of net
            for o in self._near(x, y):
                if isinstance(o, Shape) and o.drill > 0:
                    if math.hypot(x - o.cx, y - o.cy) - o.drill / 2                        - VIA_DRILL / 2 < 0.3:
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
               wrong_layer_cost, layer_pref, allow_via):
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
            i, j, l = node
            if node in goals:
                path = [node]
                cur = node
                while best[cur][1] is not None:
                    cur = best[cur][1]
                    path.append(cur)
                path.reverse()
                return path
            par = best[node][1]
            for di, dj, base in self.DIRS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.nx and 0 <= nj < self.ny):
                    continue
                nnode = (ni, nj, l)
                if nnode in visited:
                    continue
                is_goal = nnode in goals
                if not is_goal and self.blocked(net, width, ni, nj, l):
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
                old = best.get(nnode)
                if old is None or ng < old[0] - 1e-9:
                    best[nnode] = (ng, node)
                    heapq.heappush(openq, (ng + self._octile(ni - gx, nj - gy),
                                           ng, nnode))
            if allow_via:
                nnode = (i, j, 1 - l)
                if nnode not in visited and self.via_ok(net, i, j):
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
