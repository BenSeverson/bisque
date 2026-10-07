"""pcbnew helpers shared by sync_board.py and route.py.

This used to be the board builder: it placed every footprint from
design.py, routed the whole board and wrote the file from nothing. The
board file owns placement and copper now (see sync_board.py), so what is
left here is the toolbox both scripts need - loading library footprints,
the silk stroke floor, the 3D-model fixups, the USB keepout derived from
the pair's tracks, the DRU self-test, plane-island reporting, project
snapshot/restore around a board save, and resort_to_kicad_order(), which
leaves a file in KiCad's own item order so a GUI save is a no-op.
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import pcbnew
from gen_pcb import (COPPER_LAYER_TYPE, USB_KEEPOUT_MARGIN, USB_DIFF_PAIR, U2_POUR)

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
# Both silk TEXT sites clamp here, and so - since JLC's DFM report on the
# 2026-10-04 package - do footprint OUTLINES (`widen_fp_silk`). They arrive at
# 0.12 mm from KiCad's stock libraries and used to be left there on the
# argument that nobody reads a part outline during assembly. Two things broke
# that: JLC's DFM flags every one of them under its line-width floor, and some
# outlines ARE read - C46's chamfered outline and `+` are the board's only
# printed polarity mark on a 100 uF electrolytic, and LED1's corner and U1's
# pin-1 marker orient parts by eye. The cost the old note feared is real but
# small: the placer's outline obstacles grow by 0.02 mm a side. It is done at
# build time, as STRIP_FP_SILK is, so no .kicad_mod is edited.
SILK_MIN_STROKE = 0.16

_major = int(pcbnew.Version().split(".")[0])
if _major < 10:
    sys.exit("kicad_build.py requires KiCad 10+ (found %s)" % pcbnew.Version())

# The footprint reader, resolved once. Belt-and-braces against the swig
# type-table corruption sync_board._REMOVED documents: while a live pcbnew
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
    # Y1 - the fifth footprint KiCad 10 ships no model for. It DECLARES one at
    # ${KICAD10_3DMODEL_DIR}/Oscillator.3dshapes/..., and that directory exists
    # with nine other parts in it, so the reference looks satisfied right up
    # until the render quietly omits the part. c_rotation is "0,0,0", so unlike
    # J1 there is nothing to correct.
    "Y1": dict(file="Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm"),
    # F1 - the sixth, and the one that proves the trap is still live. The
    # footprint declares ${KICAD10_3DMODEL_DIR}/Fuse.3dshapes/
    # Fuse_1812_4532Metric.step and that directory exists with 0402, 0603,
    # 0805, 1206 and 1210 in it - just not 1812. So the reference resolves to
    # a real directory, the render exits 0, and F1 simply is not there.
    # Nobody noticed until it was spotted in the committed image.
    # c_rotation "0,0,0", so nothing to correct.
    "F1": dict(file="Fuse_1812_4532Metric"),
}
MODEL_DIR = "${KIPRJMOD}/3dmodels/%s.step"


# Pad-to-silk clearance, mm - the `JLC: pad to silkscreen` rule in the .dru.
PAD_SILK_CLEAR = 0.15


def _pad_gap(sh, pads):
    """Edge-to-edge distance from silk shape `sh` to the nearest mask opening.

    A mask opening is the pad's copper grown by its solder-mask expansion -
    zero on every pad here except the fiducials. Bisected on Collide() rather
    than computed, because pcbnew's SHAPE API answers "within c?" and not
    "how far?"; 20 halvings of 1 mm is under a nanometre.
    """
    lim = MM(1.0)
    best = lim
    bb = sh.BBox()
    for psh, exp in pads:
        pb = psh.BBox()
        if (pb.GetLeft() - exp - lim > bb.GetRight() or bb.GetLeft() > pb.GetRight() + exp + lim
                or pb.GetTop() - exp - lim > bb.GetBottom() or bb.GetTop() > pb.GetBottom() + exp + lim):
            continue
        if sh.Collide(psh, exp):
            return 0
        if not sh.Collide(psh, exp + best):
            continue
        lo, hi = 0, best
        for _ in range(20):
            mid = (lo + hi) // 2
            if sh.Collide(psh, exp + mid):
                hi = mid
            else:
                lo = mid
        best = hi
    return best


def widen_fp_silk(fp):
    """Clamp a footprint's silk OUTLINES to SILK_MIN_STROKE, growing away from its pads.

    A stroke widened in place moves both edges out, and on the outlines that
    already sit closest to their own copper - TP1-TP12's ring (0.141 mm) and
    U1's pin-1 corner (0.130 mm), both under the pad-to-silk rule by name in
    the .dru - that would eat the very clearance the exception budgets. So an
    outline whose widened gap falls below min(original gap, the 0.15 mm rule)
    is moved by the half-width it gained, in whichever direction gives it the
    most room: grown in radius (a ring around its pad), or slid along one of
    eight directions (a line or a marker beside one). If no move gets back to
    that floor the build fails naming the outline, rather than shipping one
    that a DRC exception would have to absorb.
    """
    floor = MM(SILK_MIN_STROKE)
    pads = [(p.GetEffectiveShape(pcbnew.F_Cu), max(0, p.GetSolderMaskExpansion(pcbnew.F_Mask)))
            for p in fp.Pads()
            if p.IsOnLayer(pcbnew.F_Cu) and p.IsOnLayer(pcbnew.F_Mask)]
    for it in fp.GraphicalItems():
        if it.GetLayer() != pcbnew.F_SilkS or hasattr(it, "GetText"):
            continue
        w = it.GetWidth()
        if w >= floor:
            continue
        before = _pad_gap(it.GetEffectiveShape(), pads)
        it.SetWidth(floor)
        need = min(before, MM(PAD_SILK_CLEAR))
        if _pad_gap(it.GetEffectiveShape(), pads) >= need:
            continue
        d = (floor - w + 1) // 2
        moves = [("move", pcbnew.VECTOR2I(round(d * math.cos(a)), round(d * math.sin(a))))
                 for a in (k * math.pi / 4 for k in range(8))]
        if it.GetShape() == pcbnew.SHAPE_T_CIRCLE:
            moves.append(("radius", d))
        best = None
        for kind, arg in moves:
            if kind == "move":
                it.Move(arg)
            else:
                it.SetRadius(it.GetRadius() + arg)
            gap = _pad_gap(it.GetEffectiveShape(), pads)
            if kind == "move":
                it.Move(pcbnew.VECTOR2I(-arg.x, -arg.y))
            else:
                it.SetRadius(it.GetRadius() - arg)
            if best is None or gap > best[0]:
                best = (gap, kind, arg)
        if best[0] < need:
            raise SystemExit("widen_fp_silk: %s %s outline cannot reach %.3f mm of its pads "
                             "at a %.2f mm stroke (best %.3f mm)"
                             % (fp.GetReference(), it.GetShapeStr(), pcbnew.ToMM(need),
                                SILK_MIN_STROKE, pcbnew.ToMM(best[0])))
        if best[1] == "move":
            it.Move(best[2])
        else:
            it.SetRadius(it.GetRadius() + best[2])


def usb_keepout(board):
    """(x0, y0, x1, y1) of the outer-layer copper keepout around the USB pair:
    the bounding box of every USB_DP/USB_DN track on the board, grown by
    USB_KEEPOUT_MARGIN.

    Read off the board rather than typed, so it follows the pair on both
    paths - the full build has just drawn the tracks, --no-route has just
    loaded them - and cannot go stale the way the measured constant it
    replaces did. Asserts the box stays east of U2_POUR: a keepout reaching
    into that pour does not fail anything, it just stops the AMS1117's
    thermal copper from filling.
    """
    names = set(USB_DIFF_PAIR)
    xs, ys = [], []
    for t in board.GetTracks():
        if t.Type() != pcbnew.PCB_TRACE_T or t.GetNetname() not in names:
            continue
        for v in (t.GetStart(), t.GetEnd()):
            xs.append(pcbnew.ToMM(v.x))
            ys.append(pcbnew.ToMM(v.y))
    assert xs, "usb_keepout: no %s tracks on the board" % "/".join(sorted(names))
    m = USB_KEEPOUT_MARGIN
    box = (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
    assert box[0] >= U2_POUR[2], (
        "USB keepout reaches x %.2f, into U2_POUR (ends at x %.2f): the pair "
        "has moved west and the AMS1117's thermal pour would silently stop "
        "filling" % (box[0], U2_POUR[2]))
    return box


    # Rev B also carved a four-layer pour keepout across the SSR optocoupler
    # row so the planes could not short around the barrier; the optos were
    # reverted to direct low-side MOSFET drive (design.py's SSR block), so
    # that one is gone and both inner planes run whole.


def plane_islands(board):
    """[(layer, area_mm2, x, y), ...] for every plane island beyond the
    largest one on its layer.

    A plane is one sheet of copper only until enough antipads line up to cut
    it. Nothing can bridge a severed island back - there is no second copper
    layer carrying the same net to via across to - so this is a report, not a
    repair: it names the layer and the spot so the fix goes into placement.
    KiCad's own DRC reports the same thing as an unconnected zone, but only
    when a pad happens to sit on the stranded piece.

    INNER layers only. That restriction is the whole meaning of the check: on
    In1/In2 an island is a severed plane and a real defect, while on an outer
    pour it is just a puddle of copper trapped between traces, which is what
    a pour on a routed layer always produces. Reporting those would bury the
    signal it exists to raise - the outer pours generated two B.Cu puddles of
    87 and 75 mm2 on their first build, both perfectly ordinary. Anything the
    outer pours strand with no pad on it is deleted rather than reported, by
    ISLAND_REMOVAL_MODE_ALWAYS in add_zones().
    """
    out = []
    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        layer = z.GetLayer()
        if layer not in PLANE_CU.values():
            continue
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


# Sentinel rule appended to a throwaway copy of the .kicad_dru by
# verify_dru_loaded(). It has to be a constraint no real board can satisfy, so
# that silence means "file dropped" and never "board happens to comply".
DRU_SENTINEL_NAME = "SELF-TEST: rules file loaded"
DRU_SENTINEL = ('\n(rule "%s"\n\t(constraint track_width (min 5mm)))\n'
                % DRU_SENTINEL_NAME)


def verify_dru_loaded(out):
    """Prove KiCad actually READ the .kicad_dru, rather than assume it.

    A .kicad_dru KiCad cannot parse is discarded IN FULL and WITHOUT A
    MESSAGE. The one that happened here (FAB-READINESS-REVIEW-REVB.md A11)
    was a `(condition "...")` string broken across two lines; the cost was
    that every `kicad-cli pcb drc` pass for the life of the file checked none
    of JLC's limits and said so in the only way it can - by reporting a clean
    board. That is indistinguishable from success, which is exactly why it
    survived: 0 violations is what passing looks like.

    So the load is asserted positively instead. Copy the board, its project
    and the rules to a scratch directory, append a rule that CANNOT hold on
    any real board (every track at least 5 mm wide), and require it to fire.
    A silent sentinel means the rules file was dropped. Returns None on
    success, or a message describing the failure.
    """
    dru = os.path.splitext(out)[0] + ".kicad_dru"
    if not os.path.exists(dru):
        return None          # no sidecar is a choice, not a defect
    pro = os.path.splitext(out)[0] + ".kicad_pro"
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.basename(os.path.splitext(out)[0])
        shutil.copy(out, os.path.join(tmp, base + ".kicad_pcb"))
        if os.path.exists(pro):
            shutil.copy(pro, os.path.join(tmp, base + ".kicad_pro"))
        # The rules KiCad will be asked to load, plus the sentinel.
        with open(os.path.join(tmp, base + ".kicad_dru"), "w") as fh:
            fh.write(open(dru).read() + DRU_SENTINEL)
        rpt = os.path.join(tmp, "selftest.rpt")
        # No --refill-zones and no --save-board: this pass exists to find out
        # whether a file parsed, not to check or rewrite anything.
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "report",
                        "--severity-error", "-o", rpt,
                        os.path.join(tmp, base + ".kicad_pcb")],
                       check=True, capture_output=True)
        hits = open(rpt).read().count(DRU_SENTINEL_NAME)
    if hits:
        print("  %s: loaded (self-test rule fired %d\u00d7)"
              % (os.path.basename(dru), hits))
        return None
    return ("%s was IGNORED by KiCad - the whole file, silently. Every JLC "
            "limit in it went unchecked and the DRC report above is "
            "meaningless. Almost always a syntax error: a quoted string "
            "spanning two lines, an unbalanced paren, an unknown token. "
            "kicad-cli names neither the file nor the line, so bisect it by "
            "deleting rules until the self-test fires."
            % os.path.basename(dru))


_REMOVED = []


def apply_layer_types(board):
    """Set copper layer types on a loaded board from gen_pcb.COPPER_LAYER_TYPE.

    gen_pcb writes these into the board text it emits, and that is not enough:
    pcbnew builds its own layer table when it loads a board and writes THAT
    back out, so the types in the input text never reach disk. This runs on
    both paths - full and --no-route - because the fast path loads a saved
    board and would otherwise carry forward whatever types it already had,
    exactly as apply_stackup() has to re-impose the stack-up for the same
    reason.

    Unlike BOARD_STACKUP, this one KiCad 10 does wrap, so it is set through the
    API rather than patched into the text afterwards.
    """
    kinds = {"signal": pcbnew.LT_SIGNAL, "power": pcbnew.LT_POWER,
             "mixed": pcbnew.LT_MIXED, "jumper": pcbnew.LT_JUMPER}
    for name, kind in COPPER_LAYER_TYPE.items():
        lid = board.GetLayerID(name)
        if lid < 0:
            raise SystemExit("kicad_build: no layer %r on the board" % name)
        board.SetLayerType(lid, kinds[kind])


def read_project(out):
    """Snapshot the sibling .kicad_pro/.kicad_prl before anything writes a board.

    Every tool here attaches the project to the board it saves and writes it
    back out from the PCB side alone, dropping whatever it never loaded. The
    known casualty used to be `schematic.top_level_sheets`, which sync_project()
    puts back - but it is not the only one: a full build also took out the whole
    `erc` block and `sch_revision`, because the old full build started from a bare
    pcbnew.BOARD() with an empty project attached. Nothing noticed, since the
    two repairs downstream only rebuild the blocks THEY own.

    So snapshot the bytes instead of enumerating what might go missing, and put
    them back once the last write is done. sync_project()/sync_netclasses()
    still run afterwards and are idempotent, so the derived blocks stay derived
    and the hand-authored ones stop being collateral. The fast path never needed
    this - LoadBoard() attaches the real project - and the restore is a no-op
    there.
    """
    stem = os.path.splitext(out)[0]
    return {f: open(f, "rb").read()
            for f in (stem + ".kicad_pro", stem + ".kicad_prl")
            if os.path.exists(f)}


def restore_project(saved):
    for f, blob in saved.items():
        if os.path.exists(f) and open(f, "rb").read() != blob:
            with open(f, "wb") as fh:
                fh.write(blob)
            print("  %s: restored blocks the board save dropped"
                  % os.path.basename(f))


def resort_to_kicad_order(path):
    """Leave the board in the order KiCad's own writer produces.

    KiCad orders board items by uuid - footprints outright, tracks and vias as
    the tie-break after position - so with the uuids the file carries
    that order is a function of the design, and putting the file in it is what
    makes opening the board in the GUI and saving it a no-op instead of a
    61,654-line reorder.

    Two things about this are easy to get wrong, and both were, here:

    `kicad-cli pcb drc --save-board` is NOT the tool for it. It writes items
    back in the order it read them, so it will happily preserve
    canonicalize.py's content order and report byte-identical output - which
    makes it useless as a stand-in for a GUI save, and it was believed to be
    one for a while. `pcb upgrade --force` does sort.

    One pass is not enough. KiCad's sort leaves ties in load order, so a file
    arriving in a foreign order needs a second pass to settle; measured on this
    board, pass 1 and pass 2 differ by 16,860 lines and pass 2 and pass 3 by
    none. Loop to the fixpoint rather than assuming a count, and fail loudly if
    it does not converge - an oscillation would mean the writer has no fixpoint
    at all, and every one of these files would churn forever.
    """
    for i in range(5):
        before = open(path, "rb").read()
        subprocess.run(["kicad-cli", "pcb", "upgrade", "--force", path],
                       check=True, capture_output=True)
        if open(path, "rb").read() == before:
            print("  re-sorted into KiCad's own item order (%d pass(es))" % (i + 1))
            return i
    sys.exit("kicad-cli pcb upgrade --force never settled on an order for %s; "
             "KiCad's writer has no fixpoint here and the board cannot be "
             "stored in it" % path)


