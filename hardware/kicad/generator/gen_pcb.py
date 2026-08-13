"""Generate bisque-controller.kicad_pcb (KiCad 9 format).

Embeds the official library footprints, assigns nets from design.py,
autoroutes signal/power nets with router.py, adds the inner GND/+3V3
planes (unfilled — press 'B' in pcbnew), edge cuts and silkscreen labels.
"""
import math
import os
import re
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
    """Yield (padname, kind, gx, gy, eff_w, eff_h, circle, layers, hole).

    `hole` is (diameter, length, angle_deg, hx, hy) and is (0, 0, 0, gx, gy)
    for an SMD pad. A slot drill — the USB-C shield's `(drill oval 0.6 1.7)`
    — is a capsule, not a circle, and hole-to-hole clearance is measured off
    that capsule (see router.Shape.hole_dist).
    """
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
        hole = (0.0, 0.0, 0.0, gx, gy)
        if kind in ("thru_hole", "np_thru_hole"):
            layers = (0, 1)
            dr = find(p, "drill")
            # a plated pad always has a hole; fall back to the min JLCPCB
            # drill rather than 0, which the router reads as "SMD pad"
            if dr and len(dr) > 1 and str(dr[1]) == "oval":
                dw, dh = num(dr[2]), num(dr[3])
            elif dr and len(dr) > 1:
                dw = dh = num(dr[1])
            else:
                dw = dh = 0.3
            # a drill offset moves the copper, not the hole: back it out so
            # the hole centre is the hole's, not the pad shape's
            hx, hy = lx, ly
            off = find(dr, "offset") if dr else None
            if off:
                ox, oy = rot_xy(num(off[1]), num(off[2]), pa)
                hx, hy = hx - ox, hy - oy
            hx, hy = rot_xy(hx, hy, frot)
            hx, hy = hx + fx, hy + fy
            hole = (min(dw, dh), max(dw, dh),
                    pa + frot + (0.0 if dw >= dh else 90.0), hx, hy)
        else:
            layers = (0,)
        yield (str(name), kind, gx, gy, w, h, circle, layers, hole)


# There is no opto-isolation barrier. Rev B carved a four-layer pour keepout
# (x 20..40.8, y 71..95.5) across the optocoupler row and made it a routing
# keepout too; the optos were reverted to rev A's direct low-side MOSFET
# drive (see design.py's SSR block), so the band is now ordinary pour and
# routing area on all four layers.


def build_router():
    r = R.Router(BX0, BY0, BX1, BY1)
    # No antenna keepout: rev B's WROOM-1U has no PCB antenna (spec 2.1).
    pad_pos = {}
    for ref, c in COMPONENTS.items():
        for (name, kind, gx, gy, w, h, circle, layers, hole) in pad_geometry(c):
            if kind == "np_thru_hole" or name == "":
                net = None
            else:
                net = c["pins"].get(name)
                if net is None:
                    net = "__nc_%s_%s" % (ref, name)
            r.add_pad(net, layers, gx, gy, w, h, circle,
                      drill=hole[0], drill_len=hole[1], drill_ang=hole[2],
                      hole=(hole[3], hole[4]))
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
SIG_W = 0.3           # default signal track width; see ROUTE_ORDER
FANOUT_WIDTH = 0.25   # fine-pitch escapes only; see the ROUTE_ORDER comment

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
PLANE_STUB_W = 0.25

# ---------------------------------------------------------------------------
# Physical stack-up
# ---------------------------------------------------------------------------
# JLCPCB's default 4-layer 1.6 mm process, JLC04161H-7628 — the stack-up this
# board is quoted and fabricated on, declared in the file rather than left
# out. Leaving it out is not a cosmetic omission: a .kicad_pcb with no
# (stackup ...) block carries no dielectric heights and no epsilon_r at all,
# so every impedance figure anyone derives from this file — KiCad's own
# calculator, the fab's coupon, an --impedance width solver — is computed
# against a placeholder that is not this board. The tools do not all fail
# loudly either; one of them answers "layer F.Cu not found in stackup" and
# then routes a 0.1 mm fallback width.
#
# The board has exactly one impedance target: USB 2.0 Full Speed, 90 ohm
# differential (USB_DP/USB_DN, J1 -> U6 -> U1). On these numbers the pair as
# routed — 0.3 mm wide, 0.2 mm gap, microstrip over the In1.Cu GND plane
# through 0.2104 mm of 7628 prepreg — comes out at 93.1 ohm differential,
# inside JLCPCB's +-10% window. That is why declaring the stack-up needed no
# re-route, and it is a property of THIS stack-up: the thinner-prepreg options
# JLCPCB also offers at 1.6 mm (2116 / 3313 / 1080) put the same geometry at
# 75 / 70 / 61 ohm. Do not switch stack-up without re-solving the USB widths.
#
# A GND pour on F.Cu or B.Cu would move it too, in the same direction — a
# flood at the default 0.2 mm clearance turns the pair into coplanar waveguide
# and lands it at 79 ohm, outside the window. If one is ever added, hold the
# pour >= 0.5 mm off the USB pair.
#
# Ordered top to bottom; KiCad reads it positionally, so the order is
# structural, not stylistic. Copper and dielectric thicknesses sum to
# 1.586 mm, which is the 1.6 mm nominal in (general (thickness ...)).
# (layer, type, thickness, material, epsilon_r, loss_tangent)
STACKUP = (
    ("F.SilkS", "Top Silk Screen", None, None, None, None),
    ("F.Paste", "Top Solder Paste", None, None, None, None),
    ("F.Mask", "Top Solder Mask", 0.01524, "JLCPCB Soldermask", 3.8, 0),
    ("F.Cu", "copper", 0.035, None, None, None),          # 1 oz
    ("dielectric 1", "prepreg", 0.2104, "Nan Ya Plastics NP-155F 7628", 4.4, 0.02),
    ("In1.Cu", "copper", 0.0152, None, None, None),       # 0.5 oz, GND plane
    ("dielectric 2", "core", 1.065, "Nan Ya Plastics NP-155F Core", 4.43, 0.02),
    ("In2.Cu", "copper", 0.0152, None, None, None),       # 0.5 oz, +3V3 plane
    ("dielectric 3", "prepreg", 0.2104, "Nan Ya Plastics NP-155F 7628", 4.4, 0.02),
    ("B.Cu", "copper", 0.035, None, None, None),          # 1 oz
    ("B.Mask", "Bottom Solder Mask", 0.01524, "JLCPCB Soldermask", 3.8, 0),
    ("B.Paste", "Bottom Solder Paste", None, None, None, None),
    ("B.SilkS", "Bottom Silk Screen", None, None, None, None),
)


def stackup_sexp(indent="\t\t"):
    """STACKUP as a (stackup ...) block.

    Formatted the way KiCad's own s-expression writer formats it — one field
    per line, tab-indented — and that is a requirement, not a courtesy. Only
    the FULL build's `kicad-cli pcb drc --refill-zones --save-board` pass
    rewrites the board through KiCad; on the fast path nothing is dirty, so
    kicad-cli leaves the file exactly as apply_stackup wrote it. Emit a
    compact block here and the two paths differ by ~66 lines of whitespace
    while agreeing on every value, which is precisely the byte-identity
    check_fast_path.py exists to catch.
    """
    def n(v):
        # Not f(): that rounds to 4 places, and the soldermask is 0.01524 mm.
        # These are quoted fab numbers, so they go in as quoted.
        return ("%.5f" % v).rstrip("0").rstrip(".") or "0"

    out = ["%s(stackup" % indent]
    for name, kind, thick, material, er, tand in STACKUP:
        out.append('%s\t(layer "%s"' % (indent, name))
        fields = ['(type "%s")' % kind]
        if kind in ("core", "prepreg"):
            fields.append('(color "FR4 natural")')
        if thick is not None:
            fields.append("(thickness %s)" % n(thick))
        if material is not None:
            fields.append('(material "%s")' % material)
        if er is not None:
            fields.append("(epsilon_r %s)" % n(er))
        if tand is not None:
            fields.append("(loss_tangent %s)" % n(tand))
        out.extend("%s\t\t%s" % (indent, fl) for fl in fields)
        out.append("%s\t)" % indent)
    out.append('%s\t(copper_finish "None")' % indent)
    # Tells the fab the epsilon_r values above are a constraint on the
    # substitution they are allowed to make, not a note. Without it JLCPCB may
    # ship any 1.6 mm four-layer press that fits, which is exactly the freedom
    # the USB pair's 93 ohm does not have.
    out.append("%s\t(dielectric_constraints yes)" % indent)
    out.append("%s)" % indent)
    return "\n".join(out) + "\n"


def _sexp_span(text, start):
    """(start, end) of the s-expression whose '(' is at index `start`."""
    depth = 0
    in_str = esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return start, i + 1
    raise ValueError("unbalanced s-expression at %d" % start)


def apply_stackup(path):
    """Force STACKUP into a saved .kicad_pcb, replacing whatever is there.

    pcbnew's Python bindings expose no way to set the stack-up — KiCad 10 does
    not wrap BOARD_STACKUP at all — so this is applied to the saved file, the
    same escape hatch canonicalize.py uses for the uuids it also cannot reach.
    It runs BEFORE the kicad-cli DRC pass, so on a full build the block is
    parsed and written back out by KiCad itself and a stack-up KiCad rejected
    would fail the build rather than reach the fab. The fast path saves
    nothing, which is why stackup_sexp() has to emit KiCad's formatting rather
    than rely on that pass to impose it.

    Any existing block is REPLACED rather than left alone. That is what makes
    the table above the single source of truth: a stack-up edited in the GUI,
    or inherited through --no-route's load/save round trip, does not survive a
    regeneration.
    """
    with open(path) as fh:
        text = fh.read()
    k = text.find("(stackup")
    if k >= 0:
        a, b = _sexp_span(text, k)
        a = text.rfind("\n", 0, a) + 1                    # eat the indent
        text = text[:a] + text[b + 1 if text[b:b + 1] == "\n" else b:]
    m = re.search(r"^(\t*)\(setup\b[^\n]*\n", text, re.M)
    if not m:
        raise SystemExit("%s: no (setup ...) block to put the stackup in" % path)
    text = text[:m.end()] + stackup_sexp(m.group(1) + "\t") + text[m.end():]
    with open(path, "w") as fh:
        fh.write(text)


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
    # layers nothing but the via, and the rail is a whole copper layer rather
    # than the 0.7 mm track rev A could afford.
    #
    # Signals are SIG_W = 0.3 mm and the remaining rails 0.7-0.8 mm, which is
    # rev A's net classes. The 2-layer attempt had to drop every signal AND
    # +3V3 to 0.25 mm, because on this board a signal ends on either a 0.65
    # mm-pitch TSSOP-14 (MAX31856 pins 5/8/9-12) or a 0.5 mm-pitch QFN-28
    # (ADE7953), and a track can only leave pads that fine along the pad's own
    # centreline - nothing wider clears the neighbouring pin. That constraint
    # has not gone away; what changed is that the router never touches those
    # pads any more. Each one is represented by the far end of its fanout stub
    # (FANOUT_WIDTH, still 0.25 mm) or of its plane-via stub (PLANE_STUB_W),
    # so the narrow width is confined to the ~2 mm of escape that geometrically
    # requires it and the rest of the net runs at full width.
    ("VIN", 0.8), ("+5V", 0.7), ("VLED", 0.7), ("VBUS", 0.5),
    ("AUX_VP", 0.7),
    # The multi-drop buses: longest reach, most terminals, hardest to thread.
    # The two thermocouple chip selects ride the same channel between U3 and U5
    # and are routed with them rather than with the other escapes, or the bus
    # takes the channel first and leaves them nothing.
    ("SPI_MOSI", SIG_W), ("SPI_SCLK", SIG_W), ("SPI_MISO", SIG_W),
    ("TC1_CS", SIG_W), ("TC2_CS", SIG_W),
    ("I2C_SDA", SIG_W), ("I2C_SCL", SIG_W),
    # the watchdog-gated SSR supply rail and the two switched low sides: the
    # SSR loop current (~15 mA/channel plus its indicator) all lands here
    ("SSR_EN", 0.5), ("SSR1_OUT", 0.4), ("SSR2_OUT", 0.4),
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
    ("SSR1_GATE", SIG_W), ("SSR1_IND_K", SIG_W),
    ("SSR2_GATE", SIG_W), ("SSR2_IND_K", SIG_W),
    ("SSR_PG", SIG_W), ("WDT_PUMP", SIG_W), ("WDT_HOLD", SIG_W),
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
#
# These coordinates are ANCHORS, not final positions. `silk.py` scores
# candidate placements around each anchor and moves a label off exposed
# copper, off the board edge and out of other silk; `kicad_build.py` (the
# authoritative generator) runs that placer, and `check_silk.py` proves the
# result. Only the hand-authored *intent* - what the label says and roughly
# where it belongs - lives here now.
SILK = [
    ("BISQUE KILN CONTROLLER", 62.5, 62.0, 0, 1.4),
    ("REV B", 62.5, 65.5, 0, 1.1),
    ("U.FL ANT ->", 62.0, 22.3, 0, 0.9),
    ("USB", 40.5, 22.0, 0, 0.9),
    ("RESET", 36.5, 20.9, 0, 0.9),
    ("BOOT", 100.0, 20.9, 0, 0.9),
    ("5V IN", 22.0, 34.0, 0, 0.9),
    ("+", 30.0, 39.6, 0, 1.1), ("-", 30.0, 44.7, 0, 1.3),
    ("AUX OUT", 24.5, 48.0, 0, 0.9),
    # Both SSR terminals are "+5V (watchdog-gated), switched low side" - the
    # board supplies the control loop, so the pin order is worth naming on
    # the silk. SJ3/SJ4, the old per-channel opto-collector-to-+5V links,
    # are gone with the optocouplers.
    #
    # Function and pin order are ONE label per terminal, in the gap directly
    # above that terminal's block. They used to be two texts each, anchored
    # at y=70.5/72.3 and 83.0/84.8 - and 83.0 is inside J4's courtyard
    # (72.44..83.66), not J9's, so `SSR2` printed against the wrong block.
    # The four blocks leave gaps of only 1.3-2.1 mm between them; one label
    # per gap is what actually fits, and a merged label cannot drift away
    # from the pin order it belongs to.
    ("SSR1  5V / OUT", 26.0, 71.4, 0, 0.8),
    ("SSR2  5V / OUT", 26.0, 84.3, 0, 0.8),
    ("TC1  K+/K-", 104.0, 31.0, 0, 0.9),
    ("TC2  K+/K-", 104.0, 58.5, 0, 0.9),
    ("CT A+/A-/B+/B-", 96.0, 76.0, 0, 0.9),
    ("AC SENSE - DNP", 100.0, 76.0, 0, 0.8),
    ("STATUS", 84.0, 93.6, 0, 0.9),
    # Over R44/R45, the pull-ups, and nothing else: x=66 was chosen when the
    # I2C parts ran east from there as one cluster - pull-ups then the Qwiic
    # connector - and both ends of that assumption have since moved. J14 went
    # to the bottom edge (it is side-entry; it needs an edge), the pull-ups
    # slid east into the space it left, and the label stayed put, 2.2 mm from
    # R43 and 6.1 mm from the parts it names. A zone label closer to a part it
    # does not describe than to the ones it does is worse than no label.
    ("I2C", 75.75, 93.6, 0, 0.9),
    # J14's own label. Every other user-facing connector on an edge says what
    # it is - `5V IN`, `SSR1  5V / OUT`, `TC1  K+/K-`, `INPUTS ...` - and the
    # Qwiic port arrived at the bottom edge next to the input terminal with
    # nothing but a designator, which is the one place a wrong guess costs a
    # 3.3 V part.
    # 109.4, not 110.6: J14's own designator wants the gap directly above the
    # connector, and this label has the whole 5 mm band between J7 and J14 to
    # sit in, so it gives way rather than crowding the reference out of the
    # one spot that is not the connector body.
    ("QWIIC  I2C", 88.0, 109.4, 0, 0.9),
    ("INPUTS  1 / 2 / 3 / GND", 62.6, 108.8, 0, 0.9),
    ("AUX_VP=5V", 34.0, 66.0, 0, 0.9),
    # SJ2 must be FITTED on this rev — nothing kicks the watchdog GPIO yet
    # (see main/Kconfig.projbuild KILN_PIN_WDT_KICK). "REMOVE" would be a
    # lie on every board built from this revision, so the silk just names
    # the jumper; jlcpcb/README.md and the hand-solder BOM carry the
    # fit-it-or-it-won't-heat instruction where a builder will see it.
    ("WDT DEFEAT", 50.0, 61.5, 0, 0.9),
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

# ---------------------------------------------------------------- test points
# What each TPn probes, printed beside it, so the board documents itself at
# the bench. The net is read out of design.py - a second hand-typed table is
# exactly the thing that rotted the rest of this file - and shortened by rule:
#
#   +3V3, +5V, GND     printed verbatim; a rail's name IS its label
#   a bus prefix       dropped   (SPI_MOSI -> MOSI, I2C_SDA -> SDA)
#   a function suffix  dropped   (SSR1_CTRL -> SSR1, WDT_HOLD -> WDT)
#
# TP_LABEL_SPECIAL is the one escape hatch, and it stays here beside the rule
# so there is a single place to look.
TP_BUS_PREFIX = ("SPI", "I2C", "UART", "USB")
TP_FUNC_SUFFIX = ("CTRL", "HOLD", "EN", "SEL")
TP_LABEL_SPECIAL = {"CTA_P": "CT A+", "CTA_N": "CT A-",
                    "CTB_P": "CT B+", "CTB_N": "CT B-"}


def tp_label(net):
    """Short bench label for a net name. Pure function of the net."""
    if net in TP_LABEL_SPECIAL:
        return TP_LABEL_SPECIAL[net]
    if net.startswith("+") or net == "GND":
        return net
    parts = net.split("_")
    if len(parts) > 1 and parts[0] in TP_BUS_PREFIX:
        parts = parts[1:]
    if len(parts) > 1 and parts[-1] in TP_FUNC_SUFFIX:
        parts = parts[:-1]
    return "_".join(parts)


def _tp_num(ref):
    return int(ref[2:])


for _tp in sorted((r for r in COMPONENTS
                   if r.startswith("TP") and r[2:].isdigit()), key=_tp_num):
    _x, _y, _r = COMPONENTS[_tp]["at"]
    # Anchored just below the pad: the reference designator sits above it by
    # library default, so the two share the test point without a fight.
    SILK.append((tp_label(COMPONENTS[_tp]["pins"]["1"]), _x, _y + 1.7, 0, 0.8))


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
    ap(stackup_sexp("\t\t").rstrip("\n"))
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
    # No rule areas. The opto-isolation barrier's four-layer pour keepout was
    # removed with the optocouplers (see design.py's SSR block).
    ap(')')
    text = "\n".join(out) + "\n"
    with open(dst, "w") as fh:
        fh.write(text)
    print("wrote %s (%d bytes, %d tracks, %d vias)"
          % (dst, len(text), len(r.result_tracks), len(r.result_vias)))
    return r


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
