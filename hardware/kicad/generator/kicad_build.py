"""Build bisque-controller.kicad_pcb through KiCad's own engine (pcbnew API).

Loads the real system-library footprints, places them per design.py,
routes with router.py (obstacle model taken from the *loaded* pad
geometry, so it always matches the libraries actually used), then lets
KiCad do the rest: `kicad-cli pcb drc --refill-zones` fills the ground
pours and runs KiCad's real DRC. The saved board is a genuine
pcbnew-written file. Requires KiCad 10+.

Usage: python3 kicad_build.py [--no-route] <out.kicad_pcb>

`--no-route` is the fast path. Routing 93 nets across 141 parts is ~91%
of the 158 s a full build costs, and several classes of change cannot
touch copper at all: silkscreen placement (silk.py), 3D model offsets
(MODEL_FIXUP), the title block, reference-designator text metrics. With
`--no-route` the tracks, vias and filled zones are read back off the
existing board and everything else is re-derived by the same code a full
build runs, so the result is byte-identical for the same design.py -
`check_fast_path.py` proves that rather than assuming it. Anything that
moves a part, changes connectivity, or changes a routing parameter needs
the full path; `verify_reusable()` below refuses the fast one when
design.py and the loaded board have drifted apart.
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
from gen_sch import sync_project
import router as R
import silk
from gen_pcb import (all_seeds, route_all, ripup_retry, promoted_order, plane_vias,
                     apply_stackup, SILK, SILK_GRAPHICS, MANUAL_VIAS,
                     PLANE_LAYER, HIDE_REFS)

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


MM = pcbnew.FromMM

# Minimum silkscreen stroke, mm. JLCPCB quotes 0.153 mm as the floor below
# which a legend line may print blurred or drop out entirely. 0.16 rather than
# KiCad's 0.15 house value on purpose: 0.15 is 2.4 um UNDER the quoted number,
# which is finer than a screen resolves and would almost certainly print, but
# "under the published figure by less than anyone can measure" is a sentence
# nobody should have to reconstruct while reading a DFM report. 0.16 is over
# it, and it was free - the placer seats all 204 labels with 0 silk-on-silk at
# either value, so there was no trade to make.
#
# Both silk TEXT sites clamp here; see the two uses. Footprint OUTLINES are a
# separate population and are deliberately NOT clamped: they arrive at 0.12 mm
# from KiCad's own stock libraries (all 37 of ours), which is what every KiCad
# board ships and what JLCPCB prints daily. Raising them would mean rewriting
# the vendored .kicad_mod files and would grow every obstacle box the placer
# works against, to thicken a part outline nobody reads during assembly. The
# text is what gets read, so the text is what is held to the floor.
SILK_MIN_STROKE = 0.16

_major = int(pcbnew.Version().split(".")[0])
if _major < 10:
    sys.exit("kicad_build.py requires KiCad 10+ (found %s)" % pcbnew.Version())

# The footprint reader, resolved once. Belt-and-braces against the swig
# type-table corruption `strip_derived()` documents: while a live pcbnew
# session is in that state, PCB_IO_MGR.FindPlugin() is one of the calls that
# hands back an untyped pointer - here, one with no FootprintLoad on it. A
# handle taken before any board is loaded keeps working.
_FP_PLUGIN = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)


def load_footprint(lib, name):
    path = os.path.join(FPBASE, lib + ".pretty")
    return _FP_PLUGIN.FootprintLoad(path, name)


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


# 3D models. Cosmetic only - no fab output (gerbers, drill, BOM, CPL, DRC)
# touches a model at all - but the renders in 3d/ are how placement and silk
# get eyeballed without a board in hand, so a part that renders as bare pads
# or floats off its footprint costs real time to diagnose.
#
# Five footprints need help. KiCad 10 ships NO model for four of them, and its
# failure mode is silence: `kicad-cli pcb render` exits 0, prints "Loading 3D
# models...", and omits the part. That is why every model this board depends on
# is vendored into 3dmodels/ and referenced through ${KIPRJMOD} rather than
# ${KICAD10_3DMODEL_DIR} - the system path is not reproducible (a KiCad upgrade
# wipes a hand-installed file, and a fresh clone never had one), and the whole
# point of a committed render is that a clean machine can reproduce it.
#
# `file` is a stem in 3dmodels/; see that directory's README for provenance.
# `offset` is mm in the footprint frame, `rotate` degrees about X/Y/Z.
#
# U1 - Espressif's own STEP is authored with its origin at a body CORNER (body
# spans X 0..18, Y 0..19.2 mm, measured off the STEP) while KiCad's footprint
# origin is the body CENTRE. Two independent derivations agree on -9.6:
#   * body centre from the STEP bounding box = (9.0, 9.6) -> offset (-9, -9.6)
#   * Espressif's own footprint uses (offset -9 -9.75 0), and their footprint
#     origin differs from KiCad's by exactly dY -0.15 mm (verified across all
#     40 signal pads, dX 0.0) -> -9.75 + 0.15 = -9.60
#
# J1 - the only one of the four LCSC models needing a correction. Unrotated,
# the shell sits ~8.9 mm north of its pads, which reads as a translation but is
# not one: EasyEDA stores a per-model display rotation next to the geometry
# (the SVGNODE's c_rotation, "0,0,180" for this part) and the STEP is authored
# in the unrotated frame. Applying it puts all 12 pins on the 12 signal pads
# with the mouth facing the board edge. C515890's c_rotation is "0,0,90" and is
# deliberately NOT applied - a square QFN is invariant under it, so it would be
# an untestable claim; C318884's is "0,0,0".
MODEL_FIXUP = {
    "U1": dict(file="ESP32-S3-WROOM-1U", offset=(-9.0, -9.6, 0.0)),
    "J1": dict(file="USB_C_Receptacle_HRO_TYPE-C-31-M-12", rotate=(0, 0, 180)),
    "U7": dict(file="QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm"),
    "SW1": dict(file="SW_Push_1P1T_XKB_TS-1187A"),
    "SW2": dict(file="SW_Push_1P1T_XKB_TS-1187A"),
}
MODEL_DIR = "${KIPRJMOD}/3dmodels/%s.step"


def build_board(existing=None):
    """Everything about the board except copper.

    `existing` is an already-routed board that `strip_derived()` has just
    emptied of footprints and board graphics; it keeps its tracks, vias and
    filled zones and gets the rest rebuilt here. Passing it through the same
    function as a fresh build - rather than a separate "patch the loaded
    board" routine - is what makes `--no-route` byte-identical by
    construction instead of by inspection.
    """
    board = pcbnew.BOARD() if existing is None else existing
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
    # A fresh TITLE_BLOCK rather than board.GetTitleBlock(): on a board that
    # came off disk the getter hands back an untyped swig pointer with no
    # methods on it. Building one here also means every field is set from
    # this table, so `--no-route` cannot inherit a stale one.
    tb = pcbnew.TITLE_BLOCK()
    tb.SetTitle("Bisque Kiln Controller")
    tb.SetDate("2026-07-20")
    tb.SetRevision("B")
    tb.SetCompany("Bisque project")
    tb.SetComment(0, "ESP32-S3-WROOM-1U-N16R2 + 2x MAX31856 + dual SSR + ADE7953")
    tb.SetComment(1, "4-layer, 100 x 100 mm, JLCPCB standard process")
    board.SetTitleBlock(tb)

    # nets. A .kicad_pcb of this vintage carries no net table - tracks, vias
    # and zones name their net inline - so a reused board already has every
    # net the copper on it mentions, and re-minting them would orphan that
    # copper. Net *codes* are internal only and never reach the file.
    nets = {}
    for name in sorted(netlist()):
        n = board.FindNet(name) if existing is not None else None
        if n is None:
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
        fix = MODEL_FIXUP.get(ref)
        if fix:
            # fp.Models() hands back COPIES - mutating them writes nothing
            # back to the footprint. Rebuild the entry instead.
            #
            # The scale and rotation are unpacked to plain floats HERE rather
            # than carried as VECTOR3Ds. `m` is a temporary, and `m.m_Scale`
            # is a reference into it, so holding that reference past the
            # comprehension leaves it dangling: whether it still reads (1,1,1)
            # or has become (0,0,0) depends on when Python happens to collect
            # the temporary. A model scaled to zero renders nothing at all,
            # and it made the board file differ between two runs of an
            # unchanged design - a determinism bug that only showed up once
            # the fast path changed the allocation pattern around it.
            old = [((m.m_Scale.x, m.m_Scale.y, m.m_Scale.z),
                    (m.m_Rotation.x, m.m_Rotation.y, m.m_Rotation.z))
                   for m in fp.Models()]
            # Every ref here names a footprint the library ships a <model>
            # entry for, even when it ships no file to back it. Rebuilding a
            # missing entry from nothing would work, but losing one is a
            # library change worth hearing about rather than papering over.
            assert old, "%s: MODEL_FIXUP set but footprint has no 3D model" % ref
            fp.Models().clear()
            for scale, rot in old:
                nm = pcbnew.FP_3DMODEL()
                nm.m_Filename = MODEL_DIR % fix["file"]
                nm.m_Scale = pcbnew.VECTOR3D(*scale)
                nm.m_Rotation = pcbnew.VECTOR3D(*fix.get("rotate", rot))
                nm.m_Offset = pcbnew.VECTOR3D(*fix.get("offset", (0.0, 0.0, 0.0)))
                fp.Models().push_back(nm)
        board.Add(fp)
        fps[ref] = fp
    # Silk: one size for every reference designator. WHERE each one lands is
    # not decided here - `silk.py` derives it after the board texts exist (see
    # add_outline_and_silk). Rev B carried a hand-maintained list of 18 refs
    # nudged out of collisions at this point; at 141 parts a patch list cannot
    # keep up, and it didn't - DRC reported 109 silkscreen violations across
    # 49 designators.
    #
    # SILK_MIN_STROKE is a fab floor, not a taste setting. JLCPCB's published
    # legend capability is 0.153 mm minimum stroke and 0.8 mm minimum height;
    # below either, the line is documented as possibly blurred or dropped
    # outright. These labels are load-bearing rather than decorative - the 13
    # through-hole parts on `jlcpcb/hand-solder-parts.csv` are fitted by hand
    # against them after the board comes back - so an illegible designator is
    # a functional defect. The stroke used to be 0.12 mm, 0.033 mm UNDER the
    # floor.
    #
    # The HEIGHT stays at 0.8 mm, which meets the minimum exactly, and the
    # 0.1875 stroke ratio that gives is bolder than KiCad's 0.15 convention.
    # That is deliberate, and taking it to 0.9 mm for a prettier 1:6 ratio was
    # tried and reverted: `silk.py` is a greedy placer over a live index, so
    # making all 141 designators 12.5% taller does not just cost those labels
    # room - it reorders who wins which gap board-wide. The one casualty was
    # the `INPUTS 1 / 2 / 3 / GND` legend, which lost its 1.82 mm slot between
    # the J6/J7 header row (F.Fab bottom y=106.93) and J11 (F.Fab top
    # y=108.75) and printed across the terminal block it names. Nothing was
    # wrong with the anchor; a neighbour simply got there first. Stroke width
    # was the actual fab defect, so stroke width is all that changed.
    for ref, fp in fps.items():
        t = fp.Reference()
        t.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
        t.SetTextThickness(MM(SILK_MIN_STROKE))
        # The designator is not the only text a footprint can put on silk.
        # Two here arrive from the stock libraries at 1.0/0.15 - under the
        # floor by the same 2.4 um the constant above declines to ship - and
        # neither this loop nor the SILK table would otherwise reach them,
        # which would leave "every silk text clears the floor" true only of
        # the text we author. Clamp, never shrink: LED1's pin-1 mark and BZ1's
        # `+` are deliberately bolder than the floor in their own libraries.
        for it in list(fp.GraphicalItems()) + [fp.Value()]:
            if it.GetLayer() == pcbnew.F_SilkS and hasattr(it, "GetText"):
                if it.GetTextThickness() < MM(SILK_MIN_STROKE):
                    it.SetTextThickness(MM(SILK_MIN_STROKE))
        # Hidden, not deleted: the field still exists, so the netlist, the
        # BOM and the CPL are untouched and DRC still knows what it is - it
        # simply is not printed. `silk.py` and `check_silk.py` both skip an
        # invisible reference already, so this also hands the placer back the
        # four corners those labels were competing for.
        if ref in HIDE_REFS:
            t.SetVisible(False)
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
    anchors = []
    for (txt, x, y, rot, size) in SILK:
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetPosition(V(x, y))
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        # The 0.15 ratio is KiCad's own stroke-to-height convention and the
        # nameplate rows depend on it, but the floor underneath it has to be
        # the fab's, not a round number: at the 0.8 mm size most of the SILK
        # table uses, size * 0.15 is 0.12 mm - well under JLCPCB's 0.153 mm
        # legend minimum, and the old 0.1 mm floor was lower still, so it
        # never bit. Clamping at SILK_MIN_STROKE leaves every row above
        # 1.0 mm untouched (they already derive more than the floor) and
        # lifts only the small legends that were under it.
        t.SetTextThickness(MM(max(SILK_MIN_STROKE, size * 0.15)))
        t.SetTextAngleDegrees(rot)
        board.Add(t)
        anchors.append((t, x, y))
    # Silk graphics are placed, not anchored, so none of these go into
    # `anchors`: `silk.place()` has nothing to move them to. It does have to
    # SEE them - board-level F.SilkS drawings are in its obstacle set for
    # exactly this reason, or the nameplate's flame would be the one thing on
    # the board a reference designator could legally print through.
    for pts, width in SILK_GRAPHICS:
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_POLY)
        sh.SetLayer(pcbnew.F_SilkS)
        sh.SetPolyPoints([V(x, y) for x, y in pts])
        sh.SetFilled(False)
        sh.SetWidth(MM(width))
        board.Add(sh)
    return anchors


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


def verify_reusable(board):
    """Refuse `--no-route` when design.py and the loaded board have drifted.

    The fast path is only sound while the copper it inherits is the copper a
    full build would produce. Nothing here can prove that outright, but every
    input the router reads out of design.py *can* be compared against what the
    board actually has, and a mismatch on any of them means the inherited
    routing belongs to a different design. A stale fast path that quietly
    emits a plausible-but-wrong board is worse than no fast path at all, so
    this exits rather than warns.

    Deliberately not checked: `value` and the SILK text table, both of which
    the fast path genuinely re-derives, and router.py's own parameters, which
    are not recorded on the board. Changing those needs the full path and the
    docs say so.
    """
    bad = []
    seen = {}
    for fp in board.GetFootprints():
        seen.setdefault(fp.GetReference(), []).append(fp)
    for ref in sorted(r for r, v in seen.items() if len(v) > 1):
        bad.append("%s: %d footprints share this reference" % (ref, len(seen[ref])))
    for ref in sorted(set(COMPONENTS) - set(seen)):
        bad.append("%s: in design.py, absent from the board" % ref)
    for ref in sorted(set(seen) - set(COMPONENTS)):
        bad.append("%s: on the board, absent from design.py" % ref)

    for ref in sorted(set(COMPONENTS) & set(seen)):
        c = COMPONENTS[ref]
        fp = seen[ref][0]
        # The board's footprints were loaded through the plugin directly, so
        # they carry the bare footprint name with no library nickname.
        want_fp = c["fp"].split(":", 1)[1]
        if fp.GetFPID().GetUniStringLibItemName() != want_fp:
            bad.append("%s: footprint is %s, design.py says %s"
                       % (ref, fp.GetFPID().GetUniStringLibItemName(), want_fp))
        x, y, rot = c["at"]
        p = fp.GetPosition()
        if abs(pcbnew.ToMM(p.x) - x) > 1e-4 or abs(pcbnew.ToMM(p.y) - y) > 1e-4:
            bad.append("%s: at (%.3f, %.3f), design.py says (%.3f, %.3f)"
                       % (ref, pcbnew.ToMM(p.x), pcbnew.ToMM(p.y), x, y))
        if abs((fp.GetOrientationDegrees() - rot + 180.0) % 360.0 - 180.0) > 1e-4:
            bad.append("%s: rotated %.2f deg, design.py says %.2f"
                       % (ref, fp.GetOrientationDegrees(), rot))
        for pad in fp.Pads():
            num = str(pad.GetNumber())
            want = c["pins"].get(num)
            have = pad.GetNetname()
            if want and have != want:
                bad.append("%s pad %s: net %s, design.py says %s"
                           % (ref, num, have or "<none>", want))

    have_nets = set(str(k) for k in board.GetNetsByName().keys()) - {""}
    want_nets = set(netlist())
    for n in sorted(want_nets - have_nets):
        bad.append("net %s: in design.py, absent from the board" % n)
    for n in sorted(have_nets - want_nets):
        bad.append("net %s: on the board, absent from design.py" % n)

    # MANUAL_VIAS are hand-placed copper, so an edit to that table is a
    # copper edit even though it lives beside the cosmetic tables.
    vias = set()
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            vias.add((t.GetNetname(), round(pcbnew.ToMM(t.GetPosition().x), 3),
                      round(pcbnew.ToMM(t.GetPosition().y), 3)))
    for (net, x, y) in MANUAL_VIAS:
        if (net, round(x, 3), round(y, 3)) not in vias:
            bad.append("MANUAL_VIAS %s at (%.3f, %.3f): no such via on the board"
                       % (net, x, y))

    if bad:
        sys.stderr.write(
            "--no-route refused: the loaded board is not this design.\n"
            "%d mismatch(es); the first few:\n" % len(bad))
        for line in bad[:12]:
            sys.stderr.write("  %s\n" % line)
        if len(bad) > 12:
            sys.stderr.write("  ... and %d more\n" % (len(bad) - 12))
        sys.exit("Run a full build (make pcb-build) - this change moves copper.")


_REMOVED = []


def strip_derived(board):
    """Delete everything `--no-route` re-derives; keep the routing.

    Footprints and board graphics are removed outright rather than edited
    back to a default state. `silk.place()` has already moved every reference
    designator and every board text on the loaded board, so re-running the
    placer over it would be scoring its own previous output instead of the
    inputs a fresh build gives it. Re-adding the library footprints is the
    only reset that is exactly the fresh build's starting state, because it
    *is* it - and it resets the 3D-model list and the reference text metrics
    for free, which a hand-written reset would have to remember to do.

    Tracks, vias and the two filled zones stay: they are the routing result,
    and they are the whole point.
    """
    # Both lists are taken before anything is removed: the swig wrappers over
    # BOARD's item containers do not survive a mutation of a sibling
    # container, and iterating Drawings() after the footprints have gone
    # raises rather than returning the drawings.
    doomed = list(board.GetFootprints()) + list(board.GetDrawings())
    for item in doomed:
        board.Remove(item)
    # And the proxies are parked in a module-level list rather than dropped.
    # A BOARD_ITEM the board no longer owns has no destructor swig can find,
    # and collecting one does not merely leak it - it corrupts pcbnew's shared
    # swig type table, after which EVERY later call returns an untyped
    # SwigPyObject. The first symptom is FootprintLoad() handing back
    # something with no SetReference() on it, ~150 lines away from the Remove
    # that caused it. Holding the references costs a few MB for one run.
    _REMOVED.extend(doomed)


def main(out, reuse_routing=False):
    out = os.path.abspath(out)
    if reuse_routing:
        if not os.path.isfile(out):
            sys.exit("--no-route reuses the routing in %s, and that file does "
                     "not exist.\nRun a full build first: make pcb-build" % out)
        # Canonicalise on the way IN as well as out. The tracks and vias are
        # carried across with the uuids the file gave them, and KiCad's
        # s-expression writer breaks position ties between items with the
        # uuid - so a board last written by something that does not
        # canonicalise (the KiCad GUI, say) would serialise its copper in an
        # order a full build never produces. Content-derived uuids make that
        # tie deterministic again. No-op on a board this pipeline wrote.
        canonicalize_file(out)
        loaded = pcbnew.LoadBoard(out)
        verify_reusable(loaded)
        n_via = sum(1 for t in loaded.GetTracks() if t.Type() == pcbnew.PCB_VIA_T)
        print("reusing routing from %s: %d tracks, %d vias, %d filled zones"
              % (os.path.basename(out), len(list(loaded.GetTracks())) - n_via,
                 n_via, len(list(loaded.Zones()))))
        strip_derived(loaded)
        board, nets, fps = build_board(loaded)
    else:
        board, nets, fps = build_board()
        r, failed = route_board(board, fps)
        if failed:
            print("UNROUTED: %s" % ", ".join(failed))
        add_copper(board, nets, r)
    anchors = add_outline_and_silk(board)
    # Silk placement runs last, once every pad, footprint outline and board
    # text exists: it is a whole-board packing problem, and it cannot be
    # solved a label at a time as each one is created.
    strayed = silk.adrift(silk.place(board, anchors))
    if not reuse_routing:
        add_zones(board, nets)
    rpt_path = os.path.splitext(out)[0] + "-drc.rpt"
    # standalone python fill/DRC needs a project-attached board; kicad-cli
    # fills, saves and checks in one authentic pass.
    import subprocess
    board.SetFileName(out)
    pcbnew.SaveBoard(out, board)
    # The physical stack-up, which pcbnew cannot be asked to set: KiCad 10's
    # SWIG bindings do not wrap BOARD_STACKUP, so gen_pcb.STACKUP is written
    # into the saved file instead. Here rather than after the DRC pass, so
    # that on the full path kicad-cli parses the block and writes it back out
    # itself - a stack-up KiCad rejected fails the build rather than reaching
    # the fab. The fast path has nothing dirty to save, so it keeps these
    # bytes verbatim; that is why gen_pcb.stackup_sexp() emits KiCad's own
    # formatting rather than leaving it to the round trip.
    apply_stackup(out)
    # Every write goes through canonicalize_file: pcbnew hands each item a
    # random uuid and then orders the file by it, so without this an
    # unchanged design lands on disk differently every run (#234). Doing it
    # after *each* write - not just at the end - matters, because the zone
    # fill is only reproducible if kicad-cli is handed a reproducible board.
    canonicalize_file(out)
    # --refill-zones is not merely unnecessary on the fast path, it is WRONG.
    # KiCad's filler is idempotent once a zone is filled, but filling an
    # unfilled zone and refilling an already-filled one do not agree: refilling
    # this board's +3V3 pour rewrites ~180 lines of its filled_polygon. The
    # full path fills from empty; the fast path inherits that fill and must
    # leave it exactly alone, or byte-identity is lost on the pour rather than
    # on anything to do with silk. Skipping it is also ~0.8 s cheaper.
    drc = ["kicad-cli", "pcb", "drc"]
    if not reuse_routing:
        drc.append("--refill-zones")
    drc += ["--save-board", "--severity-all", "--all-track-errors",
            "-o", rpt_path, out]
    print("saved %s (%s); DRC via kicad-cli..."
          % (out, "fill inherited" if reuse_routing else "unfilled"))
    subprocess.run(drc, check=True, capture_output=True)
    canonicalize_file(out)
    # Put `schematic.top_level_sheets` back. Saving this board blanked it, and
    # the culprit is `pcbnew.SaveBoard()` above, NOT kicad-cli: a BOARD has a
    # PROJECT attached, saving the board writes that project alongside it, and
    # on the FULL path build_board() hands us a bare `pcbnew.BOARD()` whose
    # project is empty - so the root-sheet block is written out as []. The
    # fast path escapes it because `build_board(loaded)` starts from
    # LoadBoard(), which attaches the real project and carries the block
    # through. Measured both ways on a scratch copy: a fresh BOARD saved next
    # to a populated .kicad_pro empties it; `kicad-cli pcb drc --refill-zones
    # --save-board` over the same file leaves it exactly alone.
    #
    # That last point is worth recording, because 9bcb0bf blamed kicad-cli
    # ("the PCB tooling never loads a schematic") and concluded it "only ever
    # adds the block when missing and preserves a populated one". The
    # conclusion is right and still holds - kicad-cli is innocent here. What
    # the fix missed is that pcbnew's own writer does the damage, and it runs
    # AFTER gen_sch.sync_project(), so on `make pcb` the derived entry was
    # being reverted minutes later and a tracked file ended every full regen
    # silently changed.
    #
    # Re-syncing here, after the last write of the run, is ordering-
    # independent rather than another lap of the tug-of-war. sync_project is
    # idempotent: it returns False and touches nothing when already correct,
    # which is what the fast path reports.
    # Pass the SCHEMATIC path: sync_project derives both the .kicad_pro to
    # edit and the `filename` field it records from what it is handed, so
    # giving it `out` would record "bisque-controller.kicad_pcb" as the root
    # sheet - in step with nothing, and worse than the empty list.
    if sync_project(os.path.splitext(out)[0] + ".kicad_sch"):
        print("  root sheet in .kicad_pro: restored after the board save "
              "blanked it")
    for (lname, area, cx, cy) in plane_islands(pcbnew.LoadBoard(out)):
        print("  !! %s plane island of %.1f mm2 stranded at (%.1f, %.1f)"
              % (lname, area, cx, cy))
    print("KiCad DRC report -> %s" % rpt_path)
    summarize(rpt_path)
    # Last, and after the board is on disk: a label that had to travel is not
    # a reason to withhold the artefact you need in order to see why. It is a
    # reason not to ship it. `silk.RING_MAX` is a bound on how far a legend
    # may be moved from where it was authored before it stops describing what
    # it was pointed at - `CT A+/A-/B+/B-` once slid 14 mm onto a different
    # terminal block - and no amount of placer cleverness fixes an anchor
    # aimed at occupied board. That is a human's call, so it stops the build.
    if strayed:
        for txt, d in strayed:
            print("FAIL: board text %r moved %.2f mm from its anchor "
                  "(silk.RING_MAX = %.1f) - move the anchor in gen_pcb.SILK, "
                  "or the parts crowding it" % (txt, d, silk.RING_MAX))
        sys.exit(1)


if __name__ == "__main__":
    argv = sys.argv[1:]
    reuse = False
    paths = []
    for a in argv:
        if a == "--no-route":
            reuse = True
        elif a.startswith("-"):
            sys.exit("unknown option %s (usage: kicad_build.py [--no-route] "
                     "<out.kicad_pcb>)" % a)
        else:
            paths.append(a)
    main(paths[0] if paths else "bisque-controller.kicad_pcb",
         reuse_routing=reuse)
