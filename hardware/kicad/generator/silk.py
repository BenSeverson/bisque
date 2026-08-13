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

Obstacles are looked up through a uniform bucket grid (`_Grid`), the same
index `router.py` uses for copper. That is a lookup optimisation and nothing
more: it narrows which obstacles get TESTED, never which candidate wins, and
the placement it produces is byte-identical to the linear scan it replaced.
Anything that changes the answer is a dropped collision, not a speedup.
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

# The same clearances in internal units, resolved once. `MM` is
# `pcbnew.FromMM`, a SWIG call, and these used to be evaluated per obstacle
# inside the scan loops: 171 million calls, 63 s of the placer's 115 s under
# cProfile - more than every collision test and every bounding-box test in
# this module put together, and the single largest line in the profile. They
# are constants, so hoisting them cannot change a verdict.
_C_COPPER = MM(CLEAR_COPPER)
_C_EDGE = MM(CLEAR_EDGE)
_C_SILK = MM(CLEAR_SILK)
_ONE_MM = MM(1.0)
# How much nearer another part's body must be before a reference counts as
# naming it rather than its own. This is a margin, not a tie-break, and the
# two populations it separates are far apart: the mislabelling this rule
# exists to stop ran 1.3-3.4 mm nearer the wrong part (LED1 0.18 mm off Y1's
# can against 1.49 mm to its own LED), while a designator in a dense 0805 row
# sits in a gap that is nearly equidistant by construction - R33 and R36 are
# 2.3 mm apart, so their labels land within ~0.1 mm of both bodies and are
# not ambiguous to a reader, who has the row's order to go on. At 0.05 mm
# every such row label was refused, and the fallback then put them somewhere
# genuinely worse.
_C_NEAREST = MM(1.0)

# Bucket size for the obstacle index below, mm. Same as `router.py`'s, but
# measured rather than assumed: silk labels are wider and flatter than the
# track/pad geometry that number was chosen for, so the sweep was rerun here.
# It is flat. Placer wall time over three reps was 3.82-3.88 s anywhere in
# 1.5-4.0 mm - indistinguishable from noise - and only degrades outside that
# band (4.08 s at 1.0, 4.07 s at 6.0, 4.10 s at 8.0), because a cell much
# smaller than a label multiplies the per-cell filing and a cell much larger
# than one refills the bucket with objects the probe must reject one at a
# time. With no measurable reason to differ from the neighbouring module,
# don't.
BUCKET = 2.0
_BUCKET = MM(BUCKET)

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
#
# A REFERENCE DESIGNATOR is a different case, and gets a rule rather than a
# penalty. The placer only ever sees a bare board, where the middle of a
# large footprint is the perfect spot - nothing to collide with, distance
# zero - so J14's designator landed under a 6 x 4 mm connector body, U1's
# under the module's can, and LED2's on J1's shell: 13 of them, each either
# invisible once the part is fitted or naming the wrong part.
#
# So it is two terms, and the ORDER between them and a collision is the whole
# design:
#
#   W_COLLISION  40   touching other silk
#   W_ON_PART     5   sitting on a part body
#   W_DISTANCE    1   per mm, measured from the part's own body
#
# 5 is above the ~2 mm every part on this board needs to step off its own
# body (that distance is scale-free because a reference's distance is
# measured from its body, not its centre - see `_cost`), so a reference
# always leaves a body it can leave, and it bounds the drift at 5 mm so it
# cannot leave for somewhere useless. It is far below W_COLLISION, so it
# never buys that escape with an overlap - a designator hidden under the
# right part beats one printed through a neighbour's outline, which a first
# version of this rule got wrong by making "off the body" a hard constraint
# and taking two silk-on-silk collisions to satisfy it.
#
# `nearer_part` IS hard (with a fallback pass), because it is not a matter of
# degree: a designator closer to a neighbour than to its own part names the
# neighbour, and no amount of distance saved is worth that.
W_ON_PART = 5.0

# A reference must not slot INTO a row of board texts. Not touching them is
# not enough: the 28 pin names above J5/J6/J7 are positional, so `J6` landing
# in the 1 mm gap between `LT` and `RT` - legal, collision-free, and where
# the rule above first sent it - prints `UP DN LT J6 RT OK G` and invents a
# seventh pin on a header the user hand-wires. Charged above W_ON_PART and
# well below W_COLLISION, which orders the three outcomes correctly: beside
# the part if there is room, hidden under its own housing if there is not,
# and never printed through something else. Only board texts crowd; two
# designators side by side read fine.
W_CROWD = 10.0
CLEAR_CROWD = 0.5
_C_CROWD = MM(CLEAR_CROWD)

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


def _box_dist(box, x, y):
    """Distance from a point to a box; 0 inside it."""
    dx = max(box[0] - x, 0, x - box[2])
    dy = max(box[1] - y, 0, y - box[3])
    return math.hypot(dx, dy)


def _covers(box, bb):
    """Could a part with this body hide a label this size?

    A 2 x 1.25 mm 0805 cannot swallow a 3.4 x 1.4 mm designator: the label
    overhangs it on every side and stays perfectly readable, and a reader has
    the row's order to go on besides. So the dense passive rows - where a
    label in a 1.3 mm gap is near two bodies by construction - are not what
    the reference rules are about, and including them was actively harmful:
    R33 and R36 were refused every spot in their own row and pushed onto
    J13's and Y1's outlines, trading a non-problem for two DRC violations.
    A connector, module, crystal or IC body is what hides a label.
    """
    return (box[2] - box[0] >= bb[2] - bb[0]
            and box[3] - box[1] >= bb[3] - bb[1])


class _Grid:
    """Uniform bucket index over bounding boxes - `router.py`'s `buckets`.

    Each object is filed into every cell its box overlaps *grown by `pad`*,
    where `pad` is the clearance the probes will ask about; a probe then reads
    only the cells its own box touches. That is exact, not approximate: two
    overlapping boxes share at least one point, every point lies in exactly
    one cell, so a padded obstacle within `pad` of the probe always sits in a
    cell the probe reads. `near()` therefore returns a superset of the linear
    scan's hits and the caller's `_hit`/`Collide` tests still decide.

    Getting `pad` wrong is the one way this silently drops a collision - an
    obstacle within clearance but in the next cell - so it is a constructor
    argument rather than an assumption, exactly as `router.py:_insert()`'s own
    `pad` is. It carries one extra internal unit of slop so that no float
    boundary case can fall between the two floors.
    """

    __slots__ = ("pad", "cells")

    def __init__(self, pad):
        self.pad = pad + 1
        self.cells = {}

    def _span(self, bb, pad):
        return (int((bb[0] - pad) // _BUCKET), int((bb[1] - pad) // _BUCKET),
                int((bb[2] + pad) // _BUCKET), int((bb[3] + pad) // _BUCKET))

    def add(self, obj, bb):
        bx0, by0, bx1, by1 = self._span(bb, self.pad)
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                self.cells.setdefault((bx, by), []).append(obj)

    def discard(self, obj, bb):
        """Unfile `obj`, which must have been added at exactly this box."""
        bx0, by0, bx1, by1 = self._span(bb, self.pad)
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                self.cells[(bx, by)].remove(obj)

    def near(self, bb):
        """Every filed object that could touch `bb`, each yielded once.

        Once each matters: `graphic_hits()` and the silk-on-silk term COUNT
        their hits, so an object read out of two cells would score as two
        collisions and change the placement.
        """
        bx0, by0, bx1, by1 = self._span(bb, 0)
        if bx0 == bx1 and by0 == by1:
            return self.cells.get((bx0, by0), ())
        out, seen = [], set()
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                for o in self.cells.get((bx, by), ()):
                    if id(o) not in seen:
                        seen.add(id(o))
                        out.append(o)
        return out


class _Obstacles:
    """Everything a label must not touch, indexed by position.

    Both sets here are immovable for the life of a placement run, so they are
    filed once in the constructor and never touched again. The movable set -
    the other labels - is indexed separately, in `place()`.
    """

    def __init__(self, board):
        self.pads = _Grid(_C_COPPER)
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                ls = pad.GetLayerSet()
                if ls.Contains(pcbnew.F_Mask) and ls.Contains(pcbnew.F_Cu):
                    bb = _bbt(pad.GetBoundingBox())
                    self.pads.add((bb, pad.GetEffectiveShape(pcbnew.F_Cu)), bb)
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
        self.graphics = _Grid(_C_SILK)
        for fp in board.GetFootprints():
            ref = fp.GetReference()
            for it in fp.GraphicalItems():
                if it.GetLayer() == pcbnew.F_SilkS and not hasattr(it, "GetText"):
                    gbb = _bbt(it.GetBoundingBox())
                    self.graphics.add((ref, gbb, it.GetEffectiveShape()), gbb)
        # Part bodies, for the reference rule above. F.Fab is the outline of
        # the component itself, which is the question being asked - "will the
        # fitted part sit on this label" - and it is not the courtyard: Y1's
        # courtyard spans 20 mm of hand-solder pads with open board between
        # them, and C32's designator lives in that gap perfectly legibly.
        # The footprints that ship no F.Fab (test points, mounting holes,
        # solder jumpers) are flat anyway; they fall back to the same box the
        # side candidates are generated from.
        self.bodies = _Grid(0)
        self.body_of = {}
        for fp in board.GetFootprints():
            box = None
            for it in fp.GraphicalItems():
                if it.GetLayer() == pcbnew.F_Fab and not hasattr(it, "GetText"):
                    b = _bbt(it.GetBoundingBox())
                    box = b if box is None else (
                        min(box[0], b[0]), min(box[1], b[1]),
                        max(box[2], b[2]), max(box[3], b[3]))
            if box is None:
                box = _body_box(fp)
            ref = fp.GetReference()
            self.body_of[ref] = box
            self.bodies.add((ref, box), box)

    def on_copper(self, bb, sh):
        for pbb, psh in self.pads.near(bb):
            if _hit(bb, pbb, _C_COPPER) and sh.Collide(psh, _C_COPPER):
                return True
        return False

    def off_board(self, bb, sh):
        # The board edges are five drawings, not five hundred, so they stay a
        # flat list: an index would cost more to consult than to skip.
        m = _C_EDGE
        if self.box is not None and not (
                bb[0] >= self.box[0] + m and bb[1] >= self.box[1] + m
                and bb[2] <= self.box[2] - m and bb[3] <= self.box[3] - m):
            return True
        return any(sh.Collide(e, m) for e in self.edges)

    def on_part(self, bb):
        """Would a fitted component sit on a label centred in `bb`?

        The centre, not the box: a designator beside a part legitimately
        overhangs its body a little, and asking for no overlap at all would
        reject the very spots the side candidates exist to offer.
        """
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
        for _ref, box in self.bodies.near((cx, cy, cx, cy)):
            if box[0] <= cx <= box[2] and box[1] <= cy <= box[3] \
                    and _covers(box, bb):
                return True
        return False

    def nearer_part(self, owner, bb):
        """Is some OTHER part's body closer to this label than its own?

        Getting a designator off its own part is only half the job. Evicting
        it is what the courtyard penalty above did to the board texts, and
        the first version of the reference rule reproduced the same failure
        one part class down: LED1's designator cleared the WS2812 and landed
        0.18 mm off Y1's can, 1.49 mm from the LED it names, and R36's ended
        up 5 mm from R36 and 1.5 mm from R31. A label reading as the wrong
        part is worse than one hidden under the right part, so a candidate
        whose nearest body is not the owner's is refused and the fallback
        takes the hidden spot instead.

        Only bodies big enough to hide the label count, the same test
        `on_part` uses, and that restriction is a KNOWN COMPROMISE rather
        than a principle: naming is about proximity, not coverage, so by
        rights every body should count. Applying it to every body was tried
        twice and is infeasible on this board - R33 and R36 sit in a 2.3 mm
        pitch grid inside the ADE7953's routing, where the only spots that
        are not over copper are the ones near a neighbour, and the placer
        answered by printing both designators through J13's and Y1's
        outlines: two DRC violations against a committed budget of zero, to
        fix an ambiguity a reader resolves from the row's order anyway.

        The residue is visible and measured: R33's designator sits 6.5 mm
        from R33 and 1.6 mm from C34. That cluster is over-constrained, and
        as with the terminal blocks above, the fix is placement, not silk.

        Ties pass: they are common between equal neighbours and a coin-flip
        either way, so only a body nearer by more than the margin disqualifies.
        """
        own = self.body_of.get(owner)
        if own is None:
            return False
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
        d = _box_dist(own, cx, cy) - _C_NEAREST
        if d <= 0:
            return False
        for ref, box in self.bodies.near((cx - d, cy - d, cx + d, cy + d)):
            if ref != owner and _covers(box, bb) \
                    and _box_dist(box, cx, cy) < d:
                return True
        return False

    def graphic_hits(self, owner, bb, sh):
        """Collisions with immovable footprint outlines.

        A footprint's OWN outline counts. It is tempting to exempt it - a
        reference inside its own courtyard is how libraries ship - but KiCad
        reports it, and on this board it reported exactly that for J9 and J10
        after the first version of this placer exempted it.
        """
        n = 0
        for gref, gbb, gsh in self.graphics.near(bb):
            if not _hit(bb, gbb, _C_SILK):
                continue
            if sh.Collide(gsh, _C_SILK):
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
        # The box at `at`, cached. The label index is keyed on it, and `_cost`
        # reads every neighbour's box once per candidate - 24 million calls to
        # `box()` before this held the answer.
        self.bb = None

    def seat(self, cx, cy):
        """Record where this label now is. `at` and `bb` move together."""
        self.at = (cx, cy)
        self.bb = self.box(cx, cy)

    def move_to(self, cx, cy):
        self.item.SetPosition(pcbnew.VECTOR2I(int(round(cx - self.dx)),
                                              int(round(cy - self.dy))))
        self.seat(cx, cy)

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


def _cost(lab, cx, cy, obs, others, on_part_ok=False):
    """None if the placement is illegal, else its score.

    `others` is the label index, not a list: it holds every label at its
    current position, `lab` included, and `lab` is skipped here exactly as it
    was when this scanned the whole list.

    `on_part_ok` relaxes the nearest-part rule; it is the fallback pass, and
    the caller must score a label's CURRENT spot with the same value it
    searched under or the two are not comparable. Sitting on a part body is
    a weight, not a rule, and is charged in both passes.
    """
    bb = lab.box(cx, cy)
    sh = lab.shape(cx, cy)
    if obs.on_copper(bb, sh):
        return None
    if obs.off_board(bb, sh):
        return None
    if not on_part_ok and lab.kind == "ref" and obs.nearer_part(lab.owner, bb):
        return None
    n = obs.graphic_hits(lab.owner, bb, sh)
    crowd = 0
    # A reference reads its neighbourhood out to _C_CROWD, so it must probe
    # that far. The index files at _C_SILK, so the QUERY carries the extra
    # reach - `near()` returns a superset either way, and the tests below
    # still decide.
    ref = lab.kind == "ref"
    for o in others.near((bb[0] - _C_CROWD, bb[1] - _C_CROWD,
                          bb[2] + _C_CROWD, bb[3] + _C_CROWD) if ref else bb):
        if o is lab or o.at is None:
            continue
        if _hit(bb, o.bb, _C_SILK) and sh.Collide(o.shape(*o.at), _C_SILK):
            n += 1
        elif (ref and o.kind == "text" and _hit(bb, o.bb, _C_CROWD)
                and sh.Collide(o.shape(*o.at), _C_CROWD)):
            crowd += 1
    if lab.kind == "text":
        ddx = abs(cx - lab.anchor[0]) / _ONE_MM
        ddy = abs(cy - lab.anchor[1]) / _ONE_MM
        dist = math.hypot(W_LATERAL * ddx, ddy)
    else:
        # A reference's distance is measured from its part's BODY, not from
        # the part's centre, and that is what makes W_ON_PART a single number
        # for a 20 mm module and an 0805 alike. Measured from the centre, the
        # weight has to out-price a big part's half-width before its own
        # designator will step off it - 11.6 mm for U1 - and every small
        # part's designator is then free to wander just as far to escape a
        # body it merely touches. R33's went 6.5 mm, ending up 1.6 mm from
        # C34. From the body edge, every part's escape is the same ~2 mm.
        own = obs.body_of.get(lab.owner)
        dist = (_box_dist(own, cx, cy) / _ONE_MM if own is not None
                else math.hypot(cx - lab.anchor[0], cy - lab.anchor[1])
                / _ONE_MM)
    hid = W_ON_PART if ref and obs.on_part(bb) else 0.0
    return W_COLLISION * n + W_CROWD * crowd + hid + W_DISTANCE * dist, n


def _best(lab, obs, others, on_part_ok=False):
    best = None
    for i, (cx, cy) in enumerate(lab.candidates()):
        c = _cost(lab, cx, cy, obs, others, on_part_ok)
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
        lab.seat((b.GetLeft() + b.GetRight()) / 2.0,
                 (b.GetTop() + b.GetBottom()) / 2.0)

    # The labels are the one obstacle set that MOVES while the placer runs -
    # this is a greedy sequential pass, so every label must see its
    # neighbours where they are right now, not where they started. Rather
    # than rebuild the index (stale between rebuilds) or defer it (stale
    # within a pass), it is repaired in the same breath as the move: unfile
    # at the old box, move, refile at the new one, and nothing else in this
    # module is allowed to reposition a label. A `seat()` that did not go
    # through here is the only way this could drift, which is why the two
    # call sites below are the only two that exist.
    live = _Grid(_C_SILK)
    for lab in labels:
        live.add(lab, lab.bb)

    def reseat(lab, cx, cy):
        live.discard(lab, lab.bb)
        lab.move_to(cx, cy)
        live.add(lab, lab.bb)

    for p in range(PASSES):
        moved = 0
        for lab in labels:
            # Strict first, relaxed only if nothing off a part body is legal.
            # Both the search and the incumbent are scored under the same
            # rule, so a reference already sitting on a part scores None and
            # any legal alternative beats it.
            for on_part_ok in (False, True):
                cur = _cost(lab, lab.at[0], lab.at[1], obs, live, on_part_ok)
                best = _best(lab, obs, live, on_part_ok)
                if best is not None:
                    break
            if best is None:
                continue
            score, cx, cy, _n = best
            if cur is None or score < cur[0] - 1e-9:
                reseat(lab, cx, cy)
                moved += 1
            elif lab.at is not None:
                reseat(lab, lab.at[0], lab.at[1])
        if verbose:
            print("  silk pass %d: %d label(s) moved" % (p + 1, moved))
        if not moved:
            break

    # Relaxed: this reports what DRC would, and a reference left on a part
    # body because nothing else was legal is a nit, not a violation. The
    # count of those is reported separately so the fallback cannot go quiet.
    bad = 0
    for lab in labels:
        c = _cost(lab, lab.at[0], lab.at[1], obs, live, True)
        if c is None:
            bad += 1
            if verbose:
                print("  !! %s has no legal silk placement" % lab.item.GetText())
    if verbose:
        n = _collisions(labels, obs)
        hidden = sum(1 for lab in labels if lab.kind == "ref"
                     and obs.on_part(lab.bb))
        astray = sum(1 for lab in labels if lab.kind == "ref"
                     and obs.nearer_part(lab.owner, lab.bb))
        print("  silk: %d label(s) placed, %d touching other silk, %d illegal,"
              " %d reference(s) on a part body, %d nearer another part"
              % (len(labels), n, bad, hidden, astray))
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
