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
  SILK UNDER A PART  a board text inside the F.Fab body of a part big enough
                     to hide it. Printable, DRC-clean, and gone the moment
                     the board is assembled - which is the whole point of a
                     legend. This one is invisible to every other check here
                     by construction, and it is what let `RESET` and `BOOT`
                     print across the two buttons they name and `+`/`-`, the
                     board's only per-terminal polarity marks, print inside
                     the block they belong to.

The first two are HARD failures. SILK ON SILK fails above SILK_ON_SILK_MAX,
which records what the board actually achieves so a regression fails. SILK
UNDER A PART is budgeted by NAME rather than by count, in ON_PART_OK: a new
burial fails, and so does a stale entry, so the list cannot rot into a
rubber stamp.

The fourth kind of association defect - a label placed far from the thing it
names - cannot be checked here and is checked in `kicad_build.py` instead.
It needs each label's authored anchor, and the board file does not record
one: by the time a `gr_text` is on disk it is just a coordinate. `silk.py`
has the anchors while it places, so that is where the test lives.

Needs KiCad's python (`import pcbnew`); the Makefile resolves it as $KPY.
Usage: python3 check_silk.py [board.kicad_pcb]
"""
import os
import re
import sys

import logo

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


# Board texts that are allowed to print under a part, as (text, part). Each
# one is a placement problem the silk placer cannot solve, and each is here
# with the reason it cannot:
#
#   RESET/BOOT  There is no room. The board edge is 19.95 and SW1's and SW2's
#               own silk outlines start at 21.60, leaving a 1.40 mm strip for
#               a 1.53 mm text box; H1 and the USB receptacle take the sides,
#               and the +3V3/+5V/GND test points take the space below. The
#               legend fits nowhere but on the button.
#   SDA/SCL/3V3 LED1 is a 5 x 5 mm WS2812B sitting in J7's pin-name band, on
#               top of the labels for pins 5, 6 and 7. Nothing below the row
#               is free either - J11's block starts 1.8 mm down - so these
#               three cannot be named until LED1 or the header moves.
#
# Both need a part moved, which is `design.py`'s business and costs a full
# re-route. Until then the burial is deliberate and recorded; what must not
# happen is a SIXTH one appearing without anyone noticing, which is what this
# list is for. Remove an entry when its part moves - a stale one fails too.
ON_PART_OK = {
    ("RESET", "SW1"), ("BOOT", "SW2"),
    ("SDA", "J7"), ("SCL", "LED1"), ("3V3", "J7"),
}


# The one asset this board shares with another tree. `logo.FLAME_PATH` is a
# copy of the favicon's path, and a copy is only safe while something proves
# it is still a copy.
FAVICON = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir, os.pardir, "web_ui", "public", "favicon.svg"))


def _mm(v):
    return pcbnew.ToMM(v)


def check_logo():
    """The flame on the board must still be the flame in the browser tab.

    Missing favicon is a warning, not a failure: this checker's subject is
    the board, and hardware/ has to stay buildable from a checkout that does
    not carry the web UI. A favicon that is present and DIFFERENT is a
    failure, because that is the drift the copy exists to be caught by.
    """
    if not os.path.exists(FAVICON):
        print("check_silk: %s absent, logo path not cross-checked"
              % os.path.relpath(FAVICON))
        return 0
    m = re.search(r'<path\s+d="([^"]*)"', open(FAVICON).read())
    if m is None:
        print("FAIL: no <path d=...> in %s" % FAVICON)
        return 1
    want = " ".join(m.group(1).split())
    have = " ".join(logo.FLAME_PATH.split())
    if want != have:
        print("FAIL: logo.FLAME_PATH has drifted from %s"
              % os.path.relpath(FAVICON))
        print("  favicon: %s" % want)
        print("  logo.py: %s" % have)
        return 1
    print("check_silk: logo path matches %s" % os.path.relpath(FAVICON))
    return 0


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


def part_bodies(board):
    """[(ref, box)] over F.Fab - the outline of the fitted component.

    F.Fab, not the courtyard, and the same choice `silk.py` makes for the
    same reason: a courtyard is keep-out, not part. Y1's spans 20 mm of
    hand-solder pads with open board between them, and a designator in that
    gap is perfectly readable. Footprints with no F.Fab (test points,
    mounting holes, solder jumpers) are flat - nothing to hide a label
    under - so they are skipped rather than approximated.
    """
    out = []
    for fp in board.GetFootprints():
        box = None
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_Fab and not hasattr(it, "GetText"):
                b = it.GetBoundingBox()
                e = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
                box = e if box is None else (
                    min(box[0], e[0]), min(box[1], e[1]),
                    max(box[2], e[2]), max(box[3], e[3]))
        if box is not None:
            out.append((fp.GetReference(), box))
    out.sort()
    return out


def under_part(silk, bodies):
    """Board texts whose centre sits on a part big enough to hide them.

    Two restrictions, both matching `silk.py` so the placer and this checker
    cannot disagree about what counts:

    - the CENTRE, not the box. A label beside a part legitimately overhangs
      its body a little; asking for no overlap at all would condemn the very
      placements the placer is trying to find.
    - the body must be able to COVER the label. A 2 x 1.25 mm 0805 cannot
      hide a 3.4 x 1.4 mm designator - it overhangs on every side and stays
      readable - so the dense passive rows are not what this is about.

    Reference designators are excluded because the placer already refuses
    them (`W_ON_PART`, and `place()` reports any that had to settle); so are
    footprint texts, because a pin-1 `1` or a polarity `+` marks its part BY
    sitting on it. What is left is exactly the free-standing board texts.
    """
    hits = []
    for label, owner, _sh, bb, is_text in silk:
        if owner is not None or not is_text:
            continue
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
        for ref, box in bodies:
            if not (box[0] <= cx <= box[2] and box[1] <= cy <= box[3]):
                continue
            if (box[2] - box[0] >= bb[2] - bb[0]
                    and box[3] - box[1] >= bb[3] - bb[1]):
                hits.append((label, ref, bb))
                break
    return hits


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

    buried = under_part(silk, part_bodies(board))
    show("SILK OVER COPPER", over)
    show("SILK OFF BOARD", off)
    show("SILK ON SILK", onsilk)
    show("SILK UNDER A PART", buried)

    bad = check_logo()
    # Compared as a SET, both ways. A new burial is the regression this
    # exists to catch; an entry that no longer happens is a comment that has
    # stopped being true, and leaving those in is how a budget turns into a
    # rubber stamp.
    seen = set((lbl, ref) for lbl, ref, _bb in buried)
    for lbl, ref in sorted(seen - ON_PART_OK):
        print("\nFAIL: board text %r prints under %s and is not in ON_PART_OK"
              % (lbl, ref))
        bad = 1
    for lbl, ref in sorted(ON_PART_OK - seen):
        print("\nFAIL: ON_PART_OK lists %r under %s, which no longer happens "
              "- remove it" % (lbl, ref))
        bad = 1
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
