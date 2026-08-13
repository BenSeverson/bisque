#!/usr/bin/env python3
"""Derive every F.Silkscreen label position instead of hand-placing it.

Rev B shipped its silk the way rev A did: `gen_pcb.SILK` held 51 absolute
coordinates chosen when the board had 52 parts, and `kicad_build.py` carried a
hand-maintained list of 18 reference designators nudged out of collisions. At
141 parts that is a patch list, not a mechanism - KiCad DRC reported 109
silkscreen violations on 49 designators, including four labels for screw
terminals a user hand-wires printed half off the board edge.

This module replaces both tables' *positions* with a placer. The anchors stay
(a board text still says where it wants to live, a reference still wants to sit
beside its own part); where the label actually lands is chosen by scoring
candidate placements:

    hard   never on an exposed pad             - ink on bare copper is a
                                                 solder defect
    hard   never crossing Edge.Cuts            - a clipped label is unreadable
    soft   minimise silk touching other silk
    soft   stay close to the thing you label

Geometry is KiCad's own: every candidate is tested with the effective shapes
DRC collides, so the placer and `check_silk.py` agree by construction.

Deterministic by construction, which `check_canonical.py` requires: candidate
order is fixed, items are placed in a sorted order, and the refinement passes
only ever accept a strict improvement, so the loop cannot oscillate.

All labels stay upright. Rotating a designator 90 degrees buys space but costs
the assembler a head-tilt on a board where the parts are already dense; the
lateral slides along each side turned out to be enough.
"""
import math

import pcbnew

MM = pcbnew.FromMM

# Clearances, mm. Copper and edge are padded beyond the zero KiCad checks at
# so a placement is not chosen exactly on the boundary, where a rounding
# difference between this placer and DRC would flip the verdict.
CLEAR_COPPER = 0.15
CLEAR_EDGE = 0.25
CLEAR_SILK = 0.05

# Scoring. A collision costs more than any displacement the candidate sets can
# produce, so a clean-but-distant spot always beats a cramped-but-adjacent one
# - but distance still breaks ties, which is what keeps a designator beside its
# own part.
W_COLLISION = 40.0
W_DISTANCE = 1.0
W_ORDER = 0.02

# A board text pays four times as much for sliding ALONG its reading
# direction as for moving perpendicular to it. This is not cosmetic: the 28
# pin names above J5/J6/J7 identify a pin by sitting over it, so a label that
# slides sideways doesn't just look ragged, it names the wrong pin. The first
# version of this placer had no such term and pushed J7's `SDA` and `3V3` a
# pin-pitch off their own pads. Moving a label up or down cannot mislead that
# way, so that direction stays cheap.
W_LATERAL = 4.0

# A terminal label printed inside its terminal block's body is legal (no
# copper, no edge, no other silk) and half-hidden once the block is fitted -
# visible in the 3D render, invisible to DRC. A courtyard penalty was tried
# to push those labels clear and REVERTED: the free gaps between the four
# left-edge blocks are 1.3-2.1 mm, so evicting `SSR2` from J9 sent it up
# beside J4, where it reads as J4's label. Mislabelling a mains-adjacent
# screw terminal is worse than partly hiding its label under the block that
# it is unambiguously attached to. See the report; the nit is known, and the
# fix is placement, not silk.

PASSES = 4

# Ring offsets for an anchored board text, nearest first. Angle order is
# below / above / right / left, then the diagonals: a label reads best
# directly under or over the thing it names.
_RING_R = (0.0, 1.0, 1.5, 2.0, 2.6, 3.4, 4.2, 5.2, 6.5, 8.0, 10.0,
           12.0, 14.0)
_RING_A = (90, 270, 0, 180, 45, 135, 225, 315,
           22, 68, 112, 158, 202, 248, 292, 338)

# Side offsets for a reference designator: gap from the part body, and the
# lateral slide along that side.
_SIDE_GAP = (0.25, 0.55, 0.95, 1.4, 2.0, 2.8, 3.8)
_SIDE_SLIDE = (0.0, 1.2, -1.2, 2.4, -2.4, 3.8, -3.8)


def _bbt(box):
    return (box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom())


def _hit(a, b, slack=0):
    return not (a[2] + slack < b[0] or b[2] + slack < a[0]
                or a[3] + slack < b[1] or b[3] + slack < a[1])


class _Obstacles:
    """Everything a label must not touch, with a bounding-box prefilter."""

    def __init__(self, board):
        self.pads = []
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                ls = pad.GetLayerSet()
                if ls.Contains(pcbnew.F_Mask) and ls.Contains(pcbnew.F_Cu):
                    self.pads.append((_bbt(pad.GetBoundingBox()),
                                      pad.GetEffectiveShape(pcbnew.F_Cu)))
        self.edges = [d.GetEffectiveShape() for d in board.GetDrawings()
                      if d.GetLayer() == pcbnew.Edge_Cuts]
        # "Does not cross the edge" is NOT "is on the board". A label placed
        # wholly past the rout line crosses nothing, collides with nothing,
        # and prints nowhere; scoring alone will choose exactly that spot,
        # because empty space is free. Containment is the real constraint.
        self.box = None
        for d in board.GetDrawings():
            if d.GetLayer() != pcbnew.Edge_Cuts:
                continue
            b = _bbt(d.GetBoundingBox())
            self.box = b if self.box is None else (
                min(self.box[0], b[0]), min(self.box[1], b[1]),
                max(self.box[2], b[2]), max(self.box[3], b[3]))
        # Footprint silk graphics are immovable: they belong to the library
        # footprint and moving them would be editing placement.
        # A footprint's silk TEXT (the pin-1 "1" several libraries carry) is
        # movable - it landed on R3's pad here - so it is a label, not an
        # obstacle. Only the drawn outlines are immovable.
        self.graphics = []
        for fp in board.GetFootprints():
            ref = fp.GetReference()
            for it in fp.GraphicalItems():
                if it.GetLayer() == pcbnew.F_SilkS and not hasattr(it, "GetText"):
                    self.graphics.append((ref, _bbt(it.GetBoundingBox()),
                                          it.GetEffectiveShape()))

    def on_copper(self, bb, sh):
        for pbb, psh in self.pads:
            if _hit(bb, pbb, MM(CLEAR_COPPER)) and sh.Collide(psh, MM(CLEAR_COPPER)):
                return True
        return False

    def off_board(self, bb, sh):
        m = MM(CLEAR_EDGE)
        if self.box is not None and not (
                bb[0] >= self.box[0] + m and bb[1] >= self.box[1] + m
                and bb[2] <= self.box[2] - m and bb[3] <= self.box[3] - m):
            return True
        return any(sh.Collide(e, m) for e in self.edges)

    def graphic_hits(self, owner, bb, sh):
        """Collisions with immovable footprint outlines.

        A footprint's OWN outline counts. It is tempting to exempt it - a
        reference inside its own courtyard is how libraries ship - but KiCad
        reports it, and on this board it reported exactly that for J9 and J10
        after the first version of this placer exempted it.
        """
        n = 0
        for gref, gbb, gsh in self.graphics:
            if not _hit(bb, gbb, MM(CLEAR_SILK)):
                continue
            if sh.Collide(gsh, MM(CLEAR_SILK)):
                n += 1
        return n


class _Label:
    """One movable silk text: the pcbnew item plus where it wants to be."""

    def __init__(self, key, owner, item, anchor, body, kind):
        self.key = key            # sort key, also the tie-break
        self.owner = owner        # footprint ref, for same-footprint exemption
        self.item = item
        self.anchor = anchor      # (x, y) internal units it wants to be near
        self.body = body          # part body box to sit beside, or None
        self.kind = kind          # "ref" | "text"
        bb = item.GetBoundingBox()
        pos = item.GetPosition()
        self.hw = bb.GetWidth() / 2.0
        self.hh = bb.GetHeight() / 2.0
        # The text's box is not necessarily centred on its anchor point.
        self.dx = (bb.GetLeft() + bb.GetRight()) / 2.0 - pos.x
        self.dy = (bb.GetTop() + bb.GetBottom()) / 2.0 - pos.y
        # Collide the glyphs, not a bounding rectangle. A rectangle is not
        # merely pessimistic here, it is WRONG in both directions: KiCad's
        # generic SHAPE::Collide answered False for a SHAPE_RECT inside
        # BZ1's circular outline, a collision the real glyph strokes report.
        # The shape is built once and translated per candidate - Clone()+
        # Move() costs microseconds, and it keeps this placer's geometry
        # identical to check_silk.py's.
        self.base = ((bb.GetLeft() + bb.GetRight()) / 2.0,
                     (bb.GetTop() + bb.GetBottom()) / 2.0)
        self.base_shape = item.GetEffectiveShape()
        self.at = None            # chosen box centre

    def move_to(self, cx, cy):
        self.item.SetPosition(pcbnew.VECTOR2I(int(round(cx - self.dx)),
                                              int(round(cy - self.dy))))
        self.at = (cx, cy)

    def box(self, cx, cy):
        return (cx - self.hw, cy - self.hh, cx + self.hw, cy + self.hh)

    def shape(self, cx, cy):
        s = self.base_shape.Clone()
        s.Move(pcbnew.VECTOR2I(int(round(cx - self.base[0])),
                               int(round(cy - self.base[1]))))
        return s

    def candidates(self):
        """Deterministic candidate box centres, best-intent first."""
        ax, ay = self.anchor
        out = []
        if self.body is not None:
            x0, y0, x1, y1 = self.body
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            for gap in _SIDE_GAP:
                g = MM(gap)
                for slide in _SIDE_SLIDE:
                    s = MM(slide)
                    out.append((mx + s, y1 + g + self.hh))   # south
                    out.append((mx + s, y0 - g - self.hh))   # north
                    out.append((x1 + g + self.hw, my + s))   # east
                    out.append((x0 - g - self.hw, my + s))   # west
        for r in _RING_R:
            for a in _RING_A:
                rad = math.radians(a)
                out.append((ax + MM(r) * math.cos(rad),
                            ay + MM(r) * math.sin(rad)))
                if r == 0.0:
                    break
        return out


def _cost(lab, cx, cy, obs, others):
    """None if the placement is illegal, else its score."""
    bb = lab.box(cx, cy)
    sh = lab.shape(cx, cy)
    if obs.on_copper(bb, sh):
        return None
    if obs.off_board(bb, sh):
        return None
    n = obs.graphic_hits(lab.owner, bb, sh)
    for o in others:
        if o is lab or o.at is None:
            continue
        if not _hit(bb, o.box(*o.at), MM(CLEAR_SILK)):
            continue
        if sh.Collide(o.shape(*o.at), MM(CLEAR_SILK)):
            n += 1
    ddx = abs(cx - lab.anchor[0]) / MM(1.0)
    ddy = abs(cy - lab.anchor[1]) / MM(1.0)
    if lab.kind == "text":
        dist = math.hypot(W_LATERAL * ddx, ddy)
    else:
        dist = math.hypot(ddx, ddy)
    return W_COLLISION * n + W_DISTANCE * dist, n


def _best(lab, obs, others):
    best = None
    for i, (cx, cy) in enumerate(lab.candidates()):
        c = _cost(lab, cx, cy, obs, others)
        if c is None:
            continue
        score = c[0] + W_ORDER * i
        if best is None or score < best[0] - 1e-9:
            best = (score, cx, cy, c[1])
    return best


def _body_box(fp):
    """Part body: pads and footprint silk graphics, but not its own text."""
    box = None
    for it in list(fp.Pads()) + list(fp.GraphicalItems()):
        if it.GetClass() == "PAD" or it.GetLayer() in (pcbnew.F_SilkS,
                                                       pcbnew.F_CrtYd):
            b = _bbt(it.GetBoundingBox())
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        p = fp.GetPosition()
        box = (p.x - MM(0.5), p.y - MM(0.5), p.x + MM(0.5), p.y + MM(0.5))
    return box


def collect_labels(board, text_anchors):
    """Every movable F.SilkS text.

    `text_anchors` is [(pcbnew text item, x_mm, y_mm)] for the board-level
    texts - the coordinate each one was authored at, which the placer treats
    as a wish rather than a instruction.
    """
    labels = []
    for fp in sorted(board.GetFootprints(), key=lambda f: _refkey(f.GetReference())):
        t = fp.Reference()
        if t.GetLayer() != pcbnew.F_SilkS or not t.IsVisible():
            continue
        ref = fp.GetReference()
        p = fp.GetPosition()
        labels.append(_Label(("2ref", _refkey(ref)), ref, t, (p.x, p.y),
                             _body_box(fp), "ref"))
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_SilkS and hasattr(it, "GetText"):
                ip = it.GetPosition()
                labels.append(_Label(("3fptext", (_refkey(ref), it.GetText())),
                                     ref, it, (ip.x, ip.y), None, "text"))
    for i, (item, ax, ay) in enumerate(text_anchors):
        labels.append(_Label(("1text", i), None, item, (MM(ax), MM(ay)),
                             None, "text"))
    labels.sort(key=lambda l: l.key)
    return labels


def _refkey(ref):
    """Natural sort so R9 precedes R10 - order must not depend on ASCII."""
    head = ref.rstrip("0123456789")
    tail = ref[len(head):]
    return (head, int(tail) if tail else -1)


def place(board, text_anchors, verbose=True):
    """Position every movable F.Silkscreen label."""
    obs = _Obstacles(board)
    labels = collect_labels(board, text_anchors)

    # Seed: everything at its anchor / library default, so pass 1 already sees
    # a complete board rather than an empty one.
    for lab in labels:
        b = lab.item.GetBoundingBox()
        lab.at = ((b.GetLeft() + b.GetRight()) / 2.0,
                  (b.GetTop() + b.GetBottom()) / 2.0)

    for p in range(PASSES):
        moved = 0
        for lab in labels:
            cur = _cost(lab, lab.at[0], lab.at[1], obs, labels)
            best = _best(lab, obs, labels)
            if best is None:
                continue
            score, cx, cy, _n = best
            if cur is None or score < cur[0] - 1e-9:
                lab.move_to(cx, cy)
                moved += 1
            elif lab.at is not None:
                lab.move_to(lab.at[0], lab.at[1])
        if verbose:
            print("  silk pass %d: %d label(s) moved" % (p + 1, moved))
        if not moved:
            break

    bad = 0
    for lab in labels:
        c = _cost(lab, lab.at[0], lab.at[1], obs, labels)
        if c is None:
            bad += 1
            if verbose:
                print("  !! %s has no legal silk placement" % lab.item.GetText())
    if verbose:
        n = _collisions(labels, obs)
        print("  silk: %d label(s) placed, %d touching other silk, %d illegal"
              % (len(labels), n, bad))
    return labels


def _collisions(labels, obs):
    seen = 0
    for i, a in enumerate(labels):
        seen += obs.graphic_hits(a.owner, a.box(*a.at), a.shape(*a.at))
        for b in labels[i + 1:]:
            if _hit(a.box(*a.at), b.box(*b.at)) and \
               a.shape(*a.at).Collide(b.shape(*b.at), 0):
                seen += 1
    return seen
