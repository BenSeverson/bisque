"""Generate bisque-controller.kicad_pcb (KiCad 9 format).

Embeds the official library footprints, assigns nets from design.py,
autoroutes signal/power nets with router.py, adds the inner GND/+3V3
planes (unfilled — press 'B' in pcbnew), edge cuts and silkscreen labels.
"""
import json
import math
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all, Sym, num, dump
from design import COMPONENTS, netlist, BX0, BY0, BX1, BY1
import logo
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

# Copper-free box on the OUTER layers around the USB pair, (x0, y0, x1, y1).
# The measured bounding box of every USB_DP/USB_DN segment on F.Cu and B.Cu is
# x 46.86..64.00 / y 27.20..44.25; this is that plus 1 mm on each side. See
# add_zones() in kicad_build.py for why the outer GND pours are held off by
# geometry instead of by a clearance setting, and STACKUP below for the
# 93.1 ohm figure that depends on it. Re-measure this if the pair ever moves.
USB_KEEPOUT = (45.86, 26.20, 65.00, 45.25)

# Local +3V3 flood on F.Cu around U2, (x0, y0, x1, y1). The board-wide outer
# pour is GND, which does nothing for the AMS1117: its SOT-223 tab is +3V3, so
# GND copper stops at the clearance gap 1.47 mm away and conducts no heat. The
# datasheet's theta-JA range of 90 down to 46 C/W is a function of "the size of
# the copper area" attached to the tab, and at 0.726 W measured this is the one
# part on the board where that number matters.
#
# Bounded by what is actually free: J2's terminal to the west, R5 and the test
# points to the north, D1/C2 to the south, and to the east USB_KEEPOUT starts
# at 45.86 so nothing may be poured past it anyway. Everything inside on
# another net (C1 and D1 on +5V, R5 on CC2, U2's own GND and +5V pins) is
# carved out by ordinary clearance.
U2_POUR = (33.0, 30.5, 45.0, 44.5)

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
        spot, chosen = None, None
        for m in members:
            (x, y, layers, area, _net) = pads[m]
            if len(layers) == 2:
                spot = "tht"              # reaches the plane by existing
                break
            cand = _via_spot_for_pad(r, net, m[0], x, y, max_r)
            if cand is not None:
                spot, chosen = (layers[0], x, y, cand[0], cand[1]), m
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
        out += _extra_plane_vias(r, net, layer, chosen, pads, max_r)
    for f in fails:
        print("  !! no plane via spot for %s" % f)
    return out, fails


# A plane pad this big is a heat path or a ground reference, not a connection,
# and one via is not enough for either. Only three SMD plane pads on the board
# clear it: U1's 3.9 x 3.9 module ground (15.21 mm2), U7's 3.1 x 3.1 exposed
# pad (9.61) and U2's 2.0 x 3.8 SOT-223 tab (7.60). The next largest is 3.00,
# so the threshold is not near anything it might catch by accident.
BIG_PAD_AREA = 4.0        # mm^2
BIG_PAD_VIAS = 4          # total, including the group's first via


def _extra_plane_vias(r, net, layer, member, pads, max_r):
    """Additional vias for a large plane pad. [] for an ordinary one.

    WHY: `plane_vias` gives each copper-joined group exactly one via, for a
    good reason documented there - five separate ground vias on the ADE7953
    once plugged the 0.5 mm escape annulus and cost more nets than the plane
    saved. That rule is right for a pin. It is wrong for a pad whose job is
    conducting heat or anchoring a reference:

      * U2 is an AMS1117 dissipating 0.726 W measured. Its SOT-223 tab is the
        entire thermal path, and the datasheet is explicit that theta-JA runs
        from 90 down to 46 C/W purely on "the mounting technique and the size
        of the copper area". One 0.3 mm via into a 0.5 oz inner plane is the
        90 end of that range.
      * U1's module ground is the return for a radio that pulls 355 mA in
        transmit bursts.

    NOT applied to parts in FANOUT (U7, U3, U5). On a 0.5 mm-pitch part every
    node outside the pad is in the escape annulus, so extra vias there re-run
    the exact failure the one-via rule exists to prevent. U7's exposed pad
    therefore keeps its single via - it is connected and it is what ADI's own
    layout section draws, just not generously. Fixing that one needs vias
    constrained to the QFN's pinless corners, which is a bigger change than
    this and belongs with the outer-pour work.

    Spots come from repeated `_nearest_via_spot` calls, and the memo MUST be
    dropped between them. `router.via_ok` caches its answer per (net, i, j),
    and adding a via does not invalidate that cache - so without the reset
    every call re-answers "yes" for the same node and all four vias land on
    one hole. That is not a subtle failure: KiCad reports it as 12
    `holes_co_located` violations, which is how it was found. `plane_vias`
    already resets the memo between groups for the same reason; this is the
    same hazard one level down.

    Stops early and silently when no further node is legal - a crowded pad
    simply keeps the vias it could get.
    """
    (x, y, layers, area, _net) = pads[member]
    if area < BIG_PAD_AREA or member[0] in FANOUT or len(layers) == 2:
        return []
    out = []
    for _ in range(BIG_PAD_VIAS - 1):
        r._memo, r._memo_net = {}, net
        cand = _nearest_via_spot(r, net, x, y, max_r)
        if cand is None:
            break
        cx, cy = cand
        r.add_via(net, cx, cy, fixed=True)
        if abs(cx - x) > 1e-6 or abs(cy - y) > 1e-6:
            r.add_seg(net, layer, x, y, cx, cy, PLANE_STUB_W, fixed=True)
        out.append((net, cx, cy))
    if out:
        print("  %s.%s (%.2f mm2): %d plane vias"
              % (member[0], member[1], area, len(out) + 1))
    return out


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
    # rev A's width scheme - and, since netclass_table() below derives the
    # .kicad_pro classes from this very table, now rev A's net classes in the
    # project file too rather than only in the router's head.
    # The 2-layer attempt had to drop every signal AND
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

# ---------------------------------------------------------------------------
# .kicad_pro net classes
# ---------------------------------------------------------------------------
# DERIVED from ROUTE_ORDER above, never typed, and that is the whole point.
# The project file used to carry exactly one class - `Default`, 0.2 mm track,
# no netclass_patterns - while this file's comments and hardware/kicad/README
# both described a board with "0.3 mm signal / 0.7-0.8 mm power" classes. Both
# descriptions were true of what the ROUTER does and false of what the FILE
# said, because the widths only ever existed as the second element of the
# tuples above. Nothing enforced the agreement, so there was nothing to notice
# when it was never established in the first place.
#
# That gap is only invisible while the board is generated. Open this project
# in KiCad to chase one DRC marker or nudge one track, and every net hands you
# 0.2 mm - narrower than the 0.25 mm minimum this board actually uses, on a
# rail the router drew at 0.8 mm. Emitting the classes makes the interactive
# router lay down what the batch router would have.
#
# Classes are grouped by WIDTH rather than by role, and named that way, because
# width is the only thing they actually share: 0.4 mm covers the two SSR
# switched low sides AND the four CT sense nets, which have nothing else in
# common. A name like "Power" would be a lie for half its members.
NETCLASS_CLEARANCE = 0.2      # as routed; JLCPCB's 4-layer floor is 0.09
# The one impedance-controlled pair on the board. Values are the geometry the
# 93.1 ohm figure in STACKUP's comment is computed from - if you retune one,
# retune the other, and re-solve against the stack-up rather than guessing.
USB_DIFF_PAIR = ("USB_DP", "USB_DN")
USB_DIFF_WIDTH, USB_DIFF_GAP = 0.3, 0.2


def netclass_table():
    """[(name, {field: value}, [net, ...])] for the .kicad_pro net_settings.

    `Default` is absent on purpose: it stays whatever the project already says
    apart from the widths patched in by sync_netclasses(), so every net not
    named here inherits SIG_W without needing a pattern of its own.
    """
    by_width = {}
    for net, w in ROUTE_ORDER:
        if w != SIG_W:
            by_width.setdefault(w, []).append(net)
    out = []
    # Widest first, so the emitted order reads like the rail hierarchy.
    for w in sorted(by_width, reverse=True):
        out.append(("Track_%.2fmm" % w, {"track_width": w}, sorted(by_width[w])))
    # The plane nets reach their layer by via; the only copper they own on a
    # routing layer is the PLANE_STUB_W stub from pad to via, so that is the
    # width a hand-drawn GND or +3V3 track should default to as well.
    out.append(("Plane", {"track_width": PLANE_STUB_W}, sorted(PLANE_LAYER)))
    out.append(("USB", {"track_width": USB_DIFF_WIDTH,
                        "diff_pair_width": USB_DIFF_WIDTH,
                        "diff_pair_gap": USB_DIFF_GAP},
                sorted(USB_DIFF_PAIR)))
    return out


def sync_netclasses(pro_path):
    """Write the derived net classes into `pro_path`. True if it changed.

    Idempotent, and it has to be: `pcbnew.SaveBoard()` on the full path blanks
    `net_settings` exactly the way it blanks `schematic.top_level_sheets` (a
    BOARD carries a PROJECT and the full path's board is a bare, project-less
    `pcbnew.BOARD()`), so this runs AFTER the board is written, not before.
    Measured: a fresh BOARD saved beside a populated .kicad_pro drops every
    class but Default and empties netclass_patterns.

    Each class is cloned from the project's own `Default` rather than authored
    field-by-field here. KiCad's netclass schema carries a dozen keys this
    board does not care about (bus_width, microvia_*, pcb_color, wire_width,
    tuning_profile...), and a literal would silently freeze whatever set was
    current the day it was written; cloning tracks the schema for free and
    keeps the diff to the fields actually being set.

    Both lists are emitted SORTED BY NAME, which is not cosmetic. KiCad
    rewrites `classes` in alphabetical order whenever it touches the project,
    so emitting them in width order (the order netclass_table() builds them
    in, widest rail first) meant every build read back a differently-ordered
    list, compared unequal against an identical set, and rewrote the file -
    reporting a change on a run where nothing had changed. Sorting to KiCad's
    own order makes the comparison meaningful and the file stable no matter
    which of the two wrote it last. `priority` still carries the width
    ordering, which is the part KiCad actually resolves against.
    """
    if not os.path.exists(pro_path):
        return False              # scratch builds (check_fast_path) have none
    with open(pro_path) as fh:
        doc = json.load(fh)
    ns = doc.setdefault("net_settings", {})
    classes = ns.setdefault("classes", [])
    base = next((c for c in classes if c.get("name") == "Default"), None)
    if base is None:
        return False              # no template to clone; leave the file alone
    want = [dict(base, name="Default", track_width=SIG_W,
                 clearance=NETCLASS_CLEARANCE)]
    patterns = []
    # priority: lower binds tighter, and Default sits at INT_MAX so anything
    # numbered here outranks it. Assigned in netclass_table() order (widest
    # rail first) even though the emitted list is then sorted by name.
    for pri, (name, fields, nets) in enumerate(netclass_table()):
        want.append(dict(base, name=name, clearance=NETCLASS_CLEARANCE,
                         priority=pri, **fields))
        patterns += [{"netclass": name, "pattern": n} for n in nets]
    want.sort(key=lambda c: c["name"])
    patterns.sort(key=lambda p: (p["netclass"], p["pattern"]))
    if classes == want and ns.get("netclass_patterns") == patterns:
        return False
    ns["classes"] = want
    ns["netclass_patterns"] = patterns
    with open(pro_path, "w") as fh:
        fh.write(json.dumps(doc, indent=2) + "\n")
    return True


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


# ----------------------------------------------------------- the nameplate
# The board's own title block: the flame, the wordmark, the revision and the
# copyright, as one centred stack.
#
# It used to be two texts at (62.5, 62.0) and (62.5, 65.5), in what the
# comment here called "the large clear band between the switching region and
# the analog region". That band stopped being clear somewhere on the way to
# 141 parts: the anchor now sits between SJ2 and the J5 fanout, the placer
# moved the title every build, and a title that lands wherever there is a gap
# reads as a caption on whatever it landed beside.
#
# TITLE_POCKET is the board's largest genuinely empty rectangle, measured off
# the pad and courtyard geometry rather than eyeballed - 18 x 32 mm with no
# exposed pad, no courtyard and no board edge inside it, the lane between the
# SSR/aux side and the ADE7953 cluster. The next-largest is 28 x 10.5 mm at
# (59.5, 45), which the four-row stack does not fit in.
#
# Rows are DERIVED rather than typed. KiCad's text bounding box is exactly
# 1.7x the glyph size at every size used here, so a stack laid out from the
# sizes and the gaps stays tight when a size changes - four typed
# y-coordinates do not, and a nameplate drifting apart one row at a time is
# how the old two-line one ended up with its subtitle 3.5 mm below it.
TITLE_POCKET = (68.0, 63.0, 86.0, 95.0)     # x0, y0, x1, y1
TITLE_LOGO_H = 11.0                          # flame height, mm
TITLE_LOGO_GAP = 2.0                         # flame to wordmark, mm
TEXT_BOX_RATIO = 1.7                         # KiCad text bbox height / size
# (text, glyph size, gap below)
TITLE_ROWS = [("BISQUE", 2.6, 0.7),
              ("KILN CONTROLLER", 1.2, 1.3),
              ("REV B", 1.0, 0.7),
              ("© 2026 Ben Severson", 0.9, 0.0)]


def _title_block():
    """([(text, x, y, rot, size)], (logo_cx, logo_cy)) for the nameplate."""
    x0, y0, x1, y1 = TITLE_POCKET
    cx = (x0 + x1) / 2.0
    stack = (TITLE_LOGO_H + TITLE_LOGO_GAP
             + sum(s * TEXT_BOX_RATIO + g for _t, s, g in TITLE_ROWS))
    y = y0 + ((y1 - y0) - stack) / 2.0
    logo_at = (cx, y + TITLE_LOGO_H / 2.0)
    y += TITLE_LOGO_H + TITLE_LOGO_GAP
    rows = []
    for txt, size, gap in TITLE_ROWS:
        h = size * TEXT_BOX_RATIO
        rows.append((txt, cx, y + h / 2.0, 0, size))
        y += h + gap
    return rows, logo_at


_TITLE_TEXTS, TITLE_LOGO_AT = _title_block()

# Free-standing silk GRAPHICS, as [(closed polyline in mm, stroke width mm)].
# Unlike the texts below these are not anchors: `silk.py` does not move a
# graphic, it routes labels around one, so what is written here is where it
# prints. The flame is the project's own mark, carried as an SVG path in
# `logo.py` rather than traced into a point table here.
SILK_GRAPHICS = [logo.flame(TITLE_LOGO_AT[0], TITLE_LOGO_AT[1], TITLE_LOGO_H)]

# Free-standing silk: the nameplate above, then every label that sits beside
# the connector or control it names.
#
# These coordinates are ANCHORS, not final positions. `silk.py` scores
# candidate placements around each anchor and moves a label off exposed
# copper, off the board edge and out of other silk; `kicad_build.py` (the
# authoritative generator) runs that placer, and `check_silk.py` proves the
# result. Only the hand-authored *intent* - what the label says and roughly
# where it belongs - lives here now.
SILK = _TITLE_TEXTS + [
    ("USB", 40.5, 22.0, 0, 0.9),
    # Both button legends used to be anchored in the 1.2-2.0 mm strip between
    # the board edge and the switch, and both were pushed under their button
    # instead - the one place a legend is guaranteed to be unreadable on a
    # finished board. The strips are not the same size, so the fixes are not
    # either. SW2's silk starts at 22.19, leaving 1.99 mm above it, which
    # takes a 0.9 text box (1.53) with room to spare - `BOOT` just needed an
    # anchor that was actually in the strip rather than 0.3 mm below it.
    # SW1's silk starts at 21.39: 1.19 mm, which takes nothing legible, so
    # `RESET` goes to its west instead, in the 4.20 mm between H1's pad ring
    # and SW1's own pads, at 0.8 because 0.9 does not fit there. It displaces
    # `SW1`, which is the right trade - a designator is recoverable from the
    # board, a button legend is not.
    ("RESET", 31.0, 24.2, 0, 0.8),
    # South of SW2, not north, even though north is where the room is. North
    # is also where `SW2` was already sitting, and a board text cannot evict
    # a seated reference: the placer runs greedily over a live index, so the
    # designator is an obstacle from pass 1 and only moves if something makes
    # IT move. `RESET` got its spot because `SW1` independently preferred
    # another side; `SW2` did not, so `BOOT` spent two rebuilds pinned to the
    # button. The 2.43 mm between SW2's silk and `TC1  K+/K-` needs no
    # argument with anybody.
    ("BOOT", 100.0, 28.9, 0, 0.9),
    # LED2 is the +3V3 power-on indicator (green, LEDP_K through R9 to GND).
    # It went unlabelled through rev B, which on a board with three other
    # LEDs is a guess. East rather than north: LED2's own silk starts 1.08 mm
    # below the edge clearance line and nothing legible fits there, but
    # removing `U.FL ANT ->` (an arrow pointing at a connector that is
    # already the only thing it could point at) freed the strip beside it.
    ("PWR", 58.0, 20.9, 0, 0.8),
    ("5V IN", 22.0, 34.0, 0, 0.9),
    # The only per-terminal marks on the board, and they were the only two
    # labels whose anchor was INSIDE the part it names: x=30.0 is 1.25 mm
    # inside J2's body (21.35..31.25), so both printed under the block and
    # vanished the moment it was soldered. East of J2 there is a 3.45 mm gap
    # before U2, which is where they go now.
    #
    # The y values are the pad centres (39.00 / 44.08), not the 39.6 / 44.7
    # they used to be: on a block this size 0.6 mm of drift is most of the
    # way to the next screw, and a polarity mark that points between two
    # terminals says nothing. That also makes these the two labels where the
    # placer's own bias is backwards - `W_LATERAL` charges four times as much
    # for sliding along the reading direction, but for a mark beside a
    # vertically stacked terminal it is the PERPENDICULAR slide that renames
    # the screw. Anchoring them somewhere they need not move is the fix;
    # silk.py has no way to know which axis carries the meaning.
    ("+", 32.8, 39.0, 0, 1.1), ("-", 32.8, 44.08, 0, 1.3),
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
    # The two amber channel indicators. Each sits across its own terminal
    # pair through a 680R, so it lights only when that channel is driven AND
    # the watchdog rail is up - which is exactly the thing a person standing
    # at the kiln wants to read off the board, and it had no legend at all.
    # `ON` rather than a bare `SSR1`: the SSR1 test point is 5 mm away and
    # already says that, and two identical words on one part of the board
    # would be worse than none.
    ("SSR1 ON", 57.0, 74.3, 0, 0.8),
    ("SSR2 ON", 54.0, 85.2, 0, 0.8),
    ("TC1  K+/K-", 104.0, 31.0, 0, 0.9),
    ("TC2  K+/K-", 104.0, 58.5, 0, 0.9),
    # In the free band above J12, centred on the block, NOT at (96, 76).
    # That anchor was 6.5 mm west of J12 with `AC SENSE - DNP` already in the
    # same 1 mm of board, so the placer took the far end of its ring - all
    # 14 mm of it - and printed the CT legend directly under `TC2  K+/K-`:
    # 12.98 mm from the block it names, 8.38 mm from the one it does not.
    # J8's bottom is 55.59 and J12's top is 74.17, so there is an 18 mm strip
    # here and nothing else wants it.
    ("CT A+/A-/B+/B-", 112.8, 72.0, 0, 0.9),
    # J13's legend, and it has to be centred ON J13 to say so. At (100, 76)
    # it printed 1.30 mm from J13 but 0.37 mm from C35 and 0.77 mm from the
    # ADE7953, straight across that chip's own value text, so the one part it
    # was not obviously describing was the header. DNP = do not populate:
    # this is the ADE7953's voltage channel (VP/VN), deliberately unfitted
    # because no mains touches this board, and the header exists so a future
    # isolated AC accessory is a firmware change rather than a respin. The
    # dash is dropped to buy the 1.6 mm that keeps it clear of C31's
    # designator.
    ("AC SENSE DNP", 98.5, 76.9, 0, 0.8),
    ("STATUS", 84.0, 93.6, 0, 0.9),
    # There is deliberately no `I2C` zone label. One used to sit over R44/R45
    # - correctly, after a move; it started life 6.1 mm from the parts it
    # named - and it was still the wrong label, because naming two pull-up
    # resistors tells a reader nothing they can act on. What it looked like
    # instead was a caption on the nameplate 3 mm above it. The bus is named
    # where a person actually meets it: `SDA`/`SCL` on J7's pin row and
    # `QWIIC  I2C` on J14.
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
    # SJ1's legend, and now it is actually at SJ1 (44.30..47.70, 48.20..50.80)
    # rather than 17 mm away beside J10, where it read as a note about the AUX
    # terminal and left the jumper itself with nothing but a designator. SJ1
    # links +5V to AUX_VP, the ULN2003's COM rail, for plain 5 V relay coils;
    # it is open by default because AUX_VP is an externally supplied rail
    # (J10 pin 1) and a 12/24 V solenoid supply meeting +5V would be a short.
    # It is NOT the watchdog jumper - that is SJ2, `WDT DEFEAT`, 8 mm south.
    # North of SJ1 rather than south: R25's designator leaves 1.37 mm below
    # it for a 1.36 mm text box, and a 0.01 mm margin is not a placement.
    # `AUX=5V` rather than the net's own `AUX_VP=5V`, which is 7.01 mm wide
    # in a 7.14 mm window and was landing 0.52 mm off C2 - close enough to
    # read as C2's label. The shorter form leaves ~1 mm either side, and the
    # rail it names is already spelled out on J10 as `AUX OUT`.
    ("AUX=5V", 47.3, 46.3, 0, 0.8),
    # SJ2 must be FITTED on this rev — nothing kicks the watchdog GPIO yet
    # (see main/Kconfig.projbuild KILN_PIN_WDT_KICK). "REMOVE" would be a
    # lie on every board built from this revision, so the silk just names
    # the jumper; jlcpcb/README.md and the hand-solder BOM carry the
    # fit-it-or-it-won't-heat instruction where a builder will see it.
    # Directly below SJ2 (55.30..58.70, 56.20..58.80), in the gap before
    # BZ1's outline starts at y=62.90. The old anchor at (50, 61.5) was
    # already 7 mm from the jumper and hard against that outline, so the
    # placer slid it 10 mm - the whole label ended up centred inside the
    # buzzer, which is both invisible once BZ1 is fitted and, before it is,
    # reads as the buzzer's own name. x=58.0 rather than SJ2's own 57.0
    # keeps the left end clear of TP12 at 53.04.
    ("WDT DEFEAT", 58.0, 60.8, 0, 0.9),
]
# Parts whose reference designator is not printed. A designator earns its ink
# by answering a question, and "which screw hole is this" is not one anybody
# asks: H1-H4 are M3 mounting holes, interchangeable, and identified by being
# the four holes in the corners. Four labels in the four most crowded corners
# of the board is a cost with no reader.
#
# FID1-3 join them for the same reason and one more. Nobody identifies a
# fiducial by name - the machine finds them by shape, and a human never refers
# to one - so the label answers nothing. The extra reason is that silk near a
# fiducial is not merely useless but actively unhelpful: the target works by
# contrast between bare copper and bare laminate, and white ink inside the
# camera's window is the one thing in the neighbourhood that could confuse it.
# The placer already keeps silk off copper, so this is belt and braces.
#
# This is deliberately a short list and should stay one. Everything else on
# the board is a part somebody has to identify against a BOM, a schematic or
# a fault, and an unlabelled one of those is the defect this whole placer
# exists to avoid.
HIDE_REFS = {"H1", "H2", "H3", "H4", "FID1", "FID2", "FID3"}

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


# Below the pad is the rule; TP10 is the exception, and it is the crowding
# that makes it one. C11's and R39's designators sit at y 94.3..95.8 either
# side of it and their 0805 silk marks leave a 3.29 mm window at y~97 for a
# 3.28 mm label, so the only clear spot below the pad is y~98.5 - which is
# 1.2 mm above J5's pin-name row and in line with its `SDO`/`TCK` pins, where
# `SSR2` reads as a fifteenth pin on the display header rather than as a test
# point 4.4 mm away. Above TP10's own designator is empty, so it goes there:
# SSR2 / TP10 / pad, reading down.
TP_LABEL_AT = {"TP10": (44.5, 91.0)}

for _tp in sorted((r for r in COMPONENTS
                   if r.startswith("TP") and r[2:].isdigit()), key=_tp_num):
    _x, _y, _r = COMPONENTS[_tp]["at"]
    # Anchored just below the pad: the reference designator sits above it by
    # library default, so the two share the test point without a fight.
    _at = TP_LABEL_AT.get(_tp, (_x, _y + 1.7))
    SILK.append((tp_label(COMPONENTS[_tp]["pins"]["1"]), _at[0], _at[1], 0, 0.8))


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
    for k, (pts, width) in enumerate(SILK_GRAPHICS):
        poly = " ".join("(xy %s %s)" % (f(x), f(y)) for x, y in pts)
        ap('\t(gr_poly (pts %s)\n'
           '\t\t(stroke (width %s) (type solid)) (fill no)\n'
           '\t\t(layer "F.SilkS") (uuid "%s")\n\t)'
           % (poly, f(width), uid("silkgfx", k)))
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
