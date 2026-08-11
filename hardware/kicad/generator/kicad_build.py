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
from gen_pcb import (all_seeds, ROUTE_ORDER, route_all, stitch_vias, SILK,
                     MANUAL_VIAS)

# Opto-isolation barrier (spec 6.2). The band spans the west edge from just
# above J4 to just below J9 and stops short of the optocouplers' input pins, so
# every scrap of isolated copper - J4/J9 and U8/U9 pins 3 and 4 - sits inside
# it and no GND pour reaches within ~5 mm of any of it. Placement and this
# rectangle move together; see the router keepout in build_router_model().
ISO_BARRIER = (20.0, 71.0, 40.8, 95.5)
ISO_NETS = ("SSR1_A", "SSR1_B", "SSR2_A", "SSR2_B")


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
                        "U8": (38.5, 73.0), "U9": (38.5, 85.0),
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
    # Opto-isolation barrier - the same rectangle add_zones() carves out of the
    # pour. Only the isolated nets may route through it.
    r.add_keepout(*ISO_BARRIER, allow_nets=ISO_NETS)
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

    # Opto-isolation barrier: no GND copper on either layer across the SSR
    # opto row, or the pour shorts around the barrier the optos exist to make.
    # A rule area (not a zone) - _gnd_islands() skips these by design.
    ka = pcbnew.ZONE(board)
    ka.SetIsRuleArea(True)
    # Forbid the pour and NOTHING else. A rule area's restrictions apply to
    # every item in the band, including the isolated copper the band exists to
    # protect - switching vias off here made KiCad flag J4/J9's own pads and
    # U8/U9 pins 3-4 as "items not allowed". Keeping GND vias out of the band
    # is the *router's* job instead (see ISO_BARRIER in build_router_model),
    # which can exempt the isolated nets by name; a rule area cannot.
    ka.SetDoNotAllowZoneFills(True)
    ka.SetDoNotAllowTracks(False)
    ka.SetDoNotAllowVias(False)
    ka.SetDoNotAllowPads(False)
    ka.SetDoNotAllowFootprints(False)
    # LSET's python binding takes no list/LSEQ in KiCad 10; AllCuMask(2) is
    # exactly F.Cu + B.Cu on this 2-layer stack.
    ka.SetLayerSet(pcbnew.LSET.AllCuMask(2))
    ol = ka.Outline()
    ol.NewOutline()
    bx0, by0, bx1, by1 = ISO_BARRIER
    for (x, y) in [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]:
        ol.Append(MM(x), MM(y))
    board.Add(ka)
    return


def _gnd_islands(board):
    """{(layer, index): filled outline} for every GND pour island."""
    isl = {}
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        layer = z.GetLayer()
        polys = z.GetFilledPolysList(layer)
        for i in range(polys.OutlineCount()):
            isl[(layer, i)] = polys.Outline(i)
    return isl


def _gnd_bridges(board):
    """Points where GND crosses between layers: vias and plated GND pads."""
    pts = [(pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y))
           for t in board.Tracks()
           if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND"]
    for fp in board.Footprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and \
               pad.GetNetname() == "GND":
                pts.append((pcbnew.ToMM(pad.GetPosition().x),
                            pcbnew.ToMM(pad.GetPosition().y)))
    return pts


def _island_components(isl, bridges):
    """Union-find over islands linked by a layer-bridging GND point.
    Returns [[key, ...], ...], largest total copper area first."""
    def at(layer, x, y):
        p = pcbnew.VECTOR2I(MM(x), MM(y))
        for key, ol in isl.items():
            if key[0] == layer and ol.PointInside(p):
                return key
        return None

    parent = {k: k for k in isl}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for (x, y) in bridges:
        f, b = at(pcbnew.F_Cu, x, y), at(pcbnew.B_Cu, x, y)
        if f and b:
            ra, rb = find(f), find(b)
            if ra != rb:
                parent[ra] = rb

    groups = {}
    for k in isl:
        groups.setdefault(find(k), []).append(k)
    return sorted(groups.values(),
                  key=lambda g: -sum(abs(isl[k].Area()) for k in g))


def heal_islands(board, nets, r, rounds=1):
    """Tie stranded GND pour copper back to the main pour with a via.

    Two distinct failure modes, both healed here:

      1. An island with no layer-bridging anchor at all.
      2. A *group* of islands that bridge to each other but never reach the
         main pour — e.g. F.Cu island -> via -> B.Cu island -> via -> back to
         the same F.Cu island. Every island in such a group has a via, so the
         original "does this island contain any anchor?" test declared them
         all healthy while KiCad reported "Missing connection between
         Zone [GND] and Zone [GND]" and heal_islands printed "healed 0".

    Modelling it as connectivity components covers both: anything outside the
    largest component needs a via placed where it overlaps the main component
    on the opposite layer. The caller refills the zones (kicad-cli
    --refill-zones) and calls again until DRC reports no unconnected items.
    """
    total = 0
    for _ in range(rounds):
        isl = _gnd_islands(board)
        comps = _island_components(isl, _gnd_bridges(board))
        if len(comps) < 2:
            break
        main = set(comps[0])
        added = 0
        for group in comps[1:]:
            placed = False
            for key in sorted(group, key=lambda k: -abs(isl[k].Area())):
                layer, _idx = key
                other = pcbnew.B_Cu if layer == pcbnew.F_Cu else pcbnew.F_Cu
                targets = [isl[k] for k in main if k[0] == other]
                ol = isl[key]
                bb = ol.BBox()
                x0, y0 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop())
                x1, y1 = pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())
                yy = y0 + 0.4
                while yy < y1 and not placed:
                    xx = x0 + 0.4
                    while xx < x1 and not placed:
                        p = pcbnew.VECTOR2I(MM(xx), MM(yy))
                        # must land in this island *and* in main-component
                        # copper on the other layer, or the via bridges
                        # nothing useful
                        if ol.PointInside(p) and \
                           any(t.PointInside(p) for t in targets):
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
                                v.SetNet(board.FindNet("GND"))
                                v.SetIsFree(True)
                                board.Add(v)
                                print("  bridged stranded GND island to the "
                                      "main pour at (%.1f, %.1f)" % (cx, cy))
                                placed = True
                                added += 1
                                total += 1
                        xx += 0.4
                    yy += 0.4
                if placed:
                    break
            if not placed:
                area = sum(abs(isl[k].Area()) for k in group) / 1e12
                print("  !! %.1f mm2 of GND pour (%d island(s)) is stranded "
                      "and no legal via spot bridges it" % (area, len(group)))
        if not added:
            break
    return total


def drop_disconnected_stitch_vias(board, rpt_path):
    """Remove any free GND via that KiCad's post-fill DRC reports as not
    actually touching copper on one of its layers.

    stitch_vias()/heal_islands() place vias on a coarse grid, checked
    against the router's own (approximate) obstacle model rather than
    KiCad's real zone-fill polygons; a via can land just inside a
    clearance gap the real fill carves out around a nearby track,
    leaving it isolated on one layer. heal_islands() doesn't catch this
    - it only bridges pour islands that have *no* via touching them at
    all, which is a different failure mode.

    This is only ever safe because GND is never point-to-point routed
    (see the "missing = ... - {'GND'}" assert in route_all): every GND
    via is a decorative stitching via added by this build script, not a
    connection some component depends on. Dropping one just means one
    fewer plane-tying via at that spot; the surrounding pour and its
    other stitching vias still carry the net. A real signal via being
    unconnected would be a genuine routing bug and must not be silently
    dropped - this only ever touches free vias on the GND net.
    """
    import re
    rpt = open(rpt_path).read()
    coords = set()
    for m in re.finditer(
            r"\[unconnected_items\].*?(?=\n\[|\n\*\*|\Z)", rpt, re.S):
        block = m.group(0)
        for vm in re.finditer(
                r"@\(([\d.]+) mm, ([\d.]+) mm\): Via \[(\S+)\] on", block):
            x, y, net = vm.groups()
            if net == "GND":
                coords.add((round(float(x), 3), round(float(y), 3)))
    removed = 0
    for via in [t for t in board.Tracks() if t.Type() == pcbnew.PCB_VIA_T]:
        if not via.GetIsFree() or via.GetNetname() != "GND":
            continue
        vx, vy = pcbnew.ToMM(via.GetPosition().x), pcbnew.ToMM(via.GetPosition().y)
        if (round(vx, 3), round(vy, 3)) in coords:
            board.Remove(via)
            removed += 1
            print("  dropped disconnected GND stitch via at (%.1f, %.1f)" % (vx, vy))
    return removed


def summarize(rpt_path):
    import re
    report = open(rpt_path).read()
    counts = dict(re.findall(r"\*\* Found (\d+) (\w[\w ]*?) \*\*", report))
    for key, v in counts.items():
        print("  %s: %s" % (v, key.strip()) if False else "  %s: %s" % (key.strip(), v))
    return counts


def main(out):
    out = os.path.abspath(out)
    board, nets, fps = build_board()
    r, pad_pos = build_router_model(board, fps)
    seed_list, stub_terms = all_seeds(pad_pos)
    for (net, layer, pts, w) in seed_list:
        for a, b in zip(pts, pts[1:]):
            r.add_seg(net, layer, a[0], a[1], b[0], b[1], w)
    for (net, x, y) in MANUAL_VIAS:
        r.add_via(net, x, y)
    print("routing (obstacles from pcbnew pad geometry)...")
    route_all(r, pad_pos, seed_list, stub_terms)
    stitches = stitch_vias(r)
    print("stitch vias: %d" % len(stitches))
    route_gnd_stubs(r, pad_pos, stitches)
    r._memo = {}
    r._memo_net = None
    print("mitred %d right-angle corners" % r.miter_corners())
    add_copper(board, nets, r)
    add_stitching(board, nets, stitches)
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
    for round_no in range(4):
        subprocess.run(["kicad-cli", "pcb", "drc", "--refill-zones",
                        "--save-board", "--severity-all",
                        "--all-track-errors", "-o", rpt_path, out],
                       check=True, capture_output=True)
        canonicalize_file(out)
        rpt = open(rpt_path).read()
        import re
        m = re.search(r"\*\* Found (\d+) unconnected", rpt)
        unconnected = int(m.group(1)) if m else 0
        if unconnected == 0:
            break
        print("  %d unconnected after fill; healing islands..." % unconnected)
        b2 = pcbnew.LoadBoard(out)
        healed = heal_islands(b2, None, r)
        print("  healed %d islands" % healed)
        dropped = drop_disconnected_stitch_vias(b2, rpt_path)
        if dropped:
            print("  dropped %d disconnected stitch via(s)" % dropped)
        pcbnew.SaveBoard(out, b2)
        canonicalize_file(out)
        if healed == 0 and dropped == 0:
            break
    print("KiCad DRC report -> %s" % rpt_path)
    summarize(rpt_path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
