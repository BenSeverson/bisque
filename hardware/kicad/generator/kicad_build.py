"""Build bisque-controller.kicad_pcb through KiCad's own engine (pcbnew API).

Loads the real system-library footprints, places them per design.py,
routes with router.py (obstacle model taken from the *loaded* pad
geometry, so it always matches the libraries actually used), then lets
KiCad do the rest: `kicad-cli pcb drc --refill-zones` fills the ground
pours and runs KiCad's real DRC. The saved board is a genuine
pcbnew-written file. Requires KiCad 10+.

Usage: python3 kicad_build.py <out.kicad_pcb>
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
try:
    # macOS: pcbnew's settings manager needs a live wx app in standalone use
    import wx
    _wx_app = wx.App(False)
    if hasattr(wx, "DisableAsserts"):
        wx.DisableAsserts()
except ImportError:
    pass
import pcbnew
from canonicalize import canonicalize_file
from design import COMPONENTS, netlist, BX0, BY0, BX1, BY1
import router as R
from gen_pcb import (all_seeds, route_all, ripup_retry, promoted_order, plane_vias,
                     SILK, MANUAL_VIAS, PLANE_LAYER)

# Copper stack-up. Rev B is 4-layer (spec 6.1): signals on the outside, an
# unbroken GND plane on In1.Cu and the +3V3 plane on In2.Cu. router.py still
# knows only two routing layers - 0 and 1 - and they map to F.Cu and B.Cu; the
# inner layers carry no tracks at all, only the plane fills, so the router
# never needs to model them. Vias stay through-hole, which is what lets a pad
# reach either plane with a single hole.
COPPER_LAYERS = 4
LAYER = {0: pcbnew.F_Cu, 1: pcbnew.B_Cu}
PLANE_CU = {"In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu}


def _find_fp_base():
    cand = [os.environ.get("KICAD_FOOTPRINT_DIR", "")]
    cand += ["/usr/share/kicad/footprints",
             "/usr/local/share/kicad/footprints",
             "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
             r"C:\Program Files\KiCad\10.0\share\kicad\footprints"]
    import glob as _g
    cand += sorted(_g.glob("/usr/share/kicad*/footprints"), reverse=True)
    for c in cand:
        if c and os.path.isdir(c):
            return c
    sys.exit("KiCad footprint libraries not found - set KICAD_FOOTPRINT_DIR")


import glob
FPBASE = _find_fp_base()


def load_footprint(lib, name):
    path = os.path.join(FPBASE, lib + ".pretty")
    mgr = pcbnew.PCB_IO_MGR
    return mgr.FindPlugin(mgr.KICAD_SEXP).FootprintLoad(path, name)
MM = pcbnew.FromMM
_major = int(pcbnew.Version().split(".")[0])
if _major < 10:
    sys.exit("kicad_build.py requires KiCad 10+ (found %s)" % pcbnew.Version())


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


# 3D-model offsets, in mm, for models whose own origin does not sit where the
# footprint expects. Cosmetic only - models are never part of a fab output -
# but a model at the wrong origin renders the part floating off the board,
# which reads as a layout error rather than a missing file.
#
# U1: KiCad 10 ships ESP32-S3-WROOM-1.step and -WROOM-2.step but NOT
# -WROOM-1U.step, so this board uses Espressif's official model
# (github.com/espressif/kicad-libraries). Its origin is a body CORNER - the
# body spans X 0..18, Y 0..19.2 mm, measured off the STEP directly - while
# KiCad's footprint origin is the body CENTRE.
#
# Two independent derivations agree on -9.6:
#   * body centre from the STEP bounding box = (9.0, 9.6) -> offset (-9, -9.6)
#   * Espressif's own footprint uses (offset -9 -9.75 0), and their footprint
#     origin differs from KiCad's by exactly dY -0.15 mm (verified across all
#     40 signal pads, dX 0.0) -> -9.75 + 0.15 = -9.60
MODEL_OFFSET = {"U1": (-9.0, -9.6, 0.0)}


def build_board():
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(COPPER_LAYERS)
    bds = board.GetDesignSettings()
    bds.m_TrackMinWidth = MM(0.2)
    bds.m_ViasMinSize = MM(0.5)
    bds.m_MinThroughDrill = MM(0.3)
    bds.m_CopperEdgeClearance = MM(0.3)

    # Title block. The schematic has carried one since rev A; the board did
    # not, so every page of the exported board PDF showed a blank Title and
    # Rev - on six pages that otherwise look nearly identical, since four
    # copper layers of the same outline are hard to tell apart at a glance.
    # Values mirror gen_sch.py's block so the two documents agree. The date is
    # deliberately FIXED, not today's: check_canonical.py requires rebuilds to
    # be byte-identical, and a live date would break that every midnight.
    tb = board.GetTitleBlock()
    tb.SetTitle("Bisque Kiln Controller")
    tb.SetDate("2026-07-20")
    tb.SetRevision("B")
    tb.SetCompany("Bisque project")
    tb.SetComment(0, "ESP32-S3-WROOM-1U-N16R2 + 2x MAX31856 + dual SSR + ADE7953")
    tb.SetComment(1, "4-layer, 100 x 100 mm, JLCPCB standard process")
    board.SetTitleBlock(tb)

    # nets
    nets = {}
    for name in sorted(netlist()):
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        nets[name] = n

    # footprints
    fps = {}
    for ref, c in COMPONENTS.items():
        lib, name = c["fp"].split(":", 1)
        fp = load_footprint(lib, name)
        assert fp is not None, c["fp"]
        fx, fy, frot = c["at"]
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPosition(V(fx, fy))
        fp.SetOrientationDegrees(frot)
        for pad in fp.Pads():
            num = str(pad.GetNumber())
            net = c["pins"].get(num)
            if net:
                pad.SetNet(nets[net])
            # library EP thermal vias use 0.2mm drills; upsize to 0.3mm so
            # the whole board stays inside JLCPCB's standard drill range
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                d = pad.GetDrillSize().x
                if 0 < d < MM(0.3):
                    pad.SetDrillSize(pcbnew.VECTOR2I(MM(0.3), MM(0.3)))
            # solid pour connection where thermals starve (module GND/EP,
            # USB shell) — these want maximum copper anyway
            if (ref == "U1" and num in ("1", "40", "41")) or \
               (ref == "J1" and num in ("A1", "B1", "A12", "B12", "S1")):
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        off = MODEL_OFFSET.get(ref)
        if off:
            # fp.Models() hands back COPIES - mutating them writes nothing
            # back to the footprint. Rebuild the entry instead.
            old = [(m.m_Filename, m.m_Scale, m.m_Rotation) for m in fp.Models()]
            assert old, "%s: MODEL_OFFSET set but footprint has no 3D model" % ref
            fp.Models().clear()
            for fname, scale, rot in old:
                nm = pcbnew.FP_3DMODEL()
                nm.m_Filename = fname
                nm.m_Scale = scale
                nm.m_Rotation = rot
                nm.m_Offset = pcbnew.VECTOR3D(*off)
                fp.Models().push_back(nm)
        board.Add(fp)
        fps[ref] = fp
    # tidy silk: smaller refs everywhere, relocate the ones that collide
    for ref, fp in fps.items():
        t = fp.Reference()
        t.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
        t.SetTextThickness(MM(0.12))
    # refs whose default (footprint-relative) position collides with a
    # neighbour's silk or lands on top of another part
    for ref, (x, y) in {"J5": (22.6, 99.6), "J6": (60.6, 99.6),
                        "J7": (78.6, 99.6), "J11": (62.6, 107.0),
                        "J2": (22.0, 34.0), "J10": (22.0, 47.0),
                        "J4": (22.0, 70.5), "J9": (22.0, 83.0),
                        "J3": (110.0, 33.0), "J8": (110.0, 45.0),
                        "J12": (110.0, 62.5), "J1": (41.0, 22.0),
                        "BZ1": (48.0, 61.0), "Y1": (96.0, 88.0),
                        "H1": (30.5, 25.0), "H2": (110.5, 25.0),
                        "H3": (30.5, 115.0), "H4": (110.5, 115.0),
                        }.items():
        fps[ref].Reference().SetPosition(V(x, y))
    return board, nets, fps


def build_router_model(board, fps):
    r = R.Router(BX0, BY0, BX1, BY1)
    # Antenna keepout, if the module footprint carries one. The WROOM-1U does
    # NOT - that is the point of the swap (spec 2.1): the 48 x 7 mm band the
    # WROOM-1's PCB antenna reserved is reclaimed for parts and pour, and rev
    # B places USB-C, the reset switch and three test points in it. There is
    # deliberately no computed fallback: inventing a keepout for a module that
    # has none would bar tracks from a third of the digital band.
    for z in fps["U1"].Zones():
        if z.GetIsRuleArea():
            bb = z.GetBoundingBox()
            r.add_keepout(pcbnew.ToMM(bb.GetLeft()), BY0,
                          pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
    pad_pos = {}
    for ref, fp in fps.items():
        c = COMPONENTS[ref]
        for pad in fp.Pads():
            ls = pad.GetLayerSet()
            on_f = ls.Contains(pcbnew.F_Cu)
            on_b = ls.Contains(pcbnew.B_Cu)
            if not (on_f or on_b):
                continue
            layers = tuple([l for l, on in ((0, on_f), (1, on_b)) if on])
            bb = pad.GetBoundingBox()
            cx = pcbnew.ToMM(bb.GetCenter().x)
            cy = pcbnew.ToMM(bb.GetCenter().y)
            w = pcbnew.ToMM(bb.GetWidth())
            h = pcbnew.ToMM(bb.GetHeight())
            num = str(pad.GetNumber())
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or num == "":
                net = None
            else:
                net = c["pins"].get(num)
                if net is None:
                    net = "__nc_%s_%s" % (ref, num)
            # Hole geometry is not pad geometry. A slot drill (the USB-C
            # shield's `(drill oval 0.6 1.7)`) has a diameter AND a length,
            # and its centre is the pad's position, not the copper bounding
            # box centre — those differ whenever the pad has an offset. Both
            # distinctions matter to hole-to-hole clearance and neither
            # survives collapsing the drill to GetDrillSize().x.
            drill = drill_len = 0.0
            drill_ang = 0.0
            hole = None
            if pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,
                                      pcbnew.PAD_ATTRIB_NPTH):
                ds = pad.GetDrillSize()
                dw, dh = pcbnew.ToMM(ds.x), pcbnew.ToMM(ds.y)
                drill, drill_len = min(dw, dh), max(dw, dh)
                drill_ang = pad.GetOrientationDegrees() + (0.0 if dw >= dh else 90.0)
                hole = (pcbnew.ToMM(pad.GetPosition().x),
                        pcbnew.ToMM(pad.GetPosition().y))
            r.add_pad(net, layers, cx, cy, w, h,
                      circle=pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE,
                      drill=drill, drill_len=drill_len, drill_ang=drill_ang,
                      hole=hole)
            if num:
                pad_pos.setdefault((ref, num), []).append((cx, cy, layers, w * h))
    return r, pad_pos


def add_copper(board, nets, r):
    for s in r.result_tracks:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(s.x1, s.y1))
        t.SetEnd(V(s.x2, s.y2))
        t.SetWidth(MM(s.w))
        t.SetLayer(LAYER[s.layer])
        t.SetNet(nets[s.net])
        board.Add(t)
    for (net, x, y, _fixed) in r.result_vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(V(x, y))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(MM(R.VIA_DRILL))
        v.SetWidth(MM(R.VIA_DIA))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(nets[net])
        board.Add(v)


def add_outline_and_silk(board):
    corners = [(BX0, BY0), (BX1, BY0), (BX1, BY1), (BX0, BY1)]
    for k in range(4):
        a, b = corners[k], corners[(k + 1) % 4]
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
        sh.SetStart(V(*a))
        sh.SetEnd(V(*b))
        sh.SetLayer(pcbnew.Edge_Cuts)
        sh.SetWidth(MM(0.1))
        board.Add(sh)
    for (txt, x, y, rot, size) in SILK:
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetPosition(V(x, y))
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        t.SetTextThickness(MM(max(0.1, size * 0.15)))
        t.SetTextAngleDegrees(rot)
        board.Add(t)


def add_zones(board, nets):
    """The two inner planes.

    There is deliberately no pour on F.Cu or B.Cu. Rev A poured GND on both
    signal layers, which on rev B's density was the single largest consumer of
    routing space on exactly the two layers the boxed-in signals needed; with
    GND on In1 and +3V3 on In2 the outer layers are signals only.
    """
    m = 0.5
    for netname, layername in sorted(PLANE_LAYER.items()):
        z = pcbnew.ZONE(board)
        z.SetLayer(PLANE_CU[layername])
        z.SetNet(nets[netname])
        ol = z.Outline()
        ol.NewOutline()
        for (x, y) in [(BX0 + m, BY0 + m), (BX1 - m, BY0 + m),
                       (BX1 - m, BY1 - m), (BX0 + m, BY1 - m)]:
            ol.Append(MM(x), MM(y))
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.2))
        z.SetThermalReliefGap(MM(0.3))
        z.SetThermalReliefSpokeWidth(MM(0.4))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        board.Add(z)

    # No rule area. Rev B carved a four-layer pour keepout across the SSR
    # optocoupler row so the planes could not short around the barrier; the
    # optos were reverted to direct low-side MOSFET drive (design.py's SSR
    # block), so nothing needs the pour kept out and both planes run whole.


def plane_islands(board):
    """[(layer, area_mm2, x, y), ...] for every plane island beyond the
    largest one on its layer.

    A plane is one sheet of copper only until enough antipads line up to cut
    it. Nothing can bridge a severed island back - there is no second copper
    layer carrying the same net to via across to - so this is a report, not a
    repair: it names the layer and the spot so the fix goes into placement.
    KiCad's own DRC reports the same thing as an unconnected zone, but only
    when a pad happens to sit on the stranded piece.
    """
    out = []
    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        layer = z.GetLayer()
        polys = z.GetFilledPolysList(layer)
        areas = []
        for i in range(polys.OutlineCount()):
            ol = polys.Outline(i)
            bb = ol.BBox()
            areas.append((abs(ol.Area()) / 1e12,
                          pcbnew.ToMM(bb.GetCenter().x),
                          pcbnew.ToMM(bb.GetCenter().y)))
        for (area, cx, cy) in sorted(areas, reverse=True)[1:]:
            out.append((board.GetLayerName(layer), area, cx, cy))
    return out


def summarize(rpt_path):
    import re
    report = open(rpt_path).read()
    counts = dict(re.findall(r"\*\* Found (\d+) (\w[\w ]*?) \*\*", report))
    for key, v in counts.items():
        print("  %s: %s" % (v, key.strip()) if False else "  %s: %s" % (key.strip(), v))
    return counts


def build_copper(board, fps, order):
    """One complete routing attempt. Returns (router, failed-net list)."""
    r, pad_pos = build_router_model(board, fps)
    seed_list, stub_terms = all_seeds(pad_pos)
    for (net, layer, pts, w) in seed_list:
        for a, b in zip(pts, pts[1:]):
            r.add_seg(net, layer, a[0], a[1], b[0], b[1], w, fixed=True)
    for (net, x, y) in MANUAL_VIAS:
        r.add_via(net, x, y, fixed=True)
    # Plane vias first: they are not optional (a missing one is an unconnected
    # pad) and they are short, so they claim their spots while the board is
    # empty and the signal router threads what is left.
    pv, pv_fail = plane_vias(r, pad_pos, seed_list)
    print("  plane vias: %d (%d unplaceable)" % (len(pv), len(pv_fail)))
    failed = route_all(r, pad_pos, seed_list, stub_terms, order=order,
                       verbose=False)
    if failed:
        failed = ripup_retry(r, failed, pad_pos, stub_terms)
    failed = failed + pv_fail
    r._memo = {}
    r._memo_net = None
    print("  mitred %d right-angle corners" % r.miter_corners())
    return r, failed


def route_board(board, fps, passes=6):
    """Route, promoting whatever failed and trying again.

    router.py is greedy and never rips up, so a failed net failed because
    something routed earlier took the one lane out of its pocket. Re-running
    with the failures at the head of the order is the cheapest rip-up
    available: the blocking net gets re-routed around them, and being the
    longer of the two it usually has somewhere else to go. Iterate until
    nothing fails or the failure set stops shrinking, and keep the best
    attempt - promotion can trade one failure for another, and the loop must
    not end on a worse board than it has already seen.
    """
    promoted = []
    best = None
    for attempt in range(passes):
        order = promoted_order(promoted) if promoted else None
        print("routing pass %d (%d promoted)..." % (attempt + 1, len(promoted)))
        r, failed = build_copper(board, fps, order)
        print("  pass %d: %d net(s) unrouted%s"
              % (attempt + 1, len(failed),
                 (": " + ", ".join(failed)) if failed else ""))
        if best is None or len(failed) < len(best[1]):
            best = (r, failed)
        if not failed:
            break
        new = [n for n in failed if n not in promoted]
        if not new:
            break                      # promoting these has stopped helping
        promoted = promoted + new
    return best


def main(out):
    out = os.path.abspath(out)
    board, nets, fps = build_board()
    r, failed = route_board(board, fps)
    if failed:
        print("UNROUTED: %s" % ", ".join(failed))
    add_copper(board, nets, r)
    add_outline_and_silk(board)
    add_zones(board, nets)
    rpt_path = os.path.splitext(out)[0] + "-drc.rpt"
    # standalone python fill/DRC needs a project-attached board; kicad-cli
    # fills, saves and checks in one authentic pass.
    import subprocess
    board.SetFileName(out)
    pcbnew.SaveBoard(out, board)
    # Every write goes through canonicalize_file: pcbnew hands each item a
    # random uuid and then orders the file by it, so without this an
    # unchanged design lands on disk differently every run (#234). Doing it
    # after *each* write - not just at the end - matters, because the zone
    # fill is only reproducible if kicad-cli is handed a reproducible board.
    canonicalize_file(out)
    print("saved %s (unfilled); fill+DRC via kicad-cli..." % out)
    subprocess.run(["kicad-cli", "pcb", "drc", "--refill-zones",
                    "--save-board", "--severity-all",
                    "--all-track-errors", "-o", rpt_path, out],
                   check=True, capture_output=True)
    canonicalize_file(out)
    for (lname, area, cx, cy) in plane_islands(pcbnew.LoadBoard(out)):
        print("  !! %s plane island of %.1f mm2 stranded at (%.1f, %.1f)"
              % (lname, area, cx, cy))
    print("KiCad DRC report -> %s" % rpt_path)
    summarize(rpt_path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
