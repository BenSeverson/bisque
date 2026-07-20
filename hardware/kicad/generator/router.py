"""Two-layer grid autorouter (A*) for the bisque controller board.

Board mm coordinates. Obstacles are exact copper shapes (pads, routed
tracks/vias, antenna keepout, board margin) checked with true clearance
(edge distance >= CLEAR). Multi-terminal nets route incrementally: each
terminal connects to the growing net copper via A*.
"""
import heapq
import math

GRID = 0.4          # mm per cell
CLEAR = 0.2         # required copper-to-copper clearance
VIA_DIA = 0.6
VIA_DRILL = 0.3
BUCKET = 2.0


class Shape:
    """Axis-aligned rect or circle, on layer set. net None = blocks all."""
    __slots__ = ("net", "layers", "cx", "cy", "w", "h", "circle")

    def __init__(self, net, layers, cx, cy, w, h, circle=False):
        self.net, self.layers = net, set(layers)
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.circle = circle

    def dist(self, x, y):
        if self.circle:
            return math.hypot(x - self.cx, y - self.cy) - self.w / 2.0
        dx = max(abs(x - self.cx) - self.w / 2.0, 0.0)
        dy = max(abs(y - self.cy) - self.h / 2.0, 0.0)
        return math.hypot(dx, dy)

    def reach(self):
        return (max(self.w, self.h) / 2.0)


class Seg:
    __slots__ = ("net", "layer", "x1", "y1", "x2", "y2", "w")

    def __init__(self, net, layer, x1, y1, x2, y2, w):
        self.net, self.layer = net, layer
        self.x1, self.y1, self.x2, self.y2, self.w = x1, y1, x2, y2, w

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
        self.result_tracks = []   # Seg (all routed, incl. seeds)
        self.result_vias = []     # (net, x, y)
        self._memo = {}
        self._memo_net = None

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

    def add_pad(self, net, layers, cx, cy, w, h, circle=False):
        s = Shape(net, layers, cx, cy, w, h, circle)
        self._insert(s, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    def add_keepout(self, x0, y0, x1, y1):
        self.keepouts.append((x0, y0, x1, y1))

    def add_seg(self, net, layer, x1, y1, x2, y2, w, record=True):
        s = Seg(net, layer, x1, y1, x2, y2, w)
        self._insert(s, min(x1, x2) - w / 2, min(y1, y2) - w / 2,
                     max(x1, x2) + w / 2, max(y1, y2) + w / 2)
        if record:
            self.result_tracks.append(s)

    def add_via(self, net, x, y, record=True):
        s = Shape(net, (0, 1), x, y, VIA_DIA, VIA_DIA, circle=True)
        self._insert(s, x - VIA_DIA / 2, y - VIA_DIA / 2, x + VIA_DIA / 2, y + VIA_DIA / 2)
        if record:
            self.result_vias.append((net, x, y))

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
            r = self._clear_of(net, x, y, 0, need, check_layer=False)
        self._memo[key] = r
        return r

    # --- routing ---
    def route(self, net, terminals, width, layer_pref=0, via_cost=14.0,
              wrong_layer_cost=0.4, allow_via=True, extra_srcs=()):
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
            path = self._astar(net, width, srcs, (gx, gy), set(tgt[2]),
                               via_cost, wrong_layer_cost, layer_pref, allow_via)
            if path is None:
                raise RuntimeError("route failed: net %s to (%.2f,%.2f)"
                                   % (net, tgt[0], tgt[1]))
            self._commit(net, width, path, tgt, srcs)

    def _astar(self, net, width, srcs, goal, goal_layers, via_cost,
               wrong_layer_cost, layer_pref, allow_via):
        gx, gy = goal
        openq = []
        best = {}
        for (i, j, l) in srcs:
            h = abs(i - gx) + abs(j - gy)
            heapq.heappush(openq, (h, 0.0, (i, j, l)))
            best[(i, j, l)] = (0.0, None)
        visited = set()
        while openq:
            f, g, node = heapq.heappop(openq)
            if node in visited:
                continue
            visited.add(node)
            i, j, l = node
            if (i, j) == (gx, gy) and l in goal_layers:
                path = [node]
                cur = node
                while best[cur][1] is not None:
                    cur = best[cur][1]
                    path.append(cur)
                path.reverse()
                return path
            par = best[node][1]
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.nx and 0 <= nj < self.ny):
                    continue
                nnode = (ni, nj, l)
                if nnode in visited:
                    continue
                if not ((ni, nj) == (gx, gy) and l in goal_layers):
                    if self.blocked(net, width, ni, nj, l):
                        continue
                step = 1.0 + (wrong_layer_cost if l != layer_pref else 0.0)
                if par is not None and par[2] == l:
                    if (i - par[0], j - par[1]) != (di, dj):
                        step += 0.15
                ng = g + step
                old = best.get(nnode)
                if old is None or ng < old[0] - 1e-9:
                    best[nnode] = (ng, node)
                    heapq.heappush(openq, (ng + abs(ni - gx) + abs(nj - gy), ng, nnode))
            if allow_via:
                nnode = (i, j, 1 - l)
                if nnode not in visited and self.via_ok(net, i, j):
                    ng = g + via_cost
                    old = best.get(nnode)
                    if old is None or ng < old[0] - 1e-9:
                        best[nnode] = (ng, node)
                        heapq.heappush(openq, (ng + abs(i - gx) + abs(j - gy), ng, nnode))
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
