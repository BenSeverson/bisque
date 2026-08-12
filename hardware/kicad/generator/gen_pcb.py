"""Generate bisque-controller.kicad_pcb (KiCad 9 format).

Embeds the official library footprints, assigns nets from design.py,
autoroutes signal/power nets with router.py, adds the inner GND/+3V3
planes (unfilled — press 'B' in pcbnew), edge cuts and silkscreen labels.
"""
import math
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all, Sym, num, dump
from design import COMPONENTS, netlist, BX0, BY0, BX1, BY1
import router as R

NS = uuid.UUID("8d0c2f6e-5b5c-4e2b-8d44-234567890abc")
FPDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fp")


def uid(*key):
    return str(uuid.uuid5(NS, "/".join(str(k) for k in key)))


def sch_sym_uuid(ref):
    # must match gen_sch.py's uid("sym", ref) namespace
    ns = uuid.UUID("7c9b1f5e-4a4b-4d1a-9c33-1234567890ab")
    return str(uuid.uuid5(ns, "sym/%s" % ref))


def f(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


_fp_cache = {}


def load_fp(fname):
    if fname not in _fp_cache:
        with open(os.path.join(FPDIR, fname)) as fh:
            _fp_cache[fname] = parse(fh.read())[0]
    return _fp_cache[fname]


def rot_xy(lx, ly, rot):
    a = math.radians(rot)
    c, s = round(math.cos(a)), round(math.sin(a))
    return (lx * c + ly * s, -lx * s + ly * c)


def pad_geometry(comp):
    """Yield (padname, kind, gx, gy, eff_w, eff_h, circle, layers, drill)."""
    fp = load_fp(comp["fpf"])
    fx, fy, frot = comp["at"]
    for p in find_all(fp, "pad"):
        name = p[1]
        kind = str(p[2])
        shape = str(p[3])
        at = find(p, "at")
        lx, ly = num(at[1]), num(at[2])
        pa = num(at[3]) if len(at) > 3 else 0.0
        size = find(p, "size")
        w, h = num(size[1]), num(size[2])
        lay = find(p, "layers")
        laystr = " ".join(str(e) for e in lay[1:]) if lay else ""
        if "Cu" not in laystr:
            continue  # paste/mask-only pad, no copper
        gx, gy = rot_xy(lx, ly, frot)
        gx += fx
        gy += fy
        tot = (pa + frot) % 180
        if abs(tot - 90) < 1:
            w, h = h, w
        circle = shape == "circle"
        drill = 0.0
        if kind in ("thru_hole", "np_thru_hole"):
            layers = (0, 1)
            dr = find(p, "drill")
            # a plated pad always has a hole; fall back to the min JLCPCB
            # drill rather than 0, which the router reads as "SMD pad"
            drill = num(dr[1]) if dr and len(dr) > 1 else 0.3
        else:
            layers = (0,)
        yield (str(name), kind, gx, gy, w, h, circle, layers, drill)


# Opto-isolation barrier (spec 6.2). The band spans the west edge from just
# above J4 to just below J9 and stops short of the optocouplers' input pins, so
# every scrap of isolated copper - J4/J9 and U8/U9 pins 3 and 4 - sits inside
# it and no pour reaches within ~5 mm of any of it. Placement, the pour keepout
# and the router keepout all move together; kicad_build.py imports these.
ISO_BARRIER = (20.0, 71.0, 40.8, 95.5)
ISO_NETS = ("SSR1_A", "SSR1_B", "SSR2_A", "SSR2_B")


def build_router():
    r = R.Router(BX0, BY0, BX1, BY1)
    # No antenna keepout: rev B's WROOM-1U has no PCB antenna (spec 2.1).
    r.add_keepout(*ISO_BARRIER, allow_nets=ISO_NETS)
    pad_pos = {}
    for ref, c in COMPONENTS.items():
        for (name, kind, gx, gy, w, h, circle, layers, drill) in pad_geometry(c):
            if kind == "np_thru_hole" or name == "":
                net = None
            else:
                net = c["pins"].get(name)
                if net is None:
                    net = "__nc_%s_%s" % (ref, name)
            r.add_pad(net, layers, gx, gy, w, h, circle, drill=drill)
            if name:
                pad_pos.setdefault((ref, name), []).append((gx, gy, layers, w * h))
    return r, pad_pos


# Pre-seeded copper: hand-drawn escapes off J1's 0.5 mm-pitch pad row, which
# is finer than the router's 0.4 mm grid. J1 sits on the *top* edge in rev B
# (rot 180, x 42.7..53.3, y 20.2..29.7), so its single pad row is at y 28.445
# and every escape runs south into the board.
#
# The two D+ pads and the two D- pads interleave (DP 47.25, DN 47.75, DP
# 48.25, DN 48.75), so one net's pad-to-pad link has to hop the other's. The
# rev A trick still applies: nest the loops. D+ (the outer-left pair) is tied
# *under the connector body* to the north and escapes on the west side; D-
# (the outer-right pair) is tied in open board to the south and escapes on the
# east side. Neither loop is ever crossed.
USB_SEEDS = [  # (net, layer, [(x,y)...], width)
    ("USB_DP", 0, [(47.25, 28.445), (47.25, 27.2), (48.25, 27.2),
                   (48.25, 28.445)], 0.25),
    ("USB_DP", 0, [(47.25, 28.445), (47.25, 31.25)], 0.25),
    # The D- link ran (47.75 pad) -> south -> across -> south to the escape
    # point and never actually touched the second D- pad at x 48.75, which sits
    # 1.5 mm *north* of where the link crossed; J1.B7 came out unconnected. Two
    # polylines, mirroring the D+ pair above: the link, and the escape run
    # started at the pad it is supposed to leave from.
    ("USB_DN", 0, [(47.75, 28.445), (47.75, 30.0), (48.75, 30.0)], 0.25),
    ("USB_DN", 0, [(48.75, 28.445), (48.75, 31.25)], 0.25),
    ("CC1", 0, [(49.25, 28.445), (49.25, 31.75)], 0.25),
    ("CC2", 0, [(46.25, 28.445), (46.25, 31.75)], 0.25),
    ("VBUS", 0, [(50.45, 28.445), (50.45, 32.0), (50.5, 32.0)], 0.4),
    ("VBUS", 0, [(45.55, 28.445), (45.55, 32.0), (45.5, 32.0)], 0.4),
]
MANUAL_VIAS = []
# nets whose J1 pads are replaced by stub terminals (ends grid-aligned)
USB_STUB_TERMS = {
    "USB_DN": [(48.75, 31.25, (0,))],
    "USB_DP": [(47.25, 31.25, (0,))],
    "CC1": [(49.25, 31.75, (0,))],
    "CC2": [(46.25, 31.75, (0,))],
    "VBUS": [(50.5, 32.0, (0,)), (45.5, 32.0, (0,))],
}

# ---------------------------------------------------------------------------
# Fine-pitch fanout
# ---------------------------------------------------------------------------
# ref -> radial stub length (mm) measured from the pad centre.
#
# A track can only leave a 0.5 mm-pitch QFN or a 0.65 mm-pitch TSSOP along the
# pad's own centreline; there is no room either side. The A* router will find
# that lane if it is empty, but it routes one net at a time and never rips up,
# so whichever net reaches the part first (in practice +3V3, which has pads on
# three sides of the ADE7953) rings it and strands every remaining pin. In
# attempt 2 that cost all eight of U7's signal nets at once.
#
# The fix is the one the USB-C receptacle already uses by hand: pre-seed a
# straight escape off every pad before any net is routed, and hand the router
# the far end as the terminal instead of the pad. Each stub sits exactly on its
# pad's centreline, ends on a grid node, and claims its lane up front, so the
# order nets happen to be routed in stops mattering.
FANOUT = {"U7": 1.75, "U3": 1.5, "U5": 1.5}
SIG_W = 0.25          # default signal track width; see ROUTE_ORDER
FANOUT_WIDTH = SIG_W

# ---------------------------------------------------------------------------
# Inner planes (rev B is 4-layer; spec 6.1)
# ---------------------------------------------------------------------------
# net -> the inner copper layer it is poured on. These nets are never routed
# as tracks: every pad instead drops a via straight down to its plane, which
# is what frees F.Cu and B.Cu for signals. GND was already poured (on both
# signal layers) in rev A; +3V3 joins it because it is the one rail with pads
# scattered over the whole board - 36 of them, on every IC, header and
# strapping network - and so the one rail that competed with signals
# everywhere at once.
#
# In2 carries +3V3 ALONE rather than being split with +5V. A split needs the
# two nets' consumers to fall in separable regions, and +5V's do not: its 12
# pads run from the regulator at the top-left corner to the LCD header at the
# bottom edge, the buzzer in the middle of the switching block and the LED
# supply diode at the right edge - a partition following them would leave
# +3V3, the net that actually needs the plane, in slivers. +5V has few enough
# terminals to route comfortably as 0.6 mm track, so it does.
PLANE_LAYER = {"GND": "In1.Cu", "+3V3": "In2.Cu"}
PLANE_NETS = tuple(PLANE_LAYER)
PLANE_STUB_W = SIG_W


def plane_vias(r, pad_pos, seed_list=(), max_r=6.0):
    """Drop a via from every SMD pad of a plane net down to its plane.

    Through-hole pads already cross every layer, so they reach the plane by
    existing. An SMD pad does not, and with no pour on the signal layers there
    is nothing for it to touch: it needs a via and a stub to it.

    Placed BEFORE any signal is routed. These vias are not optional - a missing
    one is an unconnected pad - so they claim their space while the board is
    empty and the signal router threads what is left. That makes their number
    and position matter: on the ADE7953, one via per ground pin put five holes
    into the same 0.5 mm-pitch escape annulus that eight signals also have to
    leave through, and cost more nets than the plane saved. So pads already
    tied to each other in copper are treated as ONE group and share a single
    via - which for a QFN's five ground pins, all stubbed onto the exposed pad,
    means one hole instead of five.

    A group's members are physical PADS, not pin numbers. Several footprints
    here give one pin number to two separate pieces of copper - both halves of
    a tactile switch's ground side, the SOT-223's tab and its pin 2 - and they
    are only the same net, not the same copper: each needs its own via.
    """
    pads, groups = _plane_groups(r, pad_pos, seed_list)
    out, fails = [], []
    load = {ref: _side_load(ref, pad_pos) for ref in FANOUT}
    # Smallest groups first: a group of one has exactly one escape ray to try,
    # while the QFN's six-pin ground group can take any of six. Letting the
    # many-choice group pick first strands the single-choice one.
    for key in sorted(groups, key=lambda g: (len(groups[g]), sorted(groups[g])[0])):
        members = sorted(groups[key])
        net = pads[members[0]][4]
        # Where a group spans several sides of a fine-pitch part, take the via
        # off the side carrying the fewest signals. The ADE7953's five ground
        # pins are one group; putting their single via on the south row - the
        # busiest, four signals - plugged the corridor those four escape by and
        # cost three nets. Plain pin order picks that row; side load does not.
        members.sort(key=lambda m: ((load[m[0]].get(_pad_side(m[0], pads[m]), 0), m)
                                    if m[0] in load else (0, m)))
        # Every via changes what the next one may do, so the blocked/via_ok
        # memo has to be dropped between groups rather than only between nets.
        r._memo, r._memo_net = {}, net
        spot = None
        for m in members:
            (x, y, layers, area, _net) = pads[m]
            if len(layers) == 2:
                spot = "tht"              # reaches the plane by existing
                break
            cand = _via_spot_for_pad(r, net, m[0], x, y, max_r)
            if cand is not None:
                spot = (layers[0], x, y, cand[0], cand[1])
                break
        if spot is None:
            fails.append("%s (%s)"
                         % ("/".join("%s.%s" % (m[0], m[1]) for m in members), net))
            continue
        if spot == "tht":
            continue
        layer, x, y, cx, cy = spot
        r.add_via(net, cx, cy, fixed=True)
        if abs(cx - x) > 1e-6 or abs(cy - y) > 1e-6:
            r.add_seg(net, layer, x, y, cx, cy, PLANE_STUB_W, fixed=True)
        out.append((net, cx, cy))
    for f in fails:
        print("  !! no plane via spot for %s" % f)
    return out, fails


def _plane_groups(r, pad_pos, seed_list):
    """({(ref, pin, idx): (x, y, layers, area, net)}, {key: {member, ...}})

    Groups are plane-net pads already joined in copper. Two sources of
    joining, both created before this runs: the inward stubs all_seeds() draws
    from a fine-pitch part's ground pins onto its exposed pad, and the links
    added here between same-net pads adjacent on the same side of such a part
    (the ADE7953's +3V3 pins 7 and 8), which sit 0.5 mm apart and could not
    both take a via anyway.
    """
    pads = {}
    for (ref, pin), plist in pad_pos.items():
        net = COMPONENTS[ref]["pins"].get(pin)
        if net not in PLANE_LAYER:
            continue
        for idx, (x, y, layers, area) in enumerate(plist):
            pads[(ref, pin, idx)] = (x, y, layers, area, net)
    parent = {k: k for k in pads}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    # 1. a seed segment running from one pad's centre into another pad
    for (net, layer, pts, w) in seed_list:
        if net not in PLANE_LAYER:
            continue
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            hits = []
            for key in sorted(pads):
                (px, py, layers, area, pnet) = pads[key]
                if pnet != net:
                    continue
                hw = math.sqrt(area) / 2.0
                for (qx, qy) in ((ax, ay), (bx, by)):
                    if abs(qx - px) <= hw + 1e-6 and abs(qy - py) <= hw + 1e-6:
                        hits.append(key)
            for k in hits[1:]:
                union(hits[0], k)

    # 2. same-net neighbours on a fine-pitch part, linked pad centre to pad
    #    centre. The link stays inside the pads' own row, so its clearance to
    #    the pins either side is the pads' own.
    for ref in sorted(FANOUT):
        mine = sorted(k for k in pads if k[0] == ref)
        for i in range(len(mine)):
            for j in range(i + 1, len(mine)):
                (ax, ay, al, _aa, anet) = pads[mine[i]]
                (bx, by, _bl, _ba, bnet) = pads[mine[j]]
                if anet != bnet or math.hypot(bx - ax, by - ay) > 0.8:
                    continue
                r.add_seg(anet, al[0], ax, ay, bx, by, PLANE_STUB_W,
                          fixed=True)
                union(mine[i], mine[j])

    groups = {}
    for k in pads:
        groups.setdefault(find(k), set()).add(k)
    return pads, groups


def _pad_side(ref, pad):
    """0=west 1=east 2=north 3=south, by the pad's offset from the body."""
    cx, cy = COMPONENTS[ref]["at"][0], COMPONENTS[ref]["at"][1]
    dx, dy = pad[0] - cx, pad[1] - cy
    if abs(dx) >= abs(dy):
        return 0 if dx < 0 else 1
    return 2 if dy < 0 else 3


def _side_load(ref, pad_pos):
    """{side: number of routed signals leaving by it} for one part."""
    load = {}
    for (r_, pin), plist in pad_pos.items():
        if r_ != ref:
            continue
        net = COMPONENTS[ref]["pins"].get(pin)
        if not net or net in PLANE_LAYER:
            continue
        for p in plist:
            load[_pad_side(ref, p)] = load.get(_pad_side(ref, p), 0) + 1
    return load


def _via_spot_for_pad(r, net, ref, x, y, max_r):
    """Where this pad's plane via may go.

    On a fine-pitch part the pin's own centreline is tried first, because a
    via anywhere else in that annulus plugs a lane some signal has to escape
    by; the free search is the fallback for a pin whose ray is walled off by
    the neighbouring part (both MAX31856s sit in a row of filter passives).
    """
    if ref in FANOUT:
        spot = _fanout_via_spot(r, net, ref, x, y, max_r)
        if spot is not None:
            return spot
    return _nearest_via_spot(r, net, x, y, max_r)


def _fanout_via_spot(r, net, ref, x, y, max_r):
    """On a fine-pitch part the via must sit on the pin's OWN centreline and
    beyond every neighbouring escape stub.

    Anywhere else is either inside the 0.5 mm pitch, where a 0.6 mm via cannot
    clear the pins either side, or in the ring where the signal stubs end,
    where it plugs the lane those signals leave by. FANOUT[ref] + 1.25 mm is
    the first radius at which a via clears a neighbour's stub end (which sits
    0.5 mm to the side at FANOUT[ref] + 0.75).
    """
    cx, cy = COMPONENTS[ref]["at"][0], COMPONENTS[ref]["at"][1]
    dx, dy = x - cx, y - cy
    horiz = abs(dx) >= abs(dy)
    reach = FANOUT[ref] + 1.25
    while reach <= max_r:
        if horiz:
            ex, ey = _snap(x + math.copysign(reach, dx), BX0), _snap(y, BY0)
        else:
            ex, ey = _snap(x, BX0), _snap(y + math.copysign(reach, dy), BY0)
        i, j = r.snap(ex, ey)
        if 0 <= i < r.nx and 0 <= j < r.ny and r.via_ok(net, i, j) and \
           r.hop_clear(net, PLANE_STUB_W, i, j, x, y, 0):
            return (round(r.cell_xy(i, j)[0], 4), round(r.cell_xy(i, j)[1], 4))
        reach += R.GRID
    return None


def _nearest_via_spot(r, net, x, y, max_r):
    """Closest grid node that takes a via and a clear straight stub from
    (x, y). Ties break on (distance, x, y) so the choice is deterministic."""
    i0, j0 = r.snap(x, y)
    span = int(math.ceil(max_r / R.GRID))
    cands = []
    for di in range(-span, span + 1):
        for dj in range(-span, span + 1):
            i, j = i0 + di, j0 + dj
            if not (0 <= i < r.nx and 0 <= j < r.ny):
                continue
            cx, cy = r.cell_xy(i, j)
            d = math.hypot(cx - x, cy - y)
            if d > max_r:
                continue
            cands.append((round(d, 6), round(cx, 4), round(cy, 4), i, j))
    for (_d, cx, cy, i, j) in sorted(cands):
        if not r.via_ok(net, i, j):
            continue
        if not r.hop_clear(net, PLANE_STUB_W, i, j, x, y, 0):
            continue
        return (cx, cy)
    return None


def _snap(v, origin):
    return origin + round((v - origin) / R.GRID) * R.GRID


def all_seeds(pad_pos):
    """(seed polylines, {net: [stub terminal, ...]}) for every hand escape.

    Combines the USB-C escapes above with a generated radial fanout for each
    FANOUT component. GND gets seeds but never a terminal - it is poured, not
    routed - and on a part with an exposed pad every GND pin additionally gets
    a short inward stub tying it to that pad, because the pour cannot reach
    between 0.5 mm-pitch pins.
    """
    seeds = list(USB_SEEDS)
    terms = {k: list(v) for k, v in USB_STUB_TERMS.items()}
    for ref, out in sorted(FANOUT.items()):
        comp = COMPONENTS[ref]
        cx, cy = comp["at"][0], comp["at"][1]
        pads = [(pin, p) for (r_, pin), pl in pad_pos.items() if r_ == ref
                for p in pl]
        ep = max((p for _pin, p in pads), key=lambda p: p[3])
        ep_big = ep[3] > 4.0
        # Group the pads by the side they leave from, then stagger along each
        # side in SPATIAL order. Keyed on pin number the alternation scrambles
        # and adjacent stubs end up the same length again.
        sides = {}
        for pin, (px, py, layers, area) in pads:
            net = comp["pins"].get(pin)
            if not net or (ep_big and area == ep[3]):
                continue
            dx, dy = px - cx, py - cy
            if abs(dx) >= abs(dy):
                side, lat, horiz = (0 if dx < 0 else 1), py, True
            else:
                side, lat, horiz = (2 if dy < 0 else 3), px, False
            sides.setdefault(side, []).append((lat, pin, px, py, dx, dy, horiz))
        for side in sorted(sides):
            for k, (lat, pin, px, py, dx, dy, horiz) in \
                    enumerate(sorted(sides[side])):
                net = comp["pins"][pin]
                if net in PLANE_NETS:
                    # A plane net leaves by via, not along the board. Giving it
                    # a fixed-length outward stub would either fall short of
                    # the via or overshoot it and leave a dangling tail;
                    # plane_vias() runs the same centreline lane out to
                    # exactly where a via fits. What a ground pin does still
                    # need on a part with an exposed pad is the inward stub
                    # onto that pad - nothing else can reach between 0.5 mm
                    # pins - and it stays on the pin's own centreline until it
                    # is inside the pad, so it never encroaches on a neighbour.
                    if net == "GND" and ep_big:
                        end = (ep[0], py) if horiz else (px, ep[1])
                        seeds.append((net, 0, [(px, py), end], FANOUT_WIDTH))
                    continue
                reach = out + 0.75 * (k % 2)
                if horiz:
                    ex = _snap(px + math.copysign(reach, dx), BX0)
                    ey = _snap(py, BY0)
                else:
                    ex = _snap(px, BX0)
                    ey = _snap(py + math.copysign(reach, dy), BY0)
                seeds.append((net, 0, [(px, py), (ex, ey)], FANOUT_WIDTH))
                terms.setdefault(net, []).append((ex, ey, (0,)))
    return seeds, terms


# Every net except GND, which is poured. Order is the router's only conflict
# resolution: it is greedy and never rips up, so the widest and least
# reroutable copper goes first and the many short two-pin locals go last,
# threading whatever is left.
ROUTE_ORDER = [
    # rails. GND and +3V3 are absent because they are planes (PLANE_LAYER):
    # every pad of theirs reaches its layer by via, so they cost the signal
    # layers nothing but the via.
    #
    # Signals are SIG_W. Nets that terminate only on coarse footprints could
    # be wider, but nothing on this board does uniformly enough to be worth a
    # second class: the SPI and I2C buses, every strap and every module escape
    # all end on either a 0.65 mm-pitch TSSOP-14 (MAX31856 pins 5/8/9-12) or a
    # 0.5 mm-pitch QFN-28 (ADE7953), and a track can only leave pads that fine
    # along the pad's own centreline.
    ("VIN", 0.8), ("+5V", 0.6), ("VLED", 0.5), ("VBUS", 0.4),
    ("AUX_VP", 0.6),
    # The multi-drop buses: longest reach, most terminals, hardest to thread.
    # The two thermocouple chip selects ride the same channel between U3 and U5
    # and are routed with them rather than with the other escapes, or the bus
    # takes the channel first and leaves them nothing.
    ("SPI_MOSI", SIG_W), ("SPI_SCLK", SIG_W), ("SPI_MISO", SIG_W),
    ("TC1_CS", SIG_W), ("TC2_CS", SIG_W),
    ("I2C_SDA", SIG_W), ("I2C_SCL", SIG_W),
    # isolated side of the opto barrier - only nets allowed in the keepout
    ("SSR1_A", 0.4), ("SSR1_B", 0.4), ("SSR2_A", 0.4), ("SSR2_B", 0.4),
    # aux bank outputs carry relay/solenoid coil current
    # AUX*_OUT run outermost-first: U6's output pins and J10's terminal
    # positions are in opposite order, so AUX1 and AUX3 have to swap sides.
    # Routing the one with the longest reach first lets it take the outside.
    ("AUX3_OUT", 0.5), ("AUX2_OUT", 0.5), ("AUX1_OUT", 0.5),
    ("BUZZ_K", 0.5),
    # straps and indicators
    ("EN", SIG_W), ("IO0", SIG_W), ("LEDP_K", SIG_W),
    # Module escapes. Within each pad row the net whose pin sits CLOSEST to the
    # side of the module it leaves by goes first: the first-routed net hugs the
    # pad row and every later one takes the next lane out, so ordering the
    # other way round makes the near pins climb over the far ones' copper.
    # bottom row, west -> east (all of these leave southward)
    ("LCD_BL", SIG_W), ("LCD_RST", SIG_W), ("LCD_DC", SIG_W),
    ("AUX1", SIG_W), ("SSR2_CTRL", SIG_W), ("LED_DATA", SIG_W),
    # left column, south (nearest the southern exit) -> north
    ("LCD_CS", SIG_W), ("SSR1_CTRL", SIG_W), ("AUX3", SIG_W), ("AUX2", SIG_W),
    ("ALARM", SIG_W), ("T_IRQ", SIG_W), ("T_CS", SIG_W), ("IN1", SIG_W),
    # right column, south -> north
    ("WDT_KICK", SIG_W), ("BTN_UP", SIG_W), ("BTN_DOWN", SIG_W),
    ("BTN_LEFT", SIG_W), ("BTN_RIGHT", SIG_W), ("BTN_SEL", SIG_W),
    ("RXD0", SIG_W), ("TXD0", SIG_W), ("IN2", SIG_W), ("IN3", SIG_W),
    # USB (pre-seeded escapes, see USB_SEEDS)
    ("CC1", SIG_W), ("CC2", SIG_W), ("USB_DN", SIG_W), ("USB_DP", SIG_W),
    # SSR driver chains, watchdog gate
    ("SSR_EN", 0.4),
    ("SSR1_LED_A", SIG_W), ("SSR1_IND_A", SIG_W), ("SSR1_IND_K", SIG_W),
    ("SSR2_LED_A", SIG_W), ("SSR2_IND_A", SIG_W), ("SSR2_IND_K", SIG_W),
    ("WDT_PUMP", SIG_W), ("WDT_HOLD", SIG_W),
    # buzzer, status LED
    ("BUZZ_GATE", SIG_W), ("WS_DIN", SIG_W),
    # thermocouple front-ends (short, local, kept matched)
    ("TC1_P", SIG_W), ("TC1_N", SIG_W), ("TC1_P_F", SIG_W), ("TC1_N_F", SIG_W),
    ("TC2_P", SIG_W), ("TC2_N", SIG_W), ("TC2_P_F", SIG_W), ("TC2_N_F", SIG_W),
    # CT front-end and its terminal
    ("CTA_P", 0.4), ("CTA_N", 0.4), ("CTA_F", SIG_W),
    ("CTB_P", 0.4), ("CTB_N", 0.4), ("CTB_F", SIG_W),
    # ADE7953 locals
    ("ADE_CLKIN", SIG_W), ("ADE_CLKOUT", SIG_W), ("ADE_REF", SIG_W),
    ("ADE_VINTA", SIG_W), ("ADE_VINTD", SIG_W), ("ADE_RESET", SIG_W),
    ("ADE_SCLK", SIG_W), ("ADE_CS", SIG_W), ("ADE_VP", SIG_W), ("ADE_VN", SIG_W),
    # protected inputs
    ("IN1_RAW", SIG_W), ("IN2_RAW", SIG_W), ("IN3_RAW", SIG_W),
    # touch series damping (header side of R39-R43)
    ("T_CLK_R", SIG_W), ("T_CS_R", SIG_W), ("T_DIN_R", SIG_W), ("T_DO_R", SIG_W),
    ("T_IRQ_R", SIG_W),
]


def net_terminals(net, pad_pos, stub_terms):
    """(terminals, extra source points) for one net, in routing order."""
    pins = netlist()[net]
    terms = []
    for (ref, pin) in pins:
        # a pad that already has a hand-drawn escape is represented by the
        # far end of that escape, never by the pad itself
        if (ref == "J1" or ref in FANOUT) and net in stub_terms:
            continue
        for (gx, gy, layers, area) in pad_pos[(ref, pin)]:
            terms.append((gx, gy, layers, area, 0 if ref == "U1" else 1))
    # dedupe identical positions, then order the tree's growth: the module
    # first, then largest pad first (THT seeds). U1 has to be the seed of
    # any net it is on - its pad rows are the one place on this board with
    # no slack, so its escape lane must be claimed while the lane is still
    # empty. Ordering purely by pad area put the 1.7 mm header pins of
    # J5/J6/J7 ahead of the module's 0.9 mm ones and left every bottom-row
    # escape to be attempted last, from the far side of the board.
    seen = {}
    for t in terms:
        seen.setdefault((round(t[0], 3), round(t[1], 3)), t)
    terms = sorted(seen.values(), key=lambda t: (t[4], -t[3]))
    terms = [(t[0], t[1], t[2]) for t in terms]
    # USB stub ends must lead (they are the only way into J1, and the seed
    # attachment below keys off terms[0]); fanout stub ends are ordinary
    # goals and go last.
    usb = USB_STUB_TERMS.get(net, [])
    fan = [t for t in stub_terms.get(net, []) if t not in usb]
    terms = usb + terms + fan
    seeds = [(slayer, pts) for (snet, slayer, pts, w) in USB_SEEDS
             if snet == net]
    if seeds:
        # first terminal = the one touching a seed, so the seed copper is
        # genuinely part of the source component
        def seed_d(t):
            return min(math.hypot(t[0] - px, t[1] - py)
                       for (_l, pts) in seeds for (px, py) in pts)
        terms.sort(key=seed_d)
        # only seeds transitively attached to terms[0] become sources;
        # detached seed polylines keep their far end as a goal terminal
        attached, todo = [], list(seeds)
        anchor = [(terms[0][0], terms[0][1])]
        changed = True
        while changed:
            changed = False
            for sd in list(todo):
                if any(math.hypot(px - ax, py - ay) < 0.31
                       for (px, py) in sd[1] for (ax, ay) in anchor):
                    attached.append(sd)
                    todo.remove(sd)
                    anchor.extend(sd[1])
                    changed = True
    else:
        attached = []
    extra = []
    for (slayer, pts) in attached:
        for a, b in zip(pts, pts[1:]):
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            n = max(1, int(d / 0.4))
            for k in range(n + 1):
                t = k / float(n)
                extra.append((a[0] + (b[0] - a[0]) * t,
                              a[1] + (b[1] - a[1]) * t, slayer))
    return terms, extra


def route_one(r, net, width, pad_pos, stub_terms):
    """Route one net. True if every terminal was reached."""
    terms, extra = net_terminals(net, pad_pos, stub_terms)
    try:
        r.route(net, terms, width, extra_srcs=extra)
        return True
    except RuntimeError as e:
        print("  !! %s" % e)
        return False


def ripup_retry(r, failed, pad_pos, stub_terms, max_blockers=20,
                radius=8.0):
    """Rip up one blocking net at a time and retry a net that would not route.

    router.py is greedy and never backtracks, so a failed net failed because
    something routed earlier took the one lane out of its pocket. Order alone
    cannot always fix that - promoting the victim just makes a different net
    the victim - so this does the real thing: delete a neighbouring net's
    copper, route the victim into the space, then put the neighbour back by a
    different path. If the neighbour then cannot be re-routed the whole
    attempt is rolled back and the next candidate is tried, so the board never
    ends up worse than it started.

    Candidates are the nets with removable copper nearest the terminal that
    failed, which is where the blockage is by definition. Hand-seeded escapes,
    fanout stubs and plane-via stubs are marked `fixed` and are never removed:
    the router cannot re-create them.
    """
    width = dict(ROUTE_ORDER)
    still = []
    for net in failed:
        if net not in width:
            still.append(net)
            continue
        fail_at = r.fail_pos.get(net)
        if fail_at is None:
            still.append(net)
            continue
        base = r.snapshot()
        fixed_it = False
        for blocker in r.nets_near(fail_at[0], fail_at[1], radius)[:max_blockers]:
            if blocker == net or blocker not in width:
                continue
            r.restore(base)
            r.rip_up(blocker)
            r.rip_up(net)
            if not route_one(r, net, width[net], pad_pos, stub_terms):
                continue
            if route_one(r, blocker, width[blocker], pad_pos, stub_terms):
                print("  rip-up: routed %s by re-routing %s" % (net, blocker))
                fixed_it = True
                break
        if not fixed_it:
            r.restore(base)
            still.append(net)
    return still


def route_all(r, pad_pos, seed_list=None, stub_terms=None, order=None,
              verbose=True):
    """Route every non-plane net. Returns the list of nets that did not
    finish, in order, so the caller can retry with them promoted."""
    if seed_list is None or stub_terms is None:
        seed_list, stub_terms = all_seeds(pad_pos)
    nl = netlist()
    routed = set()
    failed = []
    for net, width in (order or ROUTE_ORDER):
        if not route_one(r, net, width, pad_pos, stub_terms):
            failed.append(net)
        routed.add(net)
        if verbose:
            print("  routed %-10s %d segs total" % (net, len(r.result_tracks)))
    missing = set(nl) - routed - set(PLANE_NETS)
    assert not missing, "unrouted nets: %s" % missing
    return failed


def promoted_order(promoted):
    """ROUTE_ORDER with `promoted` moved to the front.

    Order is the router's only conflict resolution - it is greedy and never
    rips up - so a net that failed did so because something routed earlier
    took the one lane out of its pocket. Routing it first is the cheapest
    form of rip-up there is: the blocking net is re-routed around it on the
    next pass, and being longer it has somewhere else to go. The caller
    iterates until the failure set stops shrinking (see kicad_build.main).
    """
    width = dict(ROUTE_ORDER)
    head = [(n, width[n]) for n in promoted if n in width]
    return head + [(n, w) for (n, w) in ROUTE_ORDER if n not in set(promoted)]


# ---------------------------------------------------------------------------
# emit board file
# ---------------------------------------------------------------------------

def transform_fp(comp, ref, netnum):
    fp = [x for x in load_fp(comp["fpf"])]
    fx, fy, frot = comp["at"]
    out = [Sym("footprint"), comp["fp"]]
    out.append([Sym("layer"), "F.Cu"])
    out.append([Sym("uuid"), uid("fp", ref)])
    out.append([Sym("at"), fx, fy] + ([frot] if frot else []))
    for x in fp[2:]:
        if not isinstance(x, list):
            continue
        head = str(x[0])
        if head in ("version", "generator", "generator_version", "layer"):
            continue
        if head == "property":
            x = [e for e in x]
            key = x[1]
            if key == "Reference":
                x[2] = ref
            elif key == "Value":
                x[2] = comp["value"]
            out.append(_rot_at(x, frot) if frot else x)
            continue
        if head == "pad":
            x = [e for e in x]
            name = x[1]
            net = None
            if str(x[2]) != "np_thru_hole" and name != "":
                net = comp["pins"].get(str(name))
            x2 = _rot_at(x, frot) if frot else x
            if net:
                # insert net before uuid if present, else append
                x2 = [e for e in x2]
                x2.append([Sym("net"), netnum[net], net])
            out.append(x2)
            continue
        if head == "fp_text" and frot:
            out.append(_rot_at(x, frot))
            continue
        out.append(x)
    out.append([Sym("path"), "/%s" % sch_sym_uuid(ref)])
    out.append([Sym("sheetfile"), "bisque-controller.kicad_sch"])
    return out


def _n(v):
    iv = round(v, 4)
    return int(iv) if abs(iv - int(iv)) < 1e-9 else iv


def _rot_at(node, frot):
    """Copy node, adding frot to its (at ...) angle (KiCad stores summed angles)."""
    out = []
    for e in node:
        if isinstance(e, list) and e and str(e[0]) == "at":
            lx, ly = num(e[1]), num(e[2])
            a = num(e[3]) if len(e) > 3 else 0.0
            na = (a + frot) % 360
            ne = [Sym("at"), _n(lx), _n(ly)]
            if na:
                ne.append(_n(na))
            out.append(ne)
        elif isinstance(e, list):
            out.append(_rot_at(e, frot))
        else:
            out.append(e)
    return out


# Free-standing silk. The large clear band between the switching region
# (x <= 60) and the analog region (x >= 86) is where the title goes; every
# other label sits beside the connector or control it names.
SILK = [
    ("BISQUE KILN CONTROLLER", 62.5, 62.0, 0, 1.4),
    ("REV B", 62.5, 65.5, 0, 1.1),
    ("U.FL ANT ->", 62.0, 22.3, 0, 0.9),
    ("USB", 40.5, 22.0, 0, 0.9),
    ("RESET", 36.5, 20.9, 0, 0.9),
    ("BOOT", 100.0, 20.9, 0, 0.9),
    ("5V IN", 22.0, 34.0, 0, 0.9),
    ("+", 30.0, 39.6, 0, 1.1), ("-", 30.0, 44.7, 0, 1.3),
    ("AUX OUT", 22.0, 47.0, 0, 0.9),
    ("SSR1", 22.0, 70.5, 0, 0.9),
    ("SSR2", 22.0, 83.0, 0, 0.9),
    ("TC1  K+/K-", 104.0, 31.0, 0, 0.9),
    ("TC2  K+/K-", 104.0, 58.5, 0, 0.9),
    ("CT A+/A-/B+/B-", 96.0, 76.0, 0, 0.9),
    ("AC SENSE - DNP", 100.0, 76.0, 0, 0.8),
    ("STATUS", 84.0, 93.6, 0, 0.9),
    ("I2C", 66.0, 93.6, 0, 0.9),
    ("INPUTS  1 / 2 / 3 / GND", 62.6, 108.8, 0, 0.9),
    ("AUX_VP=5V", 34.0, 66.0, 0, 0.9),
    ("WDT DEFEAT - REMOVE", 50.0, 61.5, 0, 0.9),
]
J5_PINS = ["5V", "GND", "CS", "RST", "DC", "SDI", "SCK", "BL",
           "SDO", "TCK", "TCS", "TDI", "TDO", "IRQ"]
J6_PINS = ["UP", "DN", "LT", "RT", "OK", "G"]
J7_PINS = ["3V3", "GND", "TX", "RX", "SDA", "SCL", "3V3", "GND"]
# Pin names go immediately north of each header's body (headers sit at y=104,
# courtyard 100.6..107.4), reading upright with pin 1 at the header's origin.
for hdr, names in (("J5", J5_PINS), ("J6", J6_PINS), ("J7", J7_PINS)):
    hx, hy, _rot = COMPONENTS[hdr]["at"]
    for k, t in enumerate(names):
        SILK.append((t, hx + 2.54 * k, hy - 4.3, 0, 0.8))


def main(dst):
    r, pad_pos = build_router()
    seed_list, stub_terms = all_seeds(pad_pos)
    for (net, layer, pts, w) in seed_list:
        for a, b in zip(pts, pts[1:]):
            r.add_seg(net, layer, a[0], a[1], b[0], b[1], w, fixed=True)
    for (net, x, y) in MANUAL_VIAS:
        r.add_via(net, x, y, fixed=True)
    print("routing...")
    route_all(r, pad_pos, seed_list, stub_terms)
    r._memo = {}
    r._memo_net = None
    print("mitred %d right-angle corners" % r.miter_corners())

    nets = sorted(netlist())
    netnum = {n: i + 1 for i, n in enumerate(nets)}

    out = []
    ap = out.append
    ap('(kicad_pcb (version 20241229) (generator "pcbnew") (generator_version "9.0")')
    ap('\t(general (thickness 1.6) (legacy_teardrops no))')
    ap('\t(paper "A3")')
    ap('\t(layers')
    for lid, lname, ltype, ualias in [
            (0, "F.Cu", "signal", None), (4, "In1.Cu", "signal", None),
            (6, "In2.Cu", "signal", None), (2, "B.Cu", "signal", None),
            (9, "F.Adhes", "user", "F.Adhesive"), (11, "B.Adhes", "user", "B.Adhesive"),
            (13, "F.Paste", "user", None), (15, "B.Paste", "user", None),
            (5, "F.SilkS", "user", "F.Silkscreen"), (7, "B.SilkS", "user", "B.Silkscreen"),
            (1, "F.Mask", "user", None), (3, "B.Mask", "user", None),
            (17, "Dwgs.User", "user", "User.Drawings"), (19, "Cmts.User", "user", "User.Comments"),
            (21, "Eco1.User", "user", "User.Eco1"), (23, "Eco2.User", "user", "User.Eco2"),
            (25, "Edge.Cuts", "user", None), (27, "Margin", "user", None),
            (31, "F.CrtYd", "user", "F.Courtyard"), (29, "B.CrtYd", "user", "B.Courtyard"),
            (35, "F.Fab", "user", "F.Fabrication"), (33, "B.Fab", "user", "B.Fabrication")]:
        if ualias:
            ap('\t\t(%d "%s" %s "%s")' % (lid, lname, ltype, ualias))
        else:
            ap('\t\t(%d "%s" %s)' % (lid, lname, ltype))
    ap('\t)')
    ap('\t(setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no)')
    ap('\t\t(pcbplotparams (layerselection 0x00000000_00000000_55555555_5755f5ff) (plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000) (disableapertmacros no) (usegerberextensions no) (usegerberattributes yes) (usegerberadvancedattributes yes) (creategerberjobfile yes) (dashed_line_dash_ratio 12.000000) (dashed_line_gap_ratio 3.000000) (svgprecision 4) (plotframeref no) (mode 1) (useauxorigin no) (hpglpennumber 1) (hpglpenspeed 20) (hpglpendiameter 15.000000) (pdf_front_fp_property_popups yes) (pdf_back_fp_property_popups yes) (pdf_metadata yes) (pdf_single_document no) (dxfpolygonmode yes) (dxfimperialunits yes) (dxfusepcbnewfont yes) (plotinvisibletext no) (sketchpadsonfab no) (plot_black_and_white no) (subtractmaskfromsilk no) (outputformat 1) (mirror no) (drillshape 1) (scaleselection 1) (outputdirectory ""))')
    ap('\t)')
    ap('\t(net 0 "")')
    for n in nets:
        ap('\t(net %d "%s")' % (netnum[n], n))
    # footprints
    for ref, comp in COMPONENTS.items():
        node = transform_fp(comp, ref, netnum)
        ap('\t' + dump(node, 1))
    # edge cuts
    corners = [(BX0, BY0), (BX1, BY0), (BX1, BY1), (BX0, BY1)]
    for k in range(4):
        a, b = corners[k], corners[(k + 1) % 4]
        ap('\t(gr_line (start %s %s) (end %s %s) (stroke (width 0.1) (type default)) (layer "Edge.Cuts") (uuid "%s"))'
           % (f(a[0]), f(a[1]), f(b[0]), f(b[1]), uid("edge", k)))
    # silk
    for k, (txt, x, y, rot, size) in enumerate(SILK):
        ap('\t(gr_text "%s" (at %s %s %s) (layer "F.SilkS") (uuid "%s")\n'
           '\t\t(effects (font (size %s %s) (thickness %s)))\n\t)'
           % (txt.replace('"', ''), f(x), f(y), f(rot), uid("silk", k),
              f(size), f(size), f(max(0.1, size * 0.15))))
    # tracks
    for i, s in enumerate(r.result_tracks):
        lname = "F.Cu" if s.layer == 0 else "B.Cu"
        ap('\t(segment (start %s %s) (end %s %s) (width %s) (layer "%s") (net %d) (uuid "%s"))'
           % (f(s.x1), f(s.y1), f(s.x2), f(s.y2), f(s.w), lname,
              netnum[s.net], uid("seg", i)))
    for i, (net, x, y, _fixed) in enumerate(r.result_vias):
        ap('\t(via (at %s %s) (size %s) (drill %s) (layers "F.Cu" "B.Cu") (net %d) (uuid "%s"))'
           % (f(x), f(y), f(R.VIA_DIA), f(R.VIA_DRILL), netnum[net], uid("via", i)))
    # inner planes: GND on In1.Cu, +3V3 on In2.Cu (PLANE_LAYER)
    m = 0.5
    pts = [(BX0 + m, BY0 + m), (BX1 - m, BY0 + m), (BX1 - m, BY1 - m), (BX0 + m, BY1 - m)]
    poly = " ".join("(xy %s %s)" % (f(x), f(y)) for x, y in pts)
    for pnet, player in sorted(PLANE_LAYER.items()):
        ap('\t(zone (net %d) (net_name "%s") (layers "%s") (uuid "%s") (hatch edge 0.5)\n'
           '\t\t(connect_pads (clearance 0.3))\n'
           '\t\t(min_thickness 0.2) (filled_areas_thickness no)\n'
           '\t\t(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.4))\n'
           '\t\t(polygon (pts %s))\n\t)'
           % (netnum[pnet], pnet, player, uid("zone", pnet), poly))
    # opto-isolation barrier: a rule area barring the pour on EVERY copper
    # layer, inner planes included (see kicad_build.add_zones)
    bpoly = " ".join("(xy %s %s)" % (f(x), f(y)) for x, y in
                     [(ISO_BARRIER[0], ISO_BARRIER[1]), (ISO_BARRIER[2], ISO_BARRIER[1]),
                      (ISO_BARRIER[2], ISO_BARRIER[3]), (ISO_BARRIER[0], ISO_BARRIER[3])])
    ap('\t(zone (net 0) (net_name "") (layers "F.Cu" "In1.Cu" "In2.Cu" "B.Cu")\n'
       '\t\t(uuid "%s") (hatch edge 0.5) (keepout (tracks allowed) (vias allowed)\n'
       '\t\t(pads allowed) (copperpour not_allowed) (footprints allowed))\n'
       '\t\t(fill (thermal_gap 0.3) (thermal_bridge_width 0.4))\n'
       '\t\t(polygon (pts %s))\n\t)' % (uid("zone", "iso"), bpoly))
    ap(')')
    text = "\n".join(out) + "\n"
    with open(dst, "w") as fh:
        fh.write(text)
    print("wrote %s (%d bytes, %d tracks, %d vias)"
          % (dst, len(text), len(r.result_tracks), len(r.result_vias)))
    return r


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
