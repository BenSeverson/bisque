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


def pad_centres(ref):
    """{pin name: (x, y)} in board mm, for the placed footprint `ref`.

    Multi-pad pins (a USB shield, a JST mounting peg) collapse to their
    first pad; nothing that asks this question cares about the rest.
    """
    out = {}
    for (name, _k, gx, gy, _w, _h, _c, _l, _hole) in \
            pad_geometry(COMPONENTS[ref]):
        out.setdefault(name, (gx, gy))
    return out


def fp_body_box(comp):
    """Global (x0, y0, x1, y1) of a placed footprint's drawn body.

    F.Fab and F.SilkS graphics, never text and never the courtyard. This is
    the outline a fitted part occupies and a legend has to stay outside of;
    a courtyard is placement slack and is routinely 0.25-0.5 mm wider, which
    on a 1.7 mm band is the difference between a legend that fits and one
    that does not. Returns None for a footprint that draws neither.
    """
    fp = load_fp(comp["fpf"])
    fx, fy, frot = comp["at"]
    box = None
    for key in ("fp_line", "fp_rect", "fp_poly", "fp_circle", "fp_arc"):
        for it in find_all(fp, key):
            lay = find(it, "layer")
            if not lay or str(lay[1]) not in ("F.Fab", "F.SilkS"):
                continue
            pts = []
            for k in ("start", "end", "center", "mid"):
                e = find(it, k)
                if e:
                    pts.append((num(e[1]), num(e[2])))
            plist = find(it, "pts")
            if plist:
                pts += [(num(xy[1]), num(xy[2])) for xy in find_all(plist, "xy")]
            if key == "fp_circle" and len(pts) >= 2:
                r = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
                cx, cy = pts[0]
                pts = [(cx - r, cy - r), (cx + r, cy + r)]
            for lx, ly in pts:
                gx, gy = rot_xy(lx, ly, frot)
                gx, gy = gx + fx, gy + fy
                box = ((gx, gy, gx, gy) if box is None else
                       (min(box[0], gx), min(box[1], gy),
                        max(box[2], gx), max(box[3], gy)))
    return box


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
    # 30.75, not 31.25. The escape seed used to overshoot by 0.5 mm: the
    # router branches off wherever the net's existing copper is nearest,
    # which after a re-route was 30.75, and the last half millimetre was
    # left as a dangling tail - a `track_dangling` warning on a board whose
    # report reads 0/0/0. A seed should end where the escape ends.
    ("USB_DP", 0, [(47.25, 28.445), (47.25, 30.75)], 0.25),
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
# The ADE7953's two I2C escapes, hand-seeded for the same reason the USB pair
# above is: they are the one place on this board where the greedy router's
# answer is not stable, and the lane each one needs is a single track wide.
#
# U7's SDA and SCL leave a 0.5 mm-pitch QFN into the tightest neighbourhood on
# the board (2.30 parts/cm2, and every escape from a 28-pin part passes
# through it). Their fanout stubs end at (94.50, 68.00) and (94.00, 67.00)
# with two and six free grid nodes respectively; whichever net reaches its
# stub first takes the only lane and the other cannot get in. That is not an
# ordering problem and promotion does not fix it - I2C_SDA fails at (94.50,
# 68.00) even when routed FIRST, before any other signal exists, because by
# then the fixed geometry (the other 26 pins' stubs and U7's own plane vias)
# is already in place.
#
# It is stable at the fixed point: the committed rev-B board routes both. It
# is NOT stable under perturbation - six unrelated placement changes
# elsewhere on the board re-rolled it and cost first one net and then the
# other, over five full re-routes. So the lanes are written down. These are
# the exact geometries the router itself found when it did succeed, read back
# off that board, which is what makes them a record rather than a guess.
ADE_I2C_SEEDS = [
    ("I2C_SDA", 0, [(92.75, 64.00), (94.50, 65.75), (94.50, 68.00)], 0.3),
    ("I2C_SCL", 0, [(94.00, 67.00), (93.75, 67.25)], 0.3),
    ("I2C_SCL", 1, [(93.75, 67.25), (93.75, 76.00)], 0.3),
]
# Vias the router may not place for itself. `via_ok` is false at both I2C
# stub ends - there is not room for a via pad beside a 0.5 mm-pitch escape -
# so SCL's drop to B.Cu, which is how the original route left the block, has
# to be given to it.
MANUAL_VIAS = [("I2C_SCL", 93.75, 67.25)]
# ... and the far end of a hand escape has to BE the net's terminal there,
# exactly as USB_STUB_TERMS does for J1. Seed the lane without moving the
# terminal and the router is still free to reach the fanout stub the short
# way; it did, both nets came out electrically complete, and the seeds were
# left hanging off the stub as 2.5 mm and 8.8 mm of dangling copper -
# antennas, and two `track_dangling` warnings against a board whose report
# reads 0/0/0. {net: (fanout stub end this replaces, (x, y, layers))}.
ADE_I2C_TERMS = {
    "I2C_SDA": ((94.50, 68.00), (92.75, 64.00, (0,))),
    "I2C_SCL": ((94.00, 67.00), (93.75, 76.00, (1,))),
}
# nets whose J1 pads are replaced by stub terminals (ends grid-aligned)
USB_STUB_TERMS = {
    "USB_DN": [(48.75, 31.25, (0,))],
    "USB_DP": [(47.25, 30.75, (0,))],
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
# U10 is a 0.5 mm-pitch VSSOP-8 and needs this for the same reason U7 does:
# without a seeded escape its pads report "0 goal nodes, free neighbours F=0"
# - the front layer between 0.5 mm-pitch pads is entirely clearance, and
# via-in-pad is forbidden, so a pad with no lane cannot start a route at all.
# 1.75 mm, the same length U7 needs: at 0.5 mm pitch four parallel stubs
# leave only a 0.2 mm gap between them, so they need to run clear of the
# pad row before they can fan out at all. 1.25 mm was not enough - pin 2
# never got a lane and WDT_KICK could not leave the part.
FANOUT = {"U7": 1.75, "U3": 1.5, "U5": 1.5, "U10": 1.75}
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

# Copper layer TYPE. KiCad never acts on this - it fills zones and runs DRC
# identically whatever it says - but it is the only machine-readable statement
# of what the stack-up IS, and leaving the inner layers on the "signal" default
# made every EMC tool read this as a four-signal-layer board and report
# "adjacent signal layers: F.Cu, In1.Cu" against a stack-up that is textbook.
# The inner layers carry the two plane fills named in PLANE_LAYER above and not
# one track between them, so "power" is simply the truth.
#
# Read twice, and both readers matter: the text emitter below writes it into
# the board gen_pcb hands to pcbnew, and kicad_build.apply_layer_types() sets
# it again on the loaded board, because pcbnew rewrites the layer table from
# its own model on save and drops whatever the input text said. Setting it in
# only one of the two places is silently a no-op.
COPPER_LAYER_TYPE = {
    "F.Cu": "signal",
    "In1.Cu": "power",     # GND plane
    "In2.Cu": "power",     # +3V3 plane
    "B.Cu": "signal",
}
PLANE_NETS = tuple(PLANE_LAYER)
PLANE_STUB_W = 0.25

# Copper-free box on the OUTER layers around the USB pair, (x0, y0, x1, y1).
# The measured bounding box of every USB_DP/USB_DN segment on F.Cu and B.Cu is
# x 47.25..64.00 / y 27.20..46.25; this is that plus 1 mm on each side. See
# add_zones() in kicad_build.py for why the outer GND pours are held off by
# geometry instead of by a clearance setting, and STACKUP below for the
# 93.1 ohm figure that depends on it. Re-measure this if the pair ever moves.
#
# It moved once already, and the lesson is that this box is a consequence of
# U4 and not just of J1 and U1. Swapping the USBLC6 for an SRV05-4 turned the
# array from a link in the pair into a stub off it, and the pair re-routed
# around a package it used to pass through: 2 mm further south (DP now reaches
# y 46.25, having previously stopped at 42.10) even after U4's channels were
# moved to the pins facing U1. Both nets are marginally SHORTER than before
# (DP 39.08 mm against 40.13, DN 36.97 against 37.05), so this is a change of
# shape, not of length.
#
# The west edge is the one to watch, because U2_POUR ends at x 45.0 and a
# keepout reaching past that silently eats the AMS1117's thermal copper - the
# pour is still emitted, it just does not fill. At 46.25 there is 1.25 mm of
# daylight. The first attempt at the U4 pin map left it at 44.50 and would
# have taken the bite without failing anything.
USB_KEEPOUT = (46.25, 26.20, 65.00, 47.25)

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
    # A real finish, not "None": KiCad copies this into the .gbrjob's Finish
    # field, and "None" told the fab nothing — the order form was the only
    # place the finish existed, so a mis-click there had nothing to disagree
    # with. ENIG for the flat pads: the ADE7953 is a 0.5 mm-pitch QFN with a
    # 3.1 mm exposed pad, and HASL's crown is worst exactly under a large EP.
    # Change this string and the order form together, or the check below is
    # worthless.
    out.append('%s\t(copper_finish "ENIG")' % indent)
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
    seeds = list(USB_SEEDS) + list(ADE_I2C_SEEDS)
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
    for net, (drop, term) in sorted(ADE_I2C_TERMS.items()):
        terms[net] = [t for t in terms.get(net, [])
                      if (round(t[0], 3), round(t[1], 3)) != drop] + [term]
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
    ("SSR_PG", SIG_W), ("WDT_OK", SIG_W), ("WDT_CT_P", SIG_W),
    ("WDT_CT_N", SIG_W),
    # buzzer, status LED
    ("BUZZ_GATE", SIG_W), ("WS_DIN", SIG_W),
    # thermocouple front-ends (short, local, kept matched)
    ("TC1_P", SIG_W), ("TC1_N", SIG_W), ("TC1_P_F", SIG_W), ("TC1_N_F", SIG_W),
    ("TC2_P", SIG_W), ("TC2_N", SIG_W), ("TC2_P_F", SIG_W), ("TC2_N_F", SIG_W),
    # CT front-end and its terminal
    ("CTA_P", 0.4), ("CTA_N", 0.4), ("CTA_F", SIG_W),
    ("CTB_P", 0.4), ("CTB_N", 0.4), ("CTB_F", SIG_W),
    # ADE7953 locals
    ("ADE_CLKIN", SIG_W), ("ADE_REF", SIG_W),
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
# The pocket it goes in is MEASURED, not typed. The nameplate is the last
# thing on the board that needs a particular place to be: every part is
# somewhere for an electrical reason and every other legend has to sit beside
# the thing it names, so the title block is whatever is left over - and
# "whatever is left over" is a thing a program can find, at build time,
# against the placement as it actually is.
#
# It used to be the constant (68, 63, 86, 95): 18 x 32 mm, correct, and
# measured by hand once. The trouble with the hand measurement is not that it
# was wrong, it is that nothing re-took it. Four parts moved in this
# revision, one of them into the band next door, and a stale pocket is
# invisible - the nameplate still prints, just somewhere that stopped being
# empty. `largest_empty_rect` re-derives it from the same pad and body
# geometry the hand measurement used, so it is the same answer when nothing
# has changed and a different one when something has.
#
# Rows are DERIVED rather than typed too. KiCad's text bounding box is
# 1.7x the glyph size at every size used here, so a stack laid out from the
# sizes and the gaps stays tight when a size changes - four typed
# y-coordinates do not, and a nameplate drifting apart one row at a time is
# how the old two-line one ended up with its subtitle 3.5 mm below it.
TITLE_LOGO_H = 11.0                          # flame height, mm
TITLE_LOGO_GAP = 2.0                         # flame to wordmark, mm
TEXT_BOX_RATIO = 1.7                         # KiCad text bbox height / size
# KiCad stroke-font advance / (glyph size x character count), measured with
# pcbnew over this nameplate's own rows: 0.918-0.961 for the multi-character
# strings here. Rounded up, because the number it feeds is a minimum size the
# pocket has to clear.
TEXT_WIDTH_RATIO = 0.98
# (text, glyph size, gap below)
TITLE_ROWS = [("BISQUE", 2.6, 0.7),
              ("KILN CONTROLLER", 1.2, 1.3),
              ("REV B", 1.0, 0.7),
              ("© 2026 Ben Severson", 0.9, 0.0)]
# Clear board the nameplate keeps around itself and from the outline, mm. The
# first is not slack: the parts bounding the pocket still have to put their
# own reference designators somewhere, and `silk.py`'s side offsets start
# 0.25 mm off the body and reach ~5.4 mm, so a pocket taken hard against a
# part body is one taken out of that part's designator.
TITLE_MARGIN, TITLE_EDGE = 0.75, 2.0
POCKET_GRID = 0.25                           # search resolution, mm
# How far the whole nameplate may be shrunk to fit the space that is left,
# and the floor below which it is not worth printing. The block is the only
# thing on this board that yields to everything else - a part is somewhere
# for an electrical reason and a legend has to be beside what it names - so
# when the free space shrinks, this shrinks rather than displacing either.
# Below TITLE_MIN_SCALE, don't print a nameplate: say so and let a person
# decide what to give up.
TITLE_MIN_SCALE = 0.60
# ... and no row goes under this however far the block scales. It is the
# board's OWN silk-text-height rule, the one KiCad DRC checks - a 0.876 scale
# once put the copyright line at 0.789 mm and earned a `text_height` warning
# against a file whose whole claim is 0/0/0. Flooring a row makes the stack
# slightly taller than pure scaling, so the fit is solved by iteration rather
# than by one division.
TITLE_MIN_TEXT = 0.8


def _keepout_box(comp, margin):
    """(x0, y0, x1, y1) a free-standing graphic must stay out of, in mm.

    The drawn body union the copper, grown by `margin`. Pads matter on their
    own account because the footprints that draw no body at all - test
    points, mounting holes, solder jumpers - are exactly the flat ones a
    pocket search would otherwise walk straight over.
    """
    box = fp_body_box(comp)
    for (_n, _k, gx, gy, w, h, _c, _l, _hole) in pad_geometry(comp):
        pb = (gx - w / 2.0, gy - h / 2.0, gx + w / 2.0, gy + h / 2.0)
        box = pb if box is None else (min(box[0], pb[0]), min(box[1], pb[1]),
                                      max(box[2], pb[2]), max(box[3], pb[3]))
    if box is None:
        return None
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def largest_empty_rect(min_w, min_h, margin=TITLE_MARGIN, edge=TITLE_EDGE,
                       grid=POCKET_GRID):
    """The biggest empty (x0, y0, x1, y1) on the board that fits min_w/min_h.

    Rasterise every part's keep-out onto a `grid` mm lattice inside the board
    outline, then take the largest all-free axis-aligned rectangle by the
    standard largest-rectangle-in-histogram sweep, considering only
    rectangles at least min_w x min_h. Ties break on area, then on the
    topmost then leftmost corner, so the answer is a function of the
    placement and nothing else - `check_canonical.py` requires that much.

    Copper is deliberately NOT an obstacle. Silkscreen over a track is
    covered by soldermask and prints perfectly; only exposed pads matter, and
    those are in the keep-out already.
    """
    nx = int((BX1 - BX0) / grid)
    ny = int((BY1 - BY0) / grid)
    free = [bytearray(b"\1") * nx for _ in range(ny)]

    def block(x0, y0, x1, y1):
        c0 = max(0, int(math.floor((x0 - BX0) / grid)))
        c1 = min(nx - 1, int(math.ceil((x1 - BX0) / grid)))
        r0 = max(0, int(math.floor((y0 - BY0) / grid)))
        r1 = min(ny - 1, int(math.ceil((y1 - BY0) / grid)))
        for r in range(r0, r1 + 1):
            row = free[r]
            for c in range(c0, c1 + 1):
                row[c] = 0

    block(BX0, BY0, BX1, BY0 + edge)
    block(BX0, BY1 - edge, BX1, BY1)
    block(BX0, BY0, BX0 + edge, BY1)
    block(BX1 - edge, BY0, BX1, BY1)
    for comp in COMPONENTS.values():
        box = _keepout_box(comp, margin)
        if box:
            block(*box)

    need_c = int(math.ceil(min_w / grid))
    need_r = int(math.ceil(min_h / grid))
    best = None                          # (area, -r0, -c0, c0, r0, c1, r1)
    height = [0] * nx
    for r in range(ny):
        row = free[r]
        for c in range(nx):
            height[c] = height[c] + 1 if row[c] else 0
        # Monotonic stack over the row's histogram, with a sentinel so every
        # bar is popped exactly once.
        stack = []
        for c in range(nx + 1):
            h = height[c] if c < nx else 0
            start = c
            while stack and stack[-1][1] >= h:
                start, sh = stack.pop()
                w = c - start
                if sh >= need_r and w >= need_c:
                    key = (sh * w, -(r - sh + 1), -start)
                    if best is None or key > best[0]:
                        best = (key, start, r - sh + 1, c - 1, r)
            stack.append((start, h))
    if best is None:
        raise SystemExit(
            "no empty %.1f x %.1f mm rectangle on the board for the nameplate"
            " - free space is gone, or TITLE_MARGIN is too generous" %
            (min_w, min_h))
    _k, c0, r0, c1, r1 = best
    return (BX0 + c0 * grid, BY0 + r0 * grid,
            BX0 + (c1 + 1) * grid, BY0 + (r1 + 1) * grid)


def _title_extent(k):
    """(width, height, [row size]) of the nameplate at scale `k`."""
    sizes = [max(TITLE_MIN_TEXT, s * k) for _t, s, _g in TITLE_ROWS]
    h = TITLE_LOGO_H * k + TITLE_LOGO_GAP * k
    for (txt, _s, gap), size in zip(TITLE_ROWS, sizes):
        h += size * TEXT_BOX_RATIO + gap * k
    w = max([TITLE_LOGO_H * k] +
            [len(t) * size * TEXT_WIDTH_RATIO
             for (t, _s, _g), size in zip(TITLE_ROWS, sizes)])
    return w, h, sizes


def _title_block():
    """([(text, x, y, rot, size)], (logo_cx, logo_cy), logo_h, scale)."""
    x0, y0, x1, y1 = largest_empty_rect(*_title_extent(TITLE_MIN_SCALE)[:2])
    box_w, box_h = x1 - x0, y1 - y0
    # Fit, then stop at full size: the sizes in TITLE_ROWS are the design, and
    # a big empty board is not a reason to print a bigger wordmark. Iterating
    # rather than dividing once, because TITLE_MIN_TEXT stops the small rows
    # shrinking with the rest and so makes the answer non-linear in k.
    k = 1.0
    for _ in range(12):
        w, h, sizes = _title_extent(k)
        if w <= box_w and h <= box_h:
            break
        k *= min(box_w / w, box_h / h) * 0.999
    else:
        raise SystemExit("nameplate does not fit its %.1f x %.1f mm pocket "
                         "even at the minimum scale" % (box_w, box_h))
    cx = (x0 + x1) / 2.0
    logo_h = TITLE_LOGO_H * k
    y = y0 + (box_h - h) / 2.0
    logo_at = (cx, y + logo_h / 2.0)
    y += logo_h + TITLE_LOGO_GAP * k
    rows = []
    for (txt, _s, gap), size in zip(TITLE_ROWS, sizes):
        rows.append((txt, cx, y + size * TEXT_BOX_RATIO / 2.0, 0,
                     round(size, 3)))
        y += size * TEXT_BOX_RATIO + gap * k
    return rows, logo_at, logo_h, k


_TITLE_TEXTS, TITLE_LOGO_AT, TITLE_LOGO_SIZE, TITLE_SCALE = _title_block()
if TITLE_SCALE < 1.0:
    print("nameplate scaled to %.0f%% to fit the free space at (%.1f, %.1f)"
          % (TITLE_SCALE * 100, TITLE_LOGO_AT[0], TITLE_LOGO_AT[1]))

# Free-standing silk GRAPHICS, as [(closed polyline in mm, stroke width mm)].
# Unlike the texts below these are not anchors: `silk.py` does not move a
# graphic, it routes labels around one, so what is written here is where it
# prints. The flame is the project's own mark, carried as an SVG path in
# `logo.py` rather than traced into a point table here.
SILK_GRAPHICS = [logo.flame(TITLE_LOGO_AT[0], TITLE_LOGO_AT[1],
                            TITLE_LOGO_SIZE)]

# ------------------------------------------ connector block legends
# The NAME of each user-wired connector block, printed beside that block.
#
# Neither half of this is hand-typed. The text comes from the part's own
# `value` in design.py, so a block's name has ONE source and can no longer
# drift from what the schematic calls it: these nine names and their nine
# Values were two independent tables, and four of them had already parted
# company. The anchor is derived from the real drawn body (`fp_body_box`),
# the way PIN_LEGENDS derives its standoff, so a name follows its part when
# the part moves. The bug that prevents is on this board's record - `SSR2`
# was once anchored at y=83.0, which is inside J4's courtyard rather than
# J9's, and printed against the wrong block.
#
# What stays here is the intent a derivation cannot know: which way out of
# the body the name goes, and how big it is.
#
# Not every connector gets one. J5/J6/J7 are 0.1" headers whose pin names say
# everything a block name would, and J11's `INPUTS` was dropped when its four
# screws each got a self-describing mark (see PIN_LEGENDS).
#
# The standoff from the drawn body to the centre of the name, mm - a WISH,
# and the only one here that another part can overrule. The four west-edge
# blocks are 1.76-2.6 mm apart body-to-body and a 0.9 mm name is 1.53 mm
# tall, so the standoff does not always fit: `block_legend()`
# measures the free span to the nearest part on that side and centres the
# name in it when the standoff would push it under the neighbour. This is
# not a nicety - at the standoff alone, `SSR2` overlapped J4's body by
# 0.31 mm and the fitted terminal block printed over it. Centred, it clears
# both blocks by 0.12 mm.
BLOCK_LEGEND_GAP = 1.3
# KiCad draws a text box 1.7x the glyph size. Used to ask whether a name
# fits a gap, so it is the same constant the nameplate's rows derive from.
BLOCK_TEXT_BOX = TEXT_BOX_RATIO


def _bl(side, size, shift=0.0, gap=BLOCK_LEGEND_GAP):
    """A BLOCK_LEGENDS entry. `shift` slides the name along its FREE axis."""
    return (side, size, shift, gap)


BLOCK_LEGENDS = {
    "J2": _bl("N", 0.9),
    # Both thermocouple blocks are named OUTSIDE the pair rather than in the
    # passive field west of them, which put `TC1` nearer R14/R15 than J3 and
    # `TC2` nearer C37/R37/R38 than J8. J3 and J8 are 0.74 mm apart and
    # nothing fits between them, so the stack reads from the outside in: TC1
    # in the band under H2, TC2 in the open board below J8.
    #
    # The shift is the one thing about them that is not centred, and it is
    # the same on both: x 113.08 is where the `J3`/`J8` designators sit, and
    # a legend aimed at a seated reference is the one that loses (see
    # RESET/BOOT in SILK).
    "J3": _bl("N", 0.9, shift=-3.25),
    "J8": _bl("S", 0.9, shift=-3.25),
    "J4": _bl("N", 0.9),
    "J9": _bl("N", 0.9),
    "J10": _bl("N", 0.9),
    "J12": _bl("N", 0.9),
    # 0.8: `AC SENSE DNP` is the longest name here on the smallest block.
    "J13": _bl("N", 0.8),
    # The one entry that asks for more than the standoff. J14's own
    # designator wants the gap directly above the connector, and this label
    # has the whole 5 mm band between J7 and J14 to sit in, so it gives way
    # rather than crowding the reference out of the one spot that is not the
    # connector body.
    "J14": _bl("N", 0.9, gap=3.6),
}
# The Value IS the name, with underscores read as spaces, unless an entry
# here says otherwise - and each exception is one for a reason.
BLOCK_LEGEND_NAME = {
    # `_K` says type-K in the schematic, where a thermocouple's alloy is a
    # real distinction. On the board there is one kind of thermocouple input
    # and its screws are already marked `K+`/`K-`.
    "J3": "TC1",
    "J8": "TC2",
    # The rail is AUX_VP and the block is an output bank. `AUX` beside a
    # terminal somebody wires does not say which way the current goes.
    "J10": "AUX OUT",
    # DNP = do not populate: the ADE7953's voltage channel (VP/VN),
    # deliberately unfitted because no mains touches this board. The header
    # exists so a future isolated AC accessory is a firmware change rather
    # than a respin. The dash of `AC SENSE - DNP` is dropped for the 1.6 mm
    # that keeps the name clear of C31's designator.
    "J13": "AC SENSE DNP",
    # The one connector whose name does not say what it speaks, at the bottom
    # edge beside the input terminal - the one place a wrong guess costs a
    # 3.3 V part. It is also the one connector with NO per-terminal legend
    # (PIN_LEGENDS): a 1 mm pitch takes no readable text, and the housing is
    # keyed, so there is nothing for a reader to get wrong.
    "J14": "QWIIC  I2C",
}
_BLOCK_EMITTED = set()


def _free_span(ref, side):
    """mm of empty board between `ref`'s drawn body and the nearest part.

    Measured only against parts that actually overlap `ref` across the
    label's own width, since a part off to one side is not what the name
    would collide with. Returns None when nothing is on that side.
    """
    x0, y0, x1, y1 = fp_body_box(COMPONENTS[ref])
    best = None
    for other, comp in COMPONENTS.items():
        if other == ref:
            continue
        b = fp_body_box(comp)
        if b is None:
            continue
        if side in ("N", "S"):
            if b[2] <= x0 or b[0] >= x1:
                continue
            d = y0 - b[3] if side == "N" else b[1] - y1
        else:
            if b[3] <= y0 or b[1] >= y1:
                continue
            d = x0 - b[2] if side == "W" else b[0] - x1
        if d >= 0 and (best is None or d < best):
            best = d
    return best


def block_legend(ref):
    """(text, x, y, rot, size) for one connector's own name."""
    side, size, shift, gap = BLOCK_LEGENDS[ref]
    txt = BLOCK_LEGEND_NAME.get(ref, COMPONENTS[ref]["value"].replace("_", " "))
    x0, y0, x1, y1 = fp_body_box(COMPONENTS[ref])
    # The standoff yields to the neighbour, never the other way round: a
    # wider gap keeps the name at the standoff (centring it in 18 mm of open
    # board would put it nowhere near the block it names), and only a gap too
    # tight to hold the box at the standoff re-centres it.
    half = size * BLOCK_TEXT_BOX / 2.0
    span = _free_span(ref, side)
    if span is not None and gap + half > span:
        gap = span / 2.0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    at = {"N": (cx + shift, y0 - gap), "S": (cx + shift, y1 + gap),
          "W": (x0 - gap, cy + shift), "E": (x1 + gap, cy + shift)}[side]
    _BLOCK_EMITTED.add(ref)
    return (txt, round(at[0], 3), round(at[1], 3), 0, size)


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
    # The two button legends, south of their buttons and level with each
    # other, because the buttons are now a pair (design.py SW1) instead of
    # being 55 mm apart. Both spent revisions printed across the button they
    # name - the one place a legend is guaranteed to be unreadable on a
    # finished board - because each was anchored in the 1.2-2.0 mm strip
    # between the switch and the board edge, and only SW2's strip was big
    # enough to hold anything.
    #
    # South, not north, even though north is a wider gap: north is where
    # `SW1`/`SW2` sit, and a board text cannot evict a seated reference. The
    # placer runs greedily over a live index, so a designator is an obstacle
    # from pass 1 and only moves if something makes IT move; `BOOT` spent two
    # rebuilds pinned to its button waiting for `SW2` to give way. Aim a
    # legend somewhere the designator is not.
    ("RESET", 91.0, 28.9, 0, 0.9),
    ("BOOT", 100.0, 28.9, 0, 0.9),
    # LED2 is the +3V3 power-on indicator (green, LEDP_K through R9 to GND).
    # It went unlabelled through rev B, which on a board with three other
    # LEDs is a guess. East rather than north: LED2's own silk starts 1.08 mm
    # below the edge clearance line and nothing legible fits there, but
    # removing `U.FL ANT ->` (an arrow pointing at a connector that is
    # already the only thing it could point at) freed the strip beside it.
    ("PWR", 58.0, 20.9, 0, 0.8),
    # Block NAMES only. What is on each individual screw is no longer spelled
    # out here as a "/"-separated list, because a horizontal list beside a
    # vertical stack of screws does not say which screw is which - it was the
    # largest single defect on the board's silk (analysis/silkscreen-review.md
    # §E). Every terminal now carries its own mark, generated beside its own
    # pad from PIN_LEGENDS below.
    #
    # Every one of them is generated: the name is the connector's own Value
    # and the anchor is its own drawn body. What each block asks for beyond
    # that lives in BLOCK_LEGENDS above, not here.
    block_legend("J2"),
    block_legend("J10"),
    block_legend("J4"),
    block_legend("J9"),
    # The two amber channel indicators. Each sits across its own terminal
    # pair through a 680R, so it lights only when that channel is driven AND
    # the watchdog rail is up - which is exactly the thing a person standing
    # at the kiln wants to read off the board.
    #
    # Above each LED, and the two anchors differ only in y now that LED3 and
    # LED4 share a column (design.py SSR_IND_X). `ON` rather than a bare
    # `SSR1`: that channel's test point is 4 mm east and its own generated
    # label already says `SSR1`, so the row reads `SSR1 ON` over the LED,
    # `SSR1` under the pad, and the two are about one thing.
    ("SSR1 ON", 57.0, 75.7, 0, 0.8),
    ("SSR2 ON", 57.0, 83.7, 0, 0.8),
    # The two thermocouple blocks, named in the gap OUTSIDE each block
    # rather than in the passive field west of it. (104, 31) and
    # (104, 58.5) put both names 5-9 mm from the terminal they belong to
    # and level with R14/R15 and R16/R17 instead, so `TC1` read as a
    # legend for whichever of the seven parts around it the reader
    # guessed - and `TC2` sat nearer C37/R37/R38 than J8. The north/south
    # split that fixes it is declared in BLOCK_LEGENDS above.
    block_legend("J3"),
    block_legend("J8"),
    # In the free band above J12 and centred on the block, which is what a
    # derived anchor gives for free. The hand-typed one was (96, 76): 6.5 mm
    # west of J12 with `AC SENSE - DNP` already in the same 1 mm of board, so
    # the placer took the far end of its ring - all 14 mm of it - and printed
    # the CT legend directly under `TC2  K+/K-`, 12.98 mm from the block it
    # names and 8.38 mm from the one it does not. J8's bottom is 55.59 and
    # J12's top is 74.17, so there is an 18 mm strip here and nothing else
    # wants it.
    block_legend("J12"),
    # J13's legend, and it has to be centred ON J13 to say so. At (100, 76)
    # it printed 1.30 mm from J13 but 0.37 mm from C35 and 0.77 mm from the
    # ADE7953, straight across that chip's own value text, so the one part it
    # was not obviously describing was the header. What it says, and why it
    # is not just the Value, is in BLOCK_LEGEND_NAME above.
    block_legend("J13"),
    # LED1's legend, and it follows LED1 (design.py). North of the LED: south
    # is D3, and further south is J5's pin-name row, where a stray word reads
    # as a fifteenth display pin - the mistake `SSR2` made from TP10 before
    # that test point moved.
    ("STATUS", 74.0, 84.0, 0, 0.9),
    # There is deliberately no `I2C` zone label. One used to sit over R44/R45
    # - correctly, after a move; it started life 6.1 mm from the parts it
    # named - and it was still the wrong label, because naming two pull-up
    # resistors tells a reader nothing they can act on. What it looked like
    # instead was a caption on the nameplate 3 mm above it. The bus is named
    # where a person actually meets it: `SDA`/`SCL` on J7's pin row and
    # `QWIIC  I2C` on J14.
    # J14's own label. Every other user-facing connector on an edge says what
    # it is - `5V IN`, `SSR1`, `TC1`, `IN1..GND` - and the Qwiic port arrived
    # at the bottom edge next to the input terminal with nothing but a
    # designator. See BLOCK_LEGENDS above for what it says and why it sits
    # further off its block than any other name here.
    block_legend("J14"),
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

# ------------------------------------------------ per-terminal pin legends
# One legend per pin, beside that pin's own pad, for every connector a person
# wires by hand.
#
# This is the fix for `analysis/silkscreen-review.md` §E, which was the
# board's largest silk defect and the only one that could cost a part or a
# finger. Every screw terminal on this board is rotated so its screws stack
# VERTICALLY, and every legend used to be a HORIZONTAL list beside them -
# `SSR1  5V / OUT`, `TC1  K+/K-`, `CT A+/A-/B+/B-`. Reading left to right
# tells a reader nothing about which screw is which; they had to find the
# block's pin-1 triangle and count. On the SSR blocks, which land beside
# mains-switched wiring, and on the CT block, that is the difference between
# a legend and a hint. J2's `+`/`-` were the only genuine per-terminal marks
# on the board, and they printed under the block.
#
# ref -> (side, size mm, (legend per pin, in pin order))
#
# `side` is which way out of the footprint the legends go, and it also
# decides which axis carries their MEANING - see the lock below. Everything
# else is derived: the pad centres come from the real footprint geometry
# (pad_centres) and the standoff from the real drawn body (fp_body_box), so
# nothing here is a coordinate anyone has to maintain when a part moves.
#
# J13 and J14 deliberately have none. J13 is a DNP 0.1" pair, and J14 is a
# keyed 1 mm Qwiic housing - a pitch that takes no readable text and a
# connector a user cannot insert wrongly.
J5_PINS = ("5V", "GND", "CS", "RST", "DC", "SDI", "SCK", "BL",
           "SDO", "TCK", "TCS", "TDI", "TDO", "IRQ")
J6_PINS = ("UP", "DN", "LT", "RT", "OK", "G")
J7_PINS = ("3V3", "GND", "TX", "RX", "SDA", "SCL", "3V3", "GND")
PIN_LEGENDS = {
    # west-edge screw terminals, legends in the interior strip east of them
    "J2": ("E", 1.0, ("+", "-")),
    # J10 pin 1 is AUX_VP, the externally supplied coil rail the ULN2003
    # commons to - an INPUT on a block named `AUX OUT`, which is exactly the
    # terminal a reader would otherwise guess wrong. `V+` says supply; the
    # three switched low sides are just numbered.
    "J10": ("E", 0.8, ("V+", "1", "2", "3")),
    # Both SSR blocks are "+5V (watchdog-gated) and the switched low side",
    # so the pin order is worth naming: hook the SSR's control + to `5V` and
    # its - to `OUT`.
    "J4": ("E", 0.8, ("5V", "OUT")),
    "J9": ("E", 0.8, ("5V", "OUT")),
    # east-edge screw terminals, legends in the interior strip west of them
    "J3": ("W", 0.8, ("K+", "K-")),
    "J8": ("W", 0.8, ("K+", "K-")),
    "J12": ("W", 0.8, ("A+", "A-", "B+", "B-")),
    # J11's screws stack horizontally, so its legends go north, one per
    # screw. `IN1/IN2/IN3` rather than `1/2/3` because those are the names
    # the firmware, docs/pin-assignments.md and the Kconfig options use.
    # There is no separate `INPUTS` block name any more - it does not fit
    # (see the note on the standoff below) and four self-describing marks
    # make it redundant.
    "J11": ("N", 0.8, ("IN1", "IN2", "IN3", "GND")),
    # 0.1" headers: pin names north of the body, as before.
    "J5": ("N", 0.8, J5_PINS),
    "J6": ("N", 0.8, J6_PINS),
    "J7": ("N", 0.8, J7_PINS),
}
# Standoff from the connector's drawn body to the centre of its legend, mm.
# 1.3 reproduces every position these labels were hand-authored at before
# they were derived, and is a wish rather than an instruction: the legend is
# locked to its pad on the axis that identifies the terminal and free on the
# other, so `silk.py` slides it along the standoff as far as it has to. J11's
# do exactly that - it faces the J5/J6/J7 row across a 1.69 mm gap, which
# fits a 0.8 legend and nothing else, and the placer centres them in it.
PIN_LEGEND_GAP = 1.3
# Which axis a legend may NOT be moved along, per side. On a vertical stack
# of screws it is y that says which screw; on a horizontal pin row it is x.
# Slide it along that axis and the label does not merely look ragged, it
# names the wrong terminal - so `silk.py` treats this as a hard constraint,
# not a weight, and `kicad_build.py` fails the build if one ends up off its
# axis. The bug this prevents is on the board today: J7's `SDA` and `3V3`
# were pushed a full 2.60 mm - more than a pin pitch - onto the connector
# body, because the placer's only defence was a 4x cost (`W_LATERAL`) and it
# had guessed the axis from the text's reading direction, which is right for
# a pin row and backwards for a screw stack.
_LEGEND_LOCK = {"E": "y", "W": "y", "N": "x", "S": "x"}


def _pin_legends():
    """[(text, x, y, rot, size, lock)] for every PIN_LEGENDS entry."""
    out = []
    for ref in sorted(PIN_LEGENDS, key=lambda r: (r[0], int(r[1:]))):
        side, size, names = PIN_LEGENDS[ref]
        pads = pad_centres(ref)
        x0, y0, x1, y1 = fp_body_box(COMPONENTS[ref])
        for k, txt in enumerate(names):
            px, py = pads[str(k + 1)]
            if side == "E":
                at = (x1 + PIN_LEGEND_GAP, py)
            elif side == "W":
                at = (x0 - PIN_LEGEND_GAP, py)
            elif side == "N":
                at = (px, y0 - PIN_LEGEND_GAP)
            else:
                at = (px, y1 + PIN_LEGEND_GAP)
            out.append((txt, at[0], at[1], 0, size, _LEGEND_LOCK[side]))
    return out

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
                    "CTB_P": "CT B+", "CTB_N": "CT B-",
                    # The rule would print WDT_CT_P verbatim: CT is not a bus
                    # prefix and P is not a function suffix, and adding either
                    # to those tables would collide with the current-transformer
                    # nets above. What a probe here reads is the watchdog's
                    # timing capacitor, so say that.
                    "WDT_CT_P": "WDT RC"}


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


# Below the pad, for every test point, with no exceptions - which is worth a
# note because there used to be one. TP10 sat at (44.5, 94.15), boxed in by
# C11's and R39's designators with its only clear spot 1.2 mm above J5's
# pin-name row and in line with its `SDO`/`TCK` pins, where `SSR2` read as a
# fifteenth pin on the display header. The override that pushed it above the
# pad was a workaround for the placement; TP10 has since moved to sit beside
# LED4 in the SSR readout row (design.py SSR_TP_X), where below the pad is
# simply empty. Prefer moving the part.
TP_LABEL_AT = {}

for _tp in sorted((r for r in COMPONENTS
                   if r.startswith("TP") and r[2:].isdigit()), key=_tp_num):
    _x, _y, _r = COMPONENTS[_tp]["at"]
    # Anchored just below the pad: the reference designator sits above it by
    # library default, so the two share the test point without a fight.
    _at = TP_LABEL_AT.get(_tp, (_x, _y + 1.7))
    SILK.append((tp_label(COMPONENTS[_tp]["pins"]["1"]), _at[0], _at[1], 0, 0.8))

SILK += _pin_legends()
# Every entry is (text, x, y, rot, size, lock) from here on. `lock` is None
# for the hand-authored legends above - a zone label may be moved wherever it
# reads best - and an axis name for the generated per-terminal ones, which
# may not. Normalising here rather than writing None into ninety tuples keeps
# the table above about intent.
SILK = [e if len(e) == 6 else (e + (None,)) for e in SILK]
# A block legend declared and never printed is a name nobody sees, and the
# table above is the only place it would be visible. Fail rather than ship a
# connector whose name exists only in a dict.
assert _BLOCK_EMITTED == set(BLOCK_LEGENDS), (
    "connector block legends declared but not in SILK: %s"
    % sorted(set(BLOCK_LEGENDS) - _BLOCK_EMITTED))


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
    # Copper types come from COPPER_LAYER_TYPE so the emitted text and
    # kicad_build.apply_layer_types() cannot disagree; see that table.
    for lid, lname, ltype, ualias in [
            (0, "F.Cu", COPPER_LAYER_TYPE["F.Cu"], None),
            (4, "In1.Cu", COPPER_LAYER_TYPE["In1.Cu"], None),
            (6, "In2.Cu", COPPER_LAYER_TYPE["In2.Cu"], None),
            (2, "B.Cu", COPPER_LAYER_TYPE["B.Cu"], None),
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
    for k, (txt, x, y, rot, size, _lock) in enumerate(SILK):
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
