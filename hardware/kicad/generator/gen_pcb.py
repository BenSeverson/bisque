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
    """Yield (padname, kind, gx, gy, eff_w, eff_h, circle, layers) for each pad."""
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
        if kind in ("thru_hole", "np_thru_hole"):
            layers = (0, 1)
        else:
            layers = (0,)
        yield (str(name), kind, gx, gy, w, h, circle, layers)


def build_router():
    r = R.Router(BX0, BY0, BX1, BY1)
    # antenna keepout from U1 placement
    fx, fy, _ = COMPONENTS["U1"]["at"]
    r.add_keepout(fx - 24, BY0, fx + 24, fy - 6.8)
    pad_pos = {}
    for ref, c in COMPONENTS.items():
        for (name, kind, gx, gy, w, h, circle, layers) in pad_geometry(c):
            if kind == "np_thru_hole" or name == "":
                net = None
            else:
                net = c["pins"].get(name)
                if net is None:
                    net = "__nc_%s_%s" % (ref, name)
            r.add_pad(net, layers, gx, gy, w, h, circle)
            if name:
                pad_pos.setdefault((ref, name), []).append((gx, gy, layers, w * h))
    return r, pad_pos


# Pre-seeded copper: USB escape stubs (0.5 mm pitch pads) and the +3V3
# under-module corridor (exits over pad 40 through the antenna-side lane so
# the right pad column keeps its escape rows).
USB_SEEDS = [  # (net, layer, [(x,y)...], width)
    ("+3V3", 0, [(79.25, 29.01), (95.5, 29.01), (95.5, 26.8), (103.4, 26.8),
                 (103.4, 34.05)], 0.5),
    ("USB_DN", 0, [(88.25, 91.56), (88.25, 92.8), (89.25, 92.8), (89.25, 91.56)], 0.25),
    ("USB_DN", 0, [(88.25, 91.56), (88.25, 89.6), (88.4, 89.6)], 0.25),
    ("USB_DP", 0, [(88.75, 91.56), (88.75, 90.3), (89.75, 90.3), (89.75, 91.56)], 0.25),
    ("USB_DP", 0, [(89.75, 90.3), (89.75, 89.6), (89.6, 89.6)], 0.25),
    ("CC1", 0, [(87.75, 91.56), (87.75, 89.6), (87.6, 89.6)], 0.25),
    ("CC2", 0, [(90.75, 91.56), (90.75, 89.6), (90.8, 89.6)], 0.25),
    ("VBUS", 0, [(91.45, 91.56), (91.45, 89.6), (91.6, 89.6)], 0.4),
    ("VBUS", 0, [(86.55, 91.56), (86.55, 90.0), (86.4, 90.0)], 0.4),
]
# nets whose J1 pads are replaced by stub terminals (ends grid-aligned)
USB_STUB_TERMS = {
    "USB_DN": [(88.4, 89.6, (0,))],
    "USB_DP": [(89.6, 89.6, (0,))],
    "CC1": [(87.6, 89.6, (0,))],
    "CC2": [(90.8, 89.6, (0,))],
    "VBUS": [(91.6, 89.6, (0,)), (86.4, 90.0, (0,))],
}

ROUTE_ORDER = [
    ("VIN", 0.8), ("+5V", 0.7), ("+3V3", 0.7), ("VLED", 0.5), ("VBUS", 0.4),
    ("LEDP_K", 0.3), ("LEDS_K", 0.3), ("SSR_GATE", 0.3), ("SSR_OUT", 0.6),
    ("BUZZ_GATE", 0.3), ("BUZZ_K", 0.5), ("WS_DIN", 0.3), ("TC_P", 0.4),
    ("CC1", 0.25), ("CC2", 0.25), ("USB_DN", 0.25), ("USB_DP", 0.25),
    ("EN", 0.3), ("IO0", 0.3),
    # bottom-row escapes, west -> east so outer pads grab outer lanes
    ("LCD_CS", 0.3), ("LCD_BL", 0.3), ("LCD_RST", 0.3), ("LCD_DC", 0.3),
    ("TC_CS", 0.3), ("SPI_MOSI", 0.3), ("SPI_SCLK", 0.3), ("SPI_MISO", 0.3),
    ("VENT", 0.3), ("LID_SW", 0.3), ("LED_DATA", 0.3),
    # west-column escapes, south -> north (first net hugs the column, the
    # rest pass above its start row and take the next lane west)
    ("SSR_CTRL", 0.3), ("AUX_B", 0.3), ("AUX_A", 0.3), ("ALARM", 0.3),
    ("BTN_LEFT", 0.3), ("BTN_DOWN", 0.3), ("BTN_UP", 0.3),
    # right-column escapes, south -> north
    ("RXD0", 0.3), ("TXD0", 0.3), ("BTN_RIGHT", 0.3), ("BTN_SEL", 0.3),
]


def route_all(r, pad_pos):
    nl = netlist()
    routed = set()
    for net, width in ROUTE_ORDER:
        pins = nl[net]
        terms = []
        for (ref, pin) in pins:
            if ref == "J1" and net in USB_STUB_TERMS:
                continue
            for (gx, gy, layers, area) in pad_pos[(ref, pin)]:
                terms.append((gx, gy, layers, area))
        # dedupe identical positions, sort largest pad first (THT seeds)
        seen = {}
        for t in terms:
            seen.setdefault((round(t[0], 3), round(t[1], 3)), t)
        terms = sorted(seen.values(), key=lambda t: -t[3])
        terms = [(t[0], t[1], t[2]) for t in terms]
        if net in USB_STUB_TERMS:
            terms = USB_STUB_TERMS[net] + terms
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
    step = 7.0
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


SILK = [
    ("BISQUE KILN CONTROLLER v1.0", 66, 68, 0, 1.5),
    ("ANTENNA - KEEP CLEAR", 88, 23.2, 0, 1.2),
    ("5V IN", 23.2, 27.5, 0, 1.0),
    ("+", 31.5, 33, 0, 1.2), ("-", 31.5, 38, 0, 1.5),
    ("SSR", 23.0, 49.5, 0, 1.0),
    ("+", 31.5, 55, 0, 1.2), ("-", 31.5, 60, 0, 1.5),
    ("TC  K+", 116.5, 60, 90, 1.0), ("K-", 116.5, 68.5, 90, 1.0),
    ("DISPLAY", 33.5, 90.6, 0, 1.0),
    ("NAV", 52.3, 90.6, 0, 1.0),
    ("AUX", 72.9, 90.6, 0, 1.0),
    ("RESET", 58.2, 25, 0, 0.9),
    ("BOOT", 104.2, 49.7, 0, 0.9),
    ("USB", 96.5, 93.5, 0, 0.9),
    ("STATUS", 75, 89.8, 0, 0.9),
]
J5_PINS = ["3V3", "GND", "CS", "RST", "DC", "SDI", "SCK", "BL"]
J6_PINS = ["UP", "DN", "LT", "RT", "OK", "G"]
J7_PINS = ["3V3", "GND", "TX", "RX", "VNT", "LID", "A15", "A16"]
for hdr, names in (("J5", J5_PINS), ("J6", J6_PINS), ("J7", J7_PINS)):
    hx = COMPONENTS[hdr]["at"][0]
    for k, t in enumerate(names):
        SILK.append((t, hx + 2.54 * k, 99.05, 270, 0.7))


def main(dst):
    r, pad_pos = build_router()
    for (net, layer, pts, w) in USB_SEEDS:
        for a, b in zip(pts, pts[1:]):
            r.add_seg(net, layer, a[0], a[1], b[0], b[1], w)
    print("routing...")
    route_all(r, pad_pos)
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
