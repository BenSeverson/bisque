"""Build bisque-controller.kicad_pcb through KiCad's own engine (pcbnew API).

Loads the real system-library footprints, places them per design.py,
routes with router.py (obstacle model taken from the *loaded* pad
geometry, so it always matches the libraries actually used), then lets
KiCad do the rest: ZONE_FILLER fills the ground pours and
WriteDRCReport runs KiCad's real DRC. The saved board is a genuine
pcbnew-written file (KiCad 7 format, opens in KiCad 7/8/9).

Usage: python3 kicad_build.py <out.kicad_pcb>
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import pcbnew
from design import COMPONENTS, netlist, BX0, BY0, BX1, BY1
import router as R
from gen_pcb import (USB_SEEDS, USB_STUB_TERMS, ROUTE_ORDER, route_all,
                     stitch_vias, SILK, MANUAL_VIAS)

FPBASE = "/usr/share/kicad/footprints"
MM = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def build_board():
    board = pcbnew.BOARD()
    bds = board.GetDesignSettings()
    bds.m_TrackMinWidth = MM(0.2)
    bds.m_ViasMinSize = MM(0.5)
    bds.m_MinThroughDrill = MM(0.3)
    bds.m_CopperEdgeClearance = MM(0.3)

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
        fp = pcbnew.FootprintLoad(os.path.join(FPBASE, lib + ".pretty"), name)
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
                pad.SetZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        board.Add(fp)
        fps[ref] = fp
    # tidy silk: smaller refs everywhere, relocate the ones that collide
    for ref, fp in fps.items():
        t = fp.Reference()
        t.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
        t.SetTextThickness(MM(0.12))
    for ref, (x, y) in {"J5": (26.5, 90.6), "J6": (47.8, 90.6),
                        "J7": (65.5, 90.6), "LED1": (69.8, 89.3),
                        "U3": (104.5, 57.4), "C9": (105.3, 69.5),
                        "J3": (110.6, 71.6), "SW1": (51.5, 25.0),
                        "H1": (29.3, 24.5)}.items():
        fps[ref].Reference().SetPosition(V(x, y))
    return board, nets, fps


def build_router_model(board, fps):
    r = R.Router(BX0, BY0, BX1, BY1)
    # antenna keepout: from U1's embedded rule areas (fall back to computed)
    u1 = fps["U1"]
    got_keepout = False
    for z in u1.Zones():
        if z.GetIsRuleArea():
            bb = z.GetBoundingBox()
            r.add_keepout(pcbnew.ToMM(bb.GetLeft()), BY0,
                          pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
            got_keepout = True
    if not got_keepout:
        fx, fy, _ = COMPONENTS["U1"]["at"]
        r.add_keepout(fx - 24, BY0, fx + 24, fy - 6.8)
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
            drill = pcbnew.ToMM(pad.GetDrillSize().x) \
                if pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,
                                          pcbnew.PAD_ATTRIB_NPTH) else 0.0
            r.add_pad(net, layers, cx, cy, w, h,
                      circle=pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE,
                      drill=drill)
            if num:
                pad_pos.setdefault((ref, num), []).append((cx, cy, layers, w * h))
    return r, pad_pos


def add_copper(board, nets, r):
    LAYER = {0: pcbnew.F_Cu, 1: pcbnew.B_Cu}
    for s in r.result_tracks:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(s.x1, s.y1))
        t.SetEnd(V(s.x2, s.y2))
        t.SetWidth(MM(s.w))
        t.SetLayer(LAYER[s.layer])
        t.SetNet(nets[s.net])
        board.Add(t)
    for (net, x, y) in r.result_vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(V(x, y))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(MM(R.VIA_DRILL))
        v.SetWidth(MM(R.VIA_DIA))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(nets[net])
        board.Add(v)


def route_gnd_stubs(r, pad_pos, stitches):
    """Give every SMD-only GND pad a real track to the nearest GND anchor
    (stitch via or plated GND hole), so no pad depends on a pour sliver."""
    anchors = list(stitches)
    tht = []
    for (ref, pin), plist in pad_pos.items():
        if COMPONENTS[ref]["pins"].get(pin) != "GND":
            continue
        for (x, y, layers, area) in plist:
            if len(layers) == 2:
                tht.append((x, y))
    anchors += tht
    extra = [(x, y, l) for (x, y) in anchors for l in (0, 1)]
    fails = 0
    for (ref, pin), plist in sorted(pad_pos.items()):
        if COMPONENTS[ref]["pins"].get(pin) != "GND":
            continue
        for (x, y, layers, area) in plist:
            if len(layers) == 2:
                continue  # THT already an anchor
            if any(s.net == "GND" and
                   min(abs(s.x1 - x) + abs(s.y1 - y),
                       abs(s.x2 - x) + abs(s.y2 - y)) < 0.3
                   for s in r.result_tracks):
                continue  # a seed already lands on this pad
            try:
                r.route("GND", [(anchors[0][0], anchors[0][1], (0, 1)),
                                (x, y, layers)], 0.3, extra_srcs=extra)
                extra.append((x, y, layers[0]))
            except RuntimeError:
                fails += 1
                print("  !! GND stub failed for %s.%s" % (ref, pin))
    return fails


def add_stitching(board, nets, stitches):
    for (x, y) in stitches:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(V(x, y))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(MM(R.VIA_DRILL))
        v.SetWidth(MM(R.VIA_DIA))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(nets["GND"])
        v.SetIsFree(True)
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
    m = 0.5
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(nets["GND"])
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
    # KiCad 7 standalone quirk: ZONE_FILLER needs a DRC engine bound to the
    # board; a throwaway WriteDRCReport creates one.
    pcbnew.WriteDRCReport(board, "/tmp/_prefill-drc.rpt",
                          pcbnew.EDA_UNITS_MILLIMETRES, False)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())


def heal_islands(board, nets, r, rounds=3):
    """Stitch any isolated GND pour island that lacks a via, then refill."""
    LNAME = {pcbnew.F_Cu: 0, pcbnew.B_Cu: 1}
    total = 0
    for _ in range(rounds):
        added = 0
        via_pts = [(pcbnew.ToMM(v.GetPosition().x), pcbnew.ToMM(v.GetPosition().y))
                   for v in board.Tracks() if v.Type() == pcbnew.PCB_VIA_T]
        tht_pts = []
        for fp in board.Footprints():
            for pad in fp.Pads():
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and \
                   pad.GetNetname() == "GND":
                    tht_pts.append((pcbnew.ToMM(pad.GetPosition().x),
                                    pcbnew.ToMM(pad.GetPosition().y)))
        anchors = via_pts + tht_pts
        for z in board.Zones():
            if z.GetIsRuleArea() or z.GetNetname() != "GND":
                continue
            layer = z.GetLayer()
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                ol = polys.Outline(i)
                if any(ol.PointInside(pcbnew.VECTOR2I(MM(x), MM(y)))
                       for (x, y) in anchors):
                    continue
                # island without any layer-bridging anchor: find a via spot
                bb = ol.BBox()
                x0, y0 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop())
                x1, y1 = pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())
                placed = False
                yy = y0 + 0.4
                while yy < y1 and not placed:
                    xx = x0 + 0.4
                    while xx < x1 and not placed:
                        if ol.PointInside(pcbnew.VECTOR2I(MM(xx), MM(yy))):
                            i2, j2 = r.snap(xx, yy)
                            r._begin("GND-heal%d" % total)
                            if r.via_ok("GND", i2, j2):
                                cx, cy = r.cell_xy(i2, j2)
                                r.add_via("GND", cx, cy, record=False)
                                v = pcbnew.PCB_VIA(board)
                                v.SetPosition(V(cx, cy))
                                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                                v.SetDrill(MM(R.VIA_DRILL))
                                v.SetWidth(MM(R.VIA_DIA))
                                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                                v.SetNet(nets["GND"])
                                v.SetIsFree(True)
                                board.Add(v)
                                placed = True
                                added += 1
                                total += 1
                        xx += 0.4
                    yy += 0.4
                if not placed:
                    print("  !! island at (%.1f,%.1f)-(%.1f,%.1f) on %s: no via spot"
                          % (x0, y0, x1, y1, "F" if layer == pcbnew.F_Cu else "B"))
        if not added:
            break
        pcbnew.WriteDRCReport(board, "/tmp/_prefill-drc.rpt",
                              pcbnew.EDA_UNITS_MILLIMETRES, False)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    return total


def run_drc(board, path):
    ok = pcbnew.WriteDRCReport(board, path, pcbnew.EDA_UNITS_MILLIMETRES, True)
    report = open(path).read()
    import re
    counts = dict(re.findall(r"\*\* Found (\d+) (\w[\w ]*?) \*\*", report))
    # parse violation blocks: "[type]: description" lines with severity
    errs = re.findall(r"\[(\w+)\]: ([^\n]+)\n\s+(?:Local override; )?[Ee]rror",
                      report)
    sev_err = [l for l in report.splitlines() if "; error" in l or "Severity: error" in l]
    return report, counts


def main(out):
    board, nets, fps = build_board()
    r, pad_pos = build_router_model(board, fps)
    for (net, layer, pts, w) in USB_SEEDS:
        for a, b in zip(pts, pts[1:]):
            r.add_seg(net, layer, a[0], a[1], b[0], b[1], w)
    for (net, x, y) in MANUAL_VIAS:
        r.add_via(net, x, y)
    print("routing (obstacles from pcbnew pad geometry)...")
    route_all(r, pad_pos)
    stitches = stitch_vias(r)
    print("stitch vias: %d" % len(stitches))
    route_gnd_stubs(r, pad_pos, stitches)
    r._memo = {}
    r._memo_net = None
    print("mitred %d right-angle corners" % r.miter_corners())
    add_copper(board, nets, r)
    add_stitching(board, nets, stitches)
    add_outline_and_silk(board)
    print("filling zones with pcbnew.ZONE_FILLER...")
    add_zones(board, nets)
    healed = heal_islands(board, nets, r)
    print("healed %d isolated pour islands" % healed)
    board.SetFileName(os.path.abspath(out))
    pcbnew.SaveBoard(os.path.abspath(out), board)
    print("saved %s" % out)
    rpt_path = os.path.splitext(out)[0] + "-drc.rpt"
    report, counts = run_drc(board, rpt_path)
    print("KiCad DRC report -> %s" % rpt_path)
    for k, v in counts.items():
        print("  %s: %s" % (k.strip(), v))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
