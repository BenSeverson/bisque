#!/usr/bin/env python3
"""Sync the board to the schematic's netlist; regenerate only what we own.

This is KiCad's "Update PCB from Schematic", by reference, as a script, plus
the derived layers the generator still owns:

  * footprints: added (parked outside the board edge), removed, swapped in
    place when the schematic's Footprint field changed, re-netted, valued,
    DNP-flagged - position, rotation, layer and lock state are the BOARD's
    and are never touched;
  * copper: never touched. Tracks or vias left on a net the schematic no
    longer has are reported, not deleted;
  * the `generated` group: every board text and silk graphic the sync owns
    (per-terminal legends, block names, test-point labels, the nameplate and
    its flame). Members are deleted and re-derived from where the parts ARE
    each run, unless locked - a locked member is a person's decision and is
    kept, and the entry it stands for is not re-emitted. Texts outside the
    group are the user's and are never touched;
  * reference designators are re-placed by silk.place() for unlocked
    footprints; a locked footprint keeps its designator where it is, and the
    placer routes everything else around it;
  * the zones, stack-up, copper layer types, net classes, title block and
    3D-model fixups are applied idempotently; a zone that exists is left
    with whatever outline the user gave it.

The run ends with KiCad's own zone fill + DRC pass and KiCad's own item
order, so opening the result in the GUI and saving is a no-op.

Usage: <kicad-python> sync_board.py [--netlist X.net] board.kicad_pcb
"""
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew

import gen_pcb as G
import netlist as NL
import silk
from gen_jlc import NOT_ASSEMBLED
from gen_pcb import apply_stackup, sync_netclasses, netclass_table, PLANE_LAYER
from kicad_build import (load_footprint, V, MM, MODEL_FIXUP, MODEL_DIR,
                         SILK_MIN_STROKE, widen_fp_silk, apply_layer_types,
                         read_project, restore_project, resort_to_kicad_order,
                         verify_dru_loaded, plane_islands, PLANE_CU,
                         usb_keepout, COPPER_LAYERS)
from project_sync import sync_project

GENERATED_GROUP = "generated"
NS = uuid.UUID("5a1c6d1e-7b3f-4c8a-9e2d-0b1f2a3c4d5e")   # sync-owned uuids
PARK_GAP = 8.0        # mm east of the board edge where new parts are parked
PARK_PITCH = 5.0

_REMOVED = []         # proxies of removed items: a BOARD_ITEM the board no longer
                      # owns has no destructor swig can find; collecting one
                      # corrupts pcbnew's type table, so they are parked here


def kiid(*key):
    return pcbnew.KIID(str(uuid.uuid5(NS, "/".join(str(k) for k in key))))


# --------------------------------------------------------------- footprints
def style_footprint(fp, ref, dnp):
    """Everything about a footprint that is policy rather than placement.

    Idempotent: each rule either sets a value or clamps one, so a footprint
    that has been through here before comes out unchanged.
    """
    fp.SetDNP(dnp)
    for pad in fp.Pads():
        num = str(pad.GetNumber())
        # library EP thermal vias use 0.2 mm drills; upsize to 0.3 mm so the
        # whole board stays inside JLCPCB's standard drill range
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            d = pad.GetDrillSize().x
            if 0 < d < MM(0.3):
                pad.SetDrillSize(pcbnew.VECTOR2I(MM(0.3), MM(0.3)))
        # solid pour connection where thermals starve (module GND/EP, USB
        # shell) - these want maximum copper anyway
        if (ref == "U1" and num in ("1", "40", "41")) or \
           (ref == "J1" and num in ("A1", "B1", "A12", "B12", "S1")):
            pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    # 3D models: fp.Models() hands back COPIES, so the list is rebuilt rather
    # than mutated (see the long note in kicad_build.build_board's history).
    fix = MODEL_FIXUP.get(ref)
    models = [(m.m_Filename, (m.m_Scale.x, m.m_Scale.y, m.m_Scale.z),
               (m.m_Rotation.x, m.m_Rotation.y, m.m_Rotation.z),
               (m.m_Offset.x, m.m_Offset.y, m.m_Offset.z)) for m in fp.Models()]
    if fix:
        assert models, "%s: MODEL_FIXUP set but footprint has no 3D model" % ref
        models = [(MODEL_DIR % fix["file"], scale, tuple(fix.get("rotate", rot)),
                   tuple(fix.get("offset", (0.0, 0.0, 0.0))))
                  for (_fn, scale, rot, _off) in models]
    if models:
        fp.Models().clear()
        for fn, scale, rot, off in models:
            nm = pcbnew.FP_3DMODEL()
            nm.m_Filename = fn
            nm.m_Scale = pcbnew.VECTOR3D(*scale)
            nm.m_Rotation = pcbnew.VECTOR3D(*rot)
            nm.m_Offset = pcbnew.VECTOR3D(*off)
            # A part that is not fitted must not be rendered as if it were.
            nm.m_Show = ref not in NOT_ASSEMBLED
            fp.Models().push_back(nm)
    # Silk: designator size and the fab's stroke floor; see kicad_build.
    t = fp.Reference()
    t.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
    t.SetTextThickness(MM(SILK_MIN_STROKE))
    for it in list(fp.GraphicalItems()) + [fp.Value()]:
        if it.GetLayer() == pcbnew.F_SilkS and hasattr(it, "GetText"):
            if it.GetTextThickness() < MM(SILK_MIN_STROKE):
                it.SetTextThickness(MM(SILK_MIN_STROKE))
    t.SetVisible(ref not in G.HIDE_REFS)
    if str(fp.GetFPID().GetLibItemName()) in G.STRIP_FP_SILK:
        for it in list(fp.GraphicalItems()):
            if it.GetLayer() == pcbnew.F_SilkS and not hasattr(it, "GetText"):
                fp.Remove(it)
                _REMOVED.append(it)
    widen_fp_silk(fp)


def reset_reference(fp, lib, name):
    """Put an unlocked footprint's designator back at its library default.

    silk.place() is a packer over the whole board, and re-running it over its
    own previous output is not the same problem as running it over a fresh
    board: the first thing it would see is where it put every label last
    time. Resetting to the library default is exactly the fresh build's
    starting state, because it IS it - a library footprint placed at this
    position and rotation.
    """
    tmp = load_footprint(lib, name)
    tmp.SetPosition(fp.GetPosition())
    if fp.GetLayer() != tmp.GetLayer():
        tmp.Flip(fp.GetPosition(), False)      # flip, THEN rotate: a flip mirrors the angle
    tmp.SetOrientation(fp.GetOrientation())
    r, lr = fp.Reference(), tmp.Reference()
    r.SetPosition(lr.GetPosition())
    r.SetTextAngle(lr.GetTextAngle())
    r.SetLayer(lr.GetLayer())
    r.SetMirrored(lr.IsMirrored())
    _REMOVED.append(tmp)


def swap_footprint(board, fp, lib, name):
    new = load_footprint(lib, name)
    assert new is not None, "%s:%s not in KiCad's footprint libraries" % (lib, name)
    new.SetPosition(fp.GetPosition())
    if fp.GetLayer() != new.GetLayer():
        new.Flip(fp.GetPosition(), False)      # flip, THEN rotate: a flip mirrors the angle
    new.SetOrientation(fp.GetOrientation())
    new.SetLocked(fp.IsLocked())
    new.SetUuid(fp.m_Uuid)
    new.SetReference(fp.GetReference())
    board.Remove(fp)
    _REMOVED.append(fp)
    board.Add(new)
    return new


def sync_footprints(board, nl, rep):
    have = {fp.GetReference(): fp for fp in board.GetFootprints()}
    nets = {}

    def net(name):
        if name not in nets:
            n = board.FindNet(name)
            if n is None:
                n = pcbnew.NETINFO_ITEM(board, name)
                board.Add(n)
            nets[name] = n
        return nets[name]

    eb = board.GetBoardEdgesBoundingBox()
    park_x = pcbnew.ToMM(eb.GetRight()) + PARK_GAP
    park_y = pcbnew.ToMM(eb.GetTop())
    for ref in sorted(set(have) - set(nl.comps)):
        fp = have.pop(ref)
        board.Remove(fp)
        _REMOVED.append(fp)
        rep["removed"].append(ref)
    for ref, c in nl.comps.items():
        if ":" not in c["footprint"]:
            raise SystemExit("%s has no footprint assigned in the schematic" % ref)
        lib, name = c["footprint"].split(":", 1)
        fp = have.get(ref)
        if fp is not None and str(fp.GetFPID().GetUniStringLibItemName()) != name:
            fp = swap_footprint(board, fp, lib, name)
            rep["swapped"].append((ref, name))
        elif fp is None:
            fp = load_footprint(lib, name)
            assert fp is not None, "%s:%s not in KiCad's footprint libraries" % (lib, name)
            fp.SetReference(ref)
            fp.SetPosition(V(park_x, park_y + PARK_PITCH * len(rep["added"])))
            fp.SetUuid(kiid("fp", ref))
            board.Add(fp)
            rep["added"].append(ref)
        have[ref] = fp
        fp.SetValue(c["value"])
        pad_nums = {str(p.GetNumber()) for p in fp.Pads() if str(p.GetNumber())}
        for num in sorted(set(c["pins"]) - pad_nums):
            rep["no_pad"].append((ref, num, c["pins"][num]))
        for pad in fp.Pads():
            num = str(pad.GetNumber())
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or not num:
                continue
            want = c["pins"].get(num)
            got = pad.GetNetname() or None
            if got != want:
                rep["renetted"].append((ref, num, got, want))
            pad.SetNet(net(want) if want else None)
        style_footprint(fp, ref, c["dnp"])
        if not fp.IsLocked():
            reset_reference(fp, lib, name)
    return have, net


def dead_copper(board, nl):
    """Tracks and vias on a net the schematic no longer has.

    Judged on the board AFTER KiCad's save + DRC pass, not before: that pass
    propagates a re-netted pad's new net onto the copper attached to it, so
    copper that merely followed a rename is not dead and must not be
    reported as if it were.
    """
    live = set(nl.nets)
    out = []
    for t in board.GetTracks():
        n = t.GetNetname()
        if n and n not in live:
            out.append((n, pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)))
    return out


# ------------------------------------------------------- generated group
def find_group(board):
    for g in board.Groups():
        if g.GetName() == GENERATED_GROUP:
            return g
    return None


def regenerate_group(board, fps, adopt_legacy=False):
    """Delete the unlocked members, re-derive, re-place. Returns the list
    of placed labels."""
    g = find_group(board)
    legacy = g is None
    if legacy and not adopt_legacy:
        sys.exit("this board has no `%s` group, so the sync cannot tell its "
                 "own silk from yours. If it was ungrouped by accident, undo "
                 "that in KiCad. If this board never had one (it predates the "
                 "sync), run once with --adopt-legacy: that adopts EVERY "
                 "unlocked F.Silkscreen board text and graphic as generated and "
                 "regenerates them - lock anything you want kept first."
                 % GENERATED_GROUP)
    if legacy:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(GENERATED_GROUP)
        g.SetUuid(kiid("group"))
        board.Add(g)
        # First sync of a board the old generator wrote: nothing is in a
        # group yet, but every F.SilkS board text and graphic on it IS ours
        # (the old pipeline emitted all of them). Adopt them, once.
        members = [d for d in board.GetDrawings()
                   if d.GetLayer() == pcbnew.F_SilkS]
        # ...and the old pipeline's USB keepout, which carried a random uuid.
        for z in board.Zones():
            if z.GetIsRuleArea() and z.GetDoNotAllowZoneFills() and \
                    z.GetLayerSet().Contains(pcbnew.F_Cu) and not z.IsLocked():
                board.Remove(z)
                _REMOVED.append(z)
    else:
        members = list(g.GetItems())
    kept = []
    for it in members:
        if it.IsLocked():
            kept.append(it)
            if it.GetParentGroup() is None:
                g.AddItem(it)
            continue
        if it.GetParentGroup() is not None:
            g.RemoveItem(it)
        board.Remove(it)
        _REMOVED.append(it)
    kept_texts = [(it.GetText(), it.GetPosition()) for it in kept
                  if hasattr(it, "GetText")]

    def pinned(txt, x, y):
        """A locked member already says this, near where it was aimed."""
        for t, p in kept_texts:
            if t == txt and abs(pcbnew.ToMM(p.x) - x) < 5.0 and \
                    abs(pcbnew.ToMM(p.y) - y) < 5.0:
                return True
        return False

    # Outline: created only when the board has none at all.
    if not any(d.GetLayer() == pcbnew.Edge_Cuts for d in board.GetDrawings()):
        bx0, by0, bx1, by1 = G.BX0, G.BY0, G.BX1, G.BY1
        corners = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
        for k in range(4):
            a, b = corners[k], corners[(k + 1) % 4]
            sh = pcbnew.PCB_SHAPE(board)
            sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
            sh.SetStart(V(*a))
            sh.SetEnd(V(*b))
            sh.SetLayer(pcbnew.Edge_Cuts)
            sh.SetWidth(MM(0.1))
            sh.SetUuid(kiid("edge", k))
            board.Add(sh)
            g.AddItem(sh)
    bx0, by0, bx1, by1 = G.BX0, G.BY0, G.BX1, G.BY1
    anchors = []
    for (txt, x, y, rot, size, lock) in G.SILK:
        if pinned(txt, x, y):
            continue
        # A legend anchored off the board belongs to a parked part. It is
        # emitted once the part is placed and synced, not before.
        if not (bx0 <= x <= bx1 and by0 <= y <= by1):
            continue
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetPosition(V(x, y))
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        t.SetTextThickness(MM(max(SILK_MIN_STROKE, size * 0.15)))
        t.SetTextAngleDegrees(rot)
        t.SetUuid(kiid("silk", txt, "%.3f" % x, "%.3f" % y))
        board.Add(t)
        g.AddItem(t)
        anchors.append((t, x, y, lock))
    for k, (pts, width) in enumerate(G.SILK_GRAPHICS):
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_POLY)
        sh.SetLayer(pcbnew.F_SilkS)
        sh.SetPolyPoints([V(x, y) for x, y in pts])
        sh.SetFilled(False)
        sh.SetWidth(MM(width))
        sh.SetUuid(kiid("silkgfx", k))
        board.Add(sh)
        g.AddItem(sh)
    if legacy:
        print("  generated group created; adopted %d legacy silk item(s)"
              % len(members))
    labels = silk.place(board, anchors)
    return labels


# ------------------------------------------------------------------ zones
def ensure_zones(board, net, group):
    """Create any owned zone that is missing; re-derive the USB keepout."""
    zones = list(board.Zones())

    def have(layer, netname, rule=False):
        return any(z.GetIsRuleArea() == rule and z.GetLayer() == layer
                   and (rule or z.GetNetname() == netname) for z in zones)

    bx0, by0, bx1, by1 = G.BX0, G.BY0, G.BX1, G.BY1
    m = 0.5
    corners = [(bx0 + m, by0 + m), (bx1 - m, by0 + m),
               (bx1 - m, by1 - m), (bx0 + m, by1 - m)]

    def _pour(layer, netname, key):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(net(netname))
        ol = z.Outline()
        ol.NewOutline()
        for (x, y) in corners:
            ol.Append(MM(x), MM(y))
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.2))
        z.SetThermalReliefGap(MM(0.3))
        z.SetThermalReliefSpokeWidth(MM(0.4))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetUuid(kiid("zone", key))
        board.Add(z)
        return z

    made = []
    for netname, layername in sorted(PLANE_LAYER.items()):
        if not have(PLANE_CU[layername], netname):
            _pour(PLANE_CU[layername], netname, layername)
            made.append("%s plane" % netname)
    for layer, lname in ((pcbnew.F_Cu, "F.Cu"), (pcbnew.B_Cu, "B.Cu")):
        if not have(layer, "GND"):
            z = _pour(layer, "GND", lname + "-pour")
            z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
            made.append("GND pour on " + lname)
    if not any(not z.GetIsRuleArea() and z.GetLayer() == pcbnew.F_Cu
               and z.GetNetname() == "+3V3" for z in zones):
        z = pcbnew.ZONE(board)
        z.SetLayer(pcbnew.F_Cu)
        z.SetNet(net("+3V3"))
        ol = z.Outline()
        ol.NewOutline()
        x0, y0, x1, y1 = G.U2_POUR
        for (x, y) in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            ol.Append(MM(x), MM(y))
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetAssignedPriority(1)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetUuid(kiid("zone", "U2-pour"))
        board.Add(z)
        made.append("+3V3 flood under U2")
    # The USB keepout follows the pair's tracks, so it is re-derived every
    # run unless someone locked it. It is known by its derived uuid and by
    # nothing else: any other rule area on the board is the user's.
    usb_id = kiid("zone", "usb-keepout").AsString()
    kept_locked = False
    for z in zones:
        if z.m_Uuid.AsString() != usb_id:
            continue
        if z.IsLocked():
            kept_locked = True
            continue
        if z.GetParentGroup() is not None:
            z.GetParentGroup().RemoveItem(z)
        board.Remove(z)
        _REMOVED.append(z)
    if not kept_locked:
        ka = pcbnew.ZONE(board)
        ls = pcbnew.LSET()
        ls.addLayer(pcbnew.F_Cu)
        ls.addLayer(pcbnew.B_Cu)
        ka.SetLayerSet(ls)
        ka.SetIsRuleArea(True)
        ka.SetDoNotAllowZoneFills(True)
        ka.SetDoNotAllowTracks(False)
        ka.SetDoNotAllowVias(False)
        ka.SetDoNotAllowPads(False)
        ka.SetDoNotAllowFootprints(False)
        ol = ka.Outline()
        ol.NewOutline()
        x0, y0, x1, y1 = usb_keepout(board)
        for (x, y) in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            ol.Append(MM(x), MM(y))
        ka.SetUuid(kiid("zone", "usb-keepout"))
        board.Add(ka)
        group.AddItem(ka)
    return made


def set_title_block(board):
    tb = pcbnew.TITLE_BLOCK()
    tb.SetTitle("Bisque Kiln Controller")
    tb.SetDate("2026-09-19")
    tb.SetRevision("B")
    tb.SetCompany("Bisque project")
    tb.SetComment(0, "ESP32-S3-WROOM-1U-N16R2 + 2x MAX31856 + dual SSR + ADE7953")
    tb.SetComment(1, "4-layer, 100 x 100 mm, JLCPCB standard process")
    board.SetTitleBlock(tb)


def view_of_pcbnew(board):
    """The legend code's placement view, from the live board object."""
    out = {}
    for fp in board.GetFootprints():
        name = str(fp.GetFPID().GetUniStringLibItemName())
        pins = {str(p.GetNumber()): (p.GetNetname() or None) for p in fp.Pads()}
        out[fp.GetReference()] = {
            "fpf": name + ".kicad_mod",
            "at": (pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y),
                   fp.GetOrientationDegrees()),
            "value": fp.GetValue(), "pins": pins}
    return out


def board_edge(board):
    """(x0, y0, x1, y1) of the outline's CENTRELINES, mm.

    GetBoardEdgesBoundingBox() includes the stroke width, which would put the
    nameplate pocket's lattice 0.05 mm off the one the outline was drawn on
    and move every nameplate row by that much on every sync.
    """
    xs, ys = [], []
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts:
            continue
        if d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            for v in (d.GetStart(), d.GetEnd()):
                xs.append(pcbnew.ToMM(v.x))
                ys.append(pcbnew.ToMM(v.y))
        else:
            bb = d.GetBoundingBox()
            h = d.GetWidth() / 2.0
            xs += [pcbnew.ToMM(bb.GetLeft() + h), pcbnew.ToMM(bb.GetRight() - h)]
            ys += [pcbnew.ToMM(bb.GetTop() + h), pcbnew.ToMM(bb.GetBottom() - h)]
    if not xs:
        sys.exit("the board has no Edge.Cuts outline; draw one before syncing")
    return (min(xs), min(ys), max(xs), max(ys))


# ------------------------------------------------------------------- main
def sync(out, net_path, adopt_legacy=False):
    nl = NL.load(net_path)
    board = pcbnew.LoadBoard(out)
    board.SetCopperLayerCount(COPPER_LAYERS)
    bds = board.GetDesignSettings()
    bds.m_TrackMinWidth = MM(0.2)
    bds.m_ViasMinSize = MM(0.5)
    bds.m_MinThroughDrill = MM(0.3)
    bds.m_CopperEdgeClearance = MM(0.3)
    rep = {k: [] for k in ("added", "removed", "swapped", "renetted", "dead_copper", "no_pad")}
    fps, net = sync_footprints(board, nl, rep)
    # Every silk table follows the parts as they now stand, parked ones
    # included - a parked part is outside the outline and blocks nothing.
    G.bind(view_of_pcbnew(board), board_edge(board))
    labels = regenerate_group(board, fps, adopt_legacy)
    made = ensure_zones(board, net, find_group(board))
    apply_layer_types(board)
    set_title_block(board)
    return board, rep, labels, made


def main(argv):
    net_path = None
    adopt_legacy = False
    paths = []
    it = iter(argv)
    for a in it:
        if a == "--netlist":
            net_path = next(it)
        elif a == "--adopt-legacy":
            adopt_legacy = True
        elif a.startswith("-"):
            sys.exit("usage: sync_board.py [--netlist X.net] [--adopt-legacy] board.kicad_pcb")
        else:
            paths.append(a)
    out = os.path.abspath(paths[0] if paths else "bisque-controller.kicad_pcb")
    stem = os.path.splitext(out)[0]
    if net_path is None:
        net_path = stem + ".net"
    sch = stem + ".kicad_sch"
    if os.path.exists(sch) and os.path.exists(NL.stamp_path(net_path)):
        if open(NL.stamp_path(net_path)).read().strip() != NL.stamp(sch):
            sys.exit("%s is stale against the schematic; run: make pcb-netlist"
                     % os.path.basename(net_path))
    project_before = read_project(out)
    board, rep, labels, made = sync(out, net_path, adopt_legacy=adopt_legacy)
    if rep["no_pad"]:
        for ref, num, n in rep["no_pad"]:
            print("FAIL: %s pin %s (net %s) in the schematic has no pad %s on the "
                  "board's footprint - the symbol and footprint disagree; nothing "
                  "written" % (ref, num, n, num))
        sys.exit(1)
    strayed, slid = silk.adrift(labels), silk.offaxis(labels)
    intruding = silk.in_legend_column(labels, G.TP_LABEL_TEXTS, G.LEGEND_OWNER)
    board.SetFileName(out)
    pcbnew.SaveBoard(out, board)
    apply_stackup(out)
    rpt_path = stem + "-drc.rpt"
    subprocess.run(["kicad-cli", "pcb", "drc", "--refill-zones", "--save-board",
                    "--severity-all", "--all-track-errors", "-o", rpt_path, out],
                   check=True, capture_output=True)
    resort_to_kicad_order(out)
    restore_project(project_before)
    if sync_project(sch):
        print("  root sheet in .kicad_pro: restored after the board save blanked it")
    if sync_netclasses(stem + ".kicad_pro"):
        print("  net classes in .kicad_pro: %d class(es) written"
              % (len(netclass_table()) + 1))

    # ---- report
    print("sync: %d added, %d removed, %d swapped, %d pad(s) re-netted"
          % (len(rep["added"]), len(rep["removed"]), len(rep["swapped"]),
             len(rep["renetted"])))
    for ref in rep["added"]:
        print("  + %s parked east of the board - place it" % ref)
    for ref in rep["removed"]:
        print("  - %s removed" % ref)
    for ref, name in rep["swapped"]:
        print("  ~ %s now %s" % (ref, name))
    for ref, num, got, want in rep["renetted"][:40]:
        print("  %s.%s: %s -> %s" % (ref, num, got or "<none>", want or "<none>"))
    if len(rep["renetted"]) > 40:
        print("  ... and %d more" % (len(rep["renetted"]) - 40))
    nl = NL.load(net_path)
    final = pcbnew.LoadBoard(out)
    dead = {}
    for n, x, y in dead_copper(final, nl):
        dead.setdefault(n, []).append((x, y))
    for n, pts in sorted(dead.items()):
        print("  !! %d track(s)/via(s) on net %s, which the schematic no longer "
              "has, near (%.1f, %.1f) - delete or re-net by hand"
              % (len(pts), n, pts[0][0], pts[0][1]))
    for z in made:
        print("  zone created: %s" % z)
    for (lname, area, cx, cy) in plane_islands(final):
        print("  !! %s plane island of %.1f mm2 stranded at (%.1f, %.1f)"
              % (lname, area, cx, cy))
    unconnected = final.GetConnectivity().GetUnconnectedCount(True)
    print("  unconnected items: %d%s"
          % (unconnected, "  (make pcb-route)" if unconnected else ""))
    print("KiCad DRC report -> %s" % rpt_path)
    import re
    for n, what in re.findall(r"\*\* Found (\d+) (\w[\w ]*?) \*\*", open(rpt_path).read()):
        print("  %s: %s" % (what.strip(), n))
    dru_fail = verify_dru_loaded(out)
    for txt, d in strayed:
        print("FAIL: board text %r moved %.2f mm from its anchor "
              "(silk.RING_MAX = %.1f) - move the anchor in gen_pcb.SILK, "
              "or the parts crowding it" % (txt, d, silk.RING_MAX))
    for txt, axis, d in slid:
        print("FAIL: terminal legend %r moved %.2f mm along its locked %s "
              "axis - it names a different terminal now. Clear the legend "
              "column in gen_pcb.PIN_LEGENDS, or move the part in the way."
              % (txt, d, axis))
    for txt, owner, d in intruding:
        if (txt, owner) in G.TP_LEGEND_OK:
            print("  (known) test-point label %r sits in %s's legend column "
                  "(overlap %.2f mm) - see gen_pcb.TP_LEGEND_OK" % (txt, owner, d))
            continue
        print("FAIL: test-point label %r prints inside %s's terminal legend "
              "column (overlap %.2f mm) - move the test point, not the label"
              % (txt, owner, d))
    if dru_fail:
        print("FAIL: %s" % dru_fail)
    intruding = [t for t in intruding if (t[0], t[1]) not in G.TP_LEGEND_OK]
    if strayed or slid or intruding or dru_fail:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
