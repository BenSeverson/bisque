"""Generate bisque-controller.kicad_pcb (KiCad 9 format).

Embeds the official library footprints, assigns nets from design.py,
autoroutes signal/power nets with router.py, adds GND pours (unfilled —
press 'B' in pcbnew), stitching vias, edge cuts and silkscreen labels.
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


def build_router():
    r = R.Router(BX0, BY0, BX1, BY1)
    # No antenna keepout: rev B's WROOM-1U has no PCB antenna (spec 2.1).
    # Opto barrier, mirroring kicad_build.ISO_BARRIER / ISO_NETS.
    r.add_keepout(20.0, 71.0, 40.8, 95.5,
                  allow_nets=("SSR1_A", "SSR1_B", "SSR2_A", "SSR2_B"))
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
    ("USB_DN", 0, [(47.75, 28.445), (47.75, 30.0), (48.75, 30.0),
                   (48.75, 31.25)], 0.25),
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
FANOUT_WIDTH = 0.25


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
                reach = out + 0.75 * (k % 2)
                if horiz:
                    ex = _snap(px + math.copysign(reach, dx), BX0)
                    ey = _snap(py, BY0)
                else:
                    ex = _snap(px, BX0)
                    ey = _snap(py + math.copysign(reach, dy), BY0)
                seeds.append((net, 0, [(px, py), (ex, ey)], FANOUT_WIDTH))
                if net == "GND":
                    # Ground pins get the outward stub (so the pour can find
                    # them) and, on a part with an exposed pad, an inward stub
                    # onto it. The inward run stays on the pin's own centreline
                    # until it is inside the pad, so it never encroaches on a
                    # neighbour.
                    if ep_big:
                        end = (ep[0], py) if horiz else (px, ep[1])
                        seeds.append((net, 0, [(px, py), end], FANOUT_WIDTH))
                    continue
                terms.setdefault(net, []).append((ex, ey, (0,)))
    return seeds, terms


# Every net except GND, which is poured. Order is the router's only conflict
# resolution: it is greedy and never rips up, so the widest and least
# reroutable copper goes first and the many short two-pin locals go last,
# threading whatever is left.
ROUTE_ORDER = [
    # rails
    # +3V3 is 0.25 mm, not the 0.7 mm rev A could afford, and every signal
    # drops from 0.3 to 0.25 for the same reason: rev B's rail and its buses
    # both have to land on 0.65 mm-pitch TSSOP-14 pads (MAX31856 pins 5/8/9-12)
    # and 0.5 mm-pitch QFN-28 pads (ADE7953), and anything wider cannot sit on
    # those pads' centrelines without breaking clearance to the neighbouring
    # pin. 0.25 mm of 1 oz copper carries ~0.9 A at a 20 C rise - several times
    # the 3V3 rail's draw, whose largest single load is the module at ~0.5 A
    # peak, and which is decoupled locally at every IC.
    ("VIN", 0.8), ("+5V", 0.6), ("+3V3", 0.25), ("VLED", 0.5), ("VBUS", 0.4),
    ("AUX_VP", 0.6),
    # The multi-drop buses: longest reach, most terminals, hardest to thread.
    # The two thermocouple chip selects ride the same channel between U3 and U5
    # and are routed with them rather than with the other escapes, or the bus
    # takes the channel first and leaves them nothing.
    ("SPI_MOSI", 0.25), ("SPI_SCLK", 0.25), ("SPI_MISO", 0.25),
    ("TC1_CS", 0.25), ("TC2_CS", 0.25),
    ("I2C_SDA", 0.25), ("I2C_SCL", 0.25),
    # isolated side of the opto barrier - only nets allowed in the keepout
    ("SSR1_A", 0.4), ("SSR1_B", 0.4), ("SSR2_A", 0.4), ("SSR2_B", 0.4),
    # aux bank outputs carry relay/solenoid coil current
    # AUX*_OUT run outermost-first: U6's output pins and J10's terminal
    # positions are in opposite order, so AUX1 and AUX3 have to swap sides.
    # Routing the one with the longest reach first lets it take the outside.
    ("AUX3_OUT", 0.5), ("AUX2_OUT", 0.5), ("AUX1_OUT", 0.5),
    ("BUZZ_K", 0.5),
    # straps and indicators
    ("EN", 0.25), ("IO0", 0.25), ("LEDP_K", 0.25),
    # Module escapes. Within each pad row the net whose pin sits CLOSEST to the
    # side of the module it leaves by goes first: the first-routed net hugs the
    # pad row and every later one takes the next lane out, so ordering the
    # other way round makes the near pins climb over the far ones' copper.
    # bottom row, west -> east (all of these leave southward)
    ("LCD_BL", 0.25), ("LCD_RST", 0.25), ("LCD_DC", 0.25),
    ("AUX1", 0.25), ("SSR2_CTRL", 0.25), ("LED_DATA", 0.25),
    # left column, south (nearest the southern exit) -> north
    ("LCD_CS", 0.25), ("SSR1_CTRL", 0.25), ("AUX3", 0.25), ("AUX2", 0.25),
    ("ALARM", 0.25), ("T_IRQ", 0.25), ("T_CS", 0.25), ("IN1", 0.25),
    # right column, south -> north
    ("WDT_KICK", 0.25), ("BTN_UP", 0.25), ("BTN_DOWN", 0.25),
    ("BTN_LEFT", 0.25), ("BTN_RIGHT", 0.25), ("BTN_SEL", 0.25),
    ("RXD0", 0.25), ("TXD0", 0.25), ("IN2", 0.25), ("IN3", 0.25),
    # USB (pre-seeded escapes, see USB_SEEDS)
    ("CC1", 0.25), ("CC2", 0.25), ("USB_DN", 0.25), ("USB_DP", 0.25),
    # SSR driver chains, watchdog gate
    ("SSR_EN", 0.4),
    ("SSR1_LED_A", 0.25), ("SSR1_IND_A", 0.25), ("SSR1_IND_K", 0.25),
    ("SSR2_LED_A", 0.25), ("SSR2_IND_A", 0.25), ("SSR2_IND_K", 0.25),
    ("WDT_PUMP", 0.25), ("WDT_HOLD", 0.25),
    # buzzer, status LED
    ("BUZZ_GATE", 0.25), ("WS_DIN", 0.25),
    # thermocouple front-ends (short, local, kept matched)
    ("TC1_P", 0.25), ("TC1_N", 0.25), ("TC1_P_F", 0.25), ("TC1_N_F", 0.25),
    ("TC2_P", 0.25), ("TC2_N", 0.25), ("TC2_P_F", 0.25), ("TC2_N_F", 0.25),
    # CT front-end and its terminal
    ("CTA_P", 0.4), ("CTA_N", 0.4), ("CTA_F", 0.25),
    ("CTB_P", 0.4), ("CTB_N", 0.4), ("CTB_F", 0.25),
    # ADE7953 locals
    ("ADE_CLKIN", 0.25), ("ADE_CLKOUT", 0.25), ("ADE_REF", 0.25),
    ("ADE_VINTA", 0.25), ("ADE_VINTD", 0.25), ("ADE_RESET", 0.25),
    ("ADE_SCLK", 0.25), ("ADE_CS", 0.25), ("ADE_VP", 0.25), ("ADE_VN", 0.25),
    # protected inputs
    ("IN1_RAW", 0.25), ("IN2_RAW", 0.25), ("IN3_RAW", 0.25),
    # touch series damping (header side of R39-R43)
    ("T_CLK_R", 0.25), ("T_CS_R", 0.25), ("T_DIN_R", 0.25), ("T_DO_R", 0.25),
    ("T_IRQ_R", 0.25),
]


def route_all(r, pad_pos, seed_list=None, stub_terms=None):
    if seed_list is None or stub_terms is None:
        seed_list, stub_terms = all_seeds(pad_pos)
    nl = netlist()
    routed = set()
    for net, width in ROUTE_ORDER:
        pins = nl[net]
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
        try:
            r.route(net, terms, width, extra_srcs=extra)
        except RuntimeError as e:
            print("  !! %s" % e)
        routed.add(net)
        print("  routed %-10s %d terms, %d segs total" % (net, len(terms), len(r.result_tracks)))
    missing = set(nl) - routed - {"GND"}
    assert not missing, "unrouted nets: %s" % missing


def stitch_vias(r, count_target=40):
    r._begin("GND-stitch")
    out = []
    step = 6.0
    y = BY0 + 4
    while y < BY1 - 3:
        x = BX0 + 4
        while x < BX1 - 3:
            i, j = r.snap(x, y)
            if r.via_ok("GND", i, j):
                cx, cy = r.cell_xy(i, j)
                out.append((cx, cy))
                r.add_via("GND", cx, cy, record=False)
            x += step
        y += step
    return out


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
    ("TC1  K+/K-", 128.0, 33.0, 0, 0.9),
    ("TC2  K+/K-", 128.0, 45.0, 0, 0.9),
    ("CT A+/A-/B+/B-", 122.0, 72.0, 0, 0.9),
    ("AC SENSE - DNP", 104.0, 77.0, 0, 0.8),
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
            r.add_seg(net, layer, a[0], a[1], b[0], b[1], w)
    for (net, x, y) in MANUAL_VIAS:
        r.add_via(net, x, y)
    print("routing...")
    route_all(r, pad_pos, seed_list, stub_terms)
    r._memo = {}
    r._memo_net = None
    print("mitred %d right-angle corners" % r.miter_corners())
    stitches = stitch_vias(r)
    print("stitch vias: %d" % len(stitches))

    nets = sorted(netlist())
    netnum = {n: i + 1 for i, n in enumerate(nets)}

    out = []
    ap = out.append
    ap('(kicad_pcb (version 20241229) (generator "pcbnew") (generator_version "9.0")')
    ap('\t(general (thickness 1.6) (legacy_teardrops no))')
    ap('\t(paper "A3")')
    ap('\t(layers')
    for lid, lname, ltype, ualias in [
            (0, "F.Cu", "signal", None), (2, "B.Cu", "signal", None),
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
    for i, (net, x, y) in enumerate(r.result_vias):
        ap('\t(via (at %s %s) (size %s) (drill %s) (layers "F.Cu" "B.Cu") (net %d) (uuid "%s"))'
           % (f(x), f(y), f(R.VIA_DIA), f(R.VIA_DRILL), netnum[net], uid("via", i)))
    for i, (x, y) in enumerate(stitches):
        ap('\t(via (at %s %s) (size %s) (drill %s) (layers "F.Cu" "B.Cu") (net %d) (free yes) (uuid "%s"))'
           % (f(x), f(y), f(R.VIA_DIA), f(R.VIA_DRILL), netnum["GND"], uid("stitch", i)))
    # GND pours, one zone covering both layers
    gnum = netnum["GND"]
    m = 0.5
    pts = [(BX0 + m, BY0 + m), (BX1 - m, BY0 + m), (BX1 - m, BY1 - m), (BX0 + m, BY1 - m)]
    poly = " ".join("(xy %s %s)" % (f(x), f(y)) for x, y in pts)
    ap('\t(zone (net %d) (net_name "GND") (layers "F.Cu" "B.Cu") (uuid "%s") (hatch edge 0.5)\n'
       '\t\t(connect_pads (clearance 0.3))\n'
       '\t\t(min_thickness 0.2) (filled_areas_thickness no)\n'
       '\t\t(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.4))\n'
       '\t\t(polygon (pts %s))\n\t)' % (gnum, uid("zone", "gnd"), poly))
    ap(')')
    text = "\n".join(out) + "\n"
    with open(dst, "w") as fh:
        fh.write(text)
    print("wrote %s (%d bytes, %d tracks, %d vias)"
          % (dst, len(text), len(r.result_tracks), len(r.result_vias)))
    return r


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
