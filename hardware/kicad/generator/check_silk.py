#!/usr/bin/env python3
"""Assert the front silkscreen is printable, legible and net-independent.

Three classes, checked with KiCad's own geometry (the same effective shapes
DRC collides), so a finding here is a finding pcbnew's DRC would also raise:

  SILK OVER COPPER   a silk item touching an exposed pad (mask opening).
                     Ink on bare copper is a solder defect, not a cosmetic
                     one - it wets badly and the label is lost anyway.
  SILK OFF BOARD     a silk item crossing Edge.Cuts, OR sitting entirely
                     outside it. Half a printed `5V / OUT` on a screw terminal
                     a user hand-wires is a real usability defect; a whole one
                     printed past the rout line is not printed at all. The
                     second case needs saying because neither KiCad's
                     `silk_edge_clearance` nor a naive crossing test sees it -
                     nothing is crossed - and a placer told only "do not
                     cross" will happily solve a crowded corner by shoving a
                     label into the void. This one did, once.
  SILK ON SILK       two silk items printed over each other. Reported with a
                     committed budget rather than a hard zero: on a 141-part
                     100 x 100 mm board the reference designators cannot all
                     be placed with zero touching, and the placer in
                     `silk.py` minimises rather than eliminates it.

The first two are HARD failures. The third fails only above SILK_ON_SILK_MAX,
which records what the board actually achieves so a regression fails.

Needs KiCad's python (`import pcbnew`); the Makefile resolves it as $KPY.
Usage: python3 check_silk.py [board.kicad_pcb]
"""
import os
import sys

try:
    import wx
    _app = wx.App(False)
    if hasattr(wx, "DisableAsserts"):
        wx.DisableAsserts()
except ImportError:
    pass
import pcbnew

# What the current generator achieves. Lower it whenever the placer improves;
# never raise it without saying why in the commit message.
SILK_ON_SILK_MAX = 0


def _mm(v):
    return pcbnew.ToMM(v)


def _name(owner, item):
    if hasattr(item, "GetText"):
        txt = item.GetText()
    else:
        txt = item.GetClass()
    return "%s%s" % (("%s:" % owner) if owner else "", txt)


def collect(board):
    """[(label, footprint-ref-or-None, shape, bbox)] for every F.SilkS item."""
    out = []

    def add(owner, item, is_text):
        sh = item.GetEffectiveShape()
        bb = item.GetBoundingBox()
        out.append((_name(owner, item), owner, sh,
                    (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()),
                    is_text))

    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS:
            add(None, d, hasattr(d, "GetText"))
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_SilkS:
                add(ref, it, hasattr(it, "GetText"))
        for t in (fp.Reference(), fp.Value()):
            if t.GetLayer() == pcbnew.F_SilkS and t.IsVisible():
                add(ref, t, True)
    out.sort(key=lambda t: (t[0], t[3]))
    return out


def exposed_pads(board):
    """Pads with a front mask opening - the copper silk must never touch."""
    out = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            ls = pad.GetLayerSet()
            if not (ls.Contains(pcbnew.F_Mask) and ls.Contains(pcbnew.F_Cu)):
                continue
            out.append(("%s pad %s" % (fp.GetReference(), pad.GetNumber()),
                        pad.GetEffectiveShape(pcbnew.F_Cu),
                        pad.GetBoundingBox()))
    out.sort(key=lambda t: t[0])
    return out


def edges(board):
    out = []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            out.append(d.GetEffectiveShape())
    return out


def board_box(board):
    box = None
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts:
            continue
        b = d.GetBoundingBox()
        e = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
        box = e if box is None else (min(box[0], e[0]), min(box[1], e[1]),
                                     max(box[2], e[2]), max(box[3], e[3]))
    return box


def _bb_hit(a, b, slack=0):
    return not (a[2] + slack < b[0] or b[2] + slack < a[0]
                or a[3] + slack < b[1] or b[3] + slack < a[1])


def main(pcb):
    board = pcbnew.LoadBoard(pcb)
    silk = collect(board)
    pads = exposed_pads(board)
    edge = edges(board)
    bbox_board = board_box(board)
    print("check_silk: %d F.Silkscreen items, %d exposed pads in %s"
          % (len(silk), len(pads), os.path.basename(pcb)))

    over, off, onsilk = [], [], []

    for label, owner, sh, bb, _t in silk:
        for pname, psh, pbb in pads:
            if not _bb_hit(bb, (pbb.GetLeft(), pbb.GetTop(),
                                pbb.GetRight(), pbb.GetBottom())):
                continue
            if sh.Collide(psh, 0):
                over.append((label, pname, bb))
        inside = (bbox_board is not None
                  and bb[0] >= bbox_board[0] and bb[1] >= bbox_board[1]
                  and bb[2] <= bbox_board[2] and bb[3] <= bbox_board[3])
        if not inside:
            off.append((label, "outside outline", bb))
        else:
            for esh in edge:
                if sh.Collide(esh, 0):
                    off.append((label, "crosses outline", bb))
                    break

    # Silk-on-silk counts the pairs KiCad's own silk clearance test counts.
    # At least one of the pair must be TEXT: two footprint outlines touching
    # is a placement question and placement is design.py's, not silk.py's.
    # A footprint's own reference over its own outline is NOT exempt - KiCad
    # reports it (it did so for J9 and J10 here) and so must this. Calibrated
    # against the pre-fix board, where this rule counts 81, exactly the 81
    # `silk_overlap` violations kicad-cli DRC reported.
    for i, (la, oa, sa, ba, ta) in enumerate(silk):
        for (lb, ob, sb, bbx, tb) in silk[i + 1:]:
            if not (ta or tb):
                continue
            if not _bb_hit(ba, bbx):
                continue
            if sa.Collide(sb, 0):
                onsilk.append((la, lb, ba))

    def show(kind, hits, limit=30):
        print("\n%s: %d" % (kind, len(hits)))
        for h in hits[:limit]:
            box = h[-1]
            print("  %-44s %-24s @ (%.1f, %.1f)"
                  % (h[0], h[1] if len(h) > 2 else "",
                     _mm(box[0]), _mm(box[1])))
        if len(hits) > limit:
            print("  ... and %d more" % (len(hits) - limit))

    show("SILK OVER COPPER", over)
    show("SILK OFF BOARD", off)
    show("SILK ON SILK", onsilk)

    bad = 0
    if over:
        print("\nFAIL: %d silk item(s) printed on exposed copper" % len(over))
        bad = 1
    if off:
        print("FAIL: %d silk item(s) clipped by the board edge" % len(off))
        bad = 1
    if len(onsilk) > SILK_ON_SILK_MAX:
        print("FAIL: %d silk-on-silk overlaps exceeds the committed budget "
              "of %d" % (len(onsilk), SILK_ON_SILK_MAX))
        bad = 1
    if not bad:
        print("\ncheck_silk: clean (silk-on-silk %d of %d allowed)"
              % (len(onsilk), SILK_ON_SILK_MAX))
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    os.pardir, "bisque-controller.kicad_pcb")))
