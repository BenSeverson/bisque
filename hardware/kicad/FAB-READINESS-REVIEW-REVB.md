# JLCPCB Fabrication Readiness Review — Rev B

Board: `bisque-controller` — **4-layer**, 100 × 100 mm, 1.6 mm, 141 components
(109 machine-placed SMD across 40 BOM lines + 13 hand-fitted THT/wafer parts +
4 mounting holes + 15 non-assembled features: 12 test pads, 2 solder jumpers,
1 DNP header)
Reviewed: 2026-08-11, against KiCad 10.0.5 and the Task 14 board build.
Re-reviewed: 2026-08-12, after the PR #301 fix wave (schematic sheet size +
`SJ3`/`SJ4`) — see "PR #301 review round" below.
Re-reviewed: 2026-08-12, after the **opto-isolation reversal** — see "The
opto-isolation reversal" below. That round removed `U8`/`U9`, `SJ3`/`SJ4`,
the four-layer pour keepout, the router keepout and `check_isolation.py`, and
added `Q4`/`Q5`/`Q6`/`R47`.
Status: **ready to order, bare or assembled**, subject to the sourcing flag
in "Open items" below.

This review supersedes `FAB-READINESS-REVIEW.md` **for this board only**.
That file documents rev A — a 2-layer, 100 × 80 mm, 52-footprint board — and
is kept as history, not edited into a claim about a board it never
described. Rev B is a respin, not a variant: the thermocouple front-end,
module variant, output bank, and layer count all changed, and no attempt was
made to keep rev A hardware compatible with rev B firmware defaults. The one
item that carries forward unchanged is `CERT-001`, below.

## Verdict

**Ready to order.** Every verification gate in
`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md` §7 that still
applies passes, including pin-map agreement. The isolation-barrier gate no
longer applies — the barrier was removed with the optocouplers, and its
checker was deleted rather than left to pass against a rectangle that does
not exist.
The board needed an unplanned stack-up escalation to get there — see "The
escalation ladder" below — which is now closed with every 2-layer concession
given back. The one open item that must be re-checked before placing the
order, not before this review, is the CT burden resistor's stock level (see
"Open items").

## Task 14 DRC results

`kicad-cli pcb drc --refill-zones`, via `kicad_build.py`, on the final
100 × 100 mm / 4-layer / 0805 / rev-A-net-class configuration:

- **0 DRC errors**
- **0 unconnected pads**
- **0 footprint errors**
- **0 warnings.** This line read "109 warnings, all silkscreen" (4
  `silk_edge_clearance`, 24 `silk_over_copper`, 81 `silk_overlap`) through
  every earlier review, waved through as "same kind as rev A". It was not
  cosmetic: `5V / OUT` and `AUX OUT` — labels for screw terminals a user
  hand-wires — printed half off the board edge, and 24 labels sat on exposed
  pads. Silk placement is now derived by `generator/silk.py` rather than read
  from a hand-maintained coordinate table, and `generator/check_silk.py`
  fails the build on any silk over copper or crossing the outline. See the
  README's "Silkscreen is placed by a packer".

Independent checks beyond KiCad's own DRC, all passing:

| Check | Result |
|---|---|
| `check_pinmap.py` (design.py ↔ Kconfig) | 29 GPIO assignments agree |
| `check_sch_bounds.py` (nothing off the declared sheet) | all placed items inside A1 |
| `check_netlist.py` (schematic round-trip) | 93 nets compared, 0 mismatches |
| `check_pcb.py` (independent connectivity) | 2271 copper items checked, ALL CHECKS PASS |
| `check_via_in_pad.py` | PASS |
| `check_canonical.py` (reproducibility) | PASS — rebuild is byte-identical |

`make pcb-check` runs all of the above in one command and is the fastest way
to confirm this review still describes the committed board.

## The escalation ladder

The principal engineering risk in this respin was density: 141 footprints on
the same 100 × 100 mm outline rev A used at 80 mm tall, on a router that had
only ever routed rev A's simpler board. The hardware-design spec's §6.3
pre-agreed an escalation order rather than guessing at a stack-up up front,
and the ladder ran in full:

| Rung | Configuration | Unroutable nets | DRC violations | Unconnected |
|---|---|---|---|---|
| 0 | 100 × 100, 0805, 2-layer | 34 | 149 | 38 |
| 1 | 100 × 100, 0603, 2-layer | 23 | 84 | 32 |
| 2 | 125 × 100, 0603, 2-layer | 9 | 78 | 27 |
| 3 | 100 × 100, 4-layer (see below) | **0** | **0** | **0** |

**2-layer did not close at any rung.** The rung-2 survivors were nine short
local nets boxed in by neighbours' copper in the SSR driver cluster and the
ADE7953 block — the signature of a **layer** shortage, not an area shortage:
growing the board bought 23 → 9 but no further, because more space doesn't
help a net that can't escape its own neighbourhood. Rung 3 (4-layer) was
escalated to rather than attempted autonomously, since it changes fabrication
cost and stack-up, not just generator behaviour.

**Rung 3 closed it, then gave back every concession the 2-layer attempts had
made:**

| Step | Configuration | Unrouted | Unconnected | DRC errors |
|---|---|---|---|---|
| Layer conversion only | 125 × 100, 0603, 0.25 mm tracks | 0 | 0 | 0 |
| Walk back rung 2 (board size) | 100 × 100, 0603, 0.25 mm | 0 | 0 | 0 |
| Walk back rung 1 (passive size) | 100 × 100, 0805, 0.25 mm | 0 | 0 | 0 |
| Walk back net classes | 100 × 100, 0805, 0.3/0.7 mm (rev A's classes) | 0 | 0 | 0 |

Final board: 100 × 100 mm, 4-layer (GND plane on In1.Cu, +3V3 plane on
In2.Cu, neither outer layer poured), 0805 passives, rev A's net classes.
Track widths came all the way back because the router stopped touching
fine-pitch pads directly — each is represented by the far end of a
pre-drawn escape stub, confining 0.25 mm tracks to the ~2 mm around each
QFN-28/TSSOP pad that actually needs it.

Two latent router bugs surfaced and were fixed during the ladder, both in
the same class as an `EN` clearance issue found earlier in the project:
`miter_corners()` chamfering a corner that had a via on it (orphaning the
via), and A* taking a via on `via_ok()` alone, leaving the first segment
after a via unchecked at its start point — invisible at 0.25 mm, and
0.172 mm from a pad at the 0.7 mm power-net width. Both are fixed in
`generator/router.py`.

## BOM/CPL parity check

`generator/gen_jlc.py jlcpcb` output, current as of this review:

```
109 parts to JLCPCB (40 BOM lines), 13 hand-soldered, LCSC verified 2026-08-11
11 unique Extended part(s) -> $33 in feeder fees
JLCPCB placement corrections applied (16)
no through-hole parts in the assembly BOM -> Economic (SMD, top-side) assembly is sufficient
```

Designator sets in `jlcpcb/BOM.csv` (machine-placed) and
`jlcpcb/hand-solder-parts.csv` (hand-fitted) are disjoint and together cover
every assembled designator in `design.py`, less `NOT_ASSEMBLED` (test points,
open solder jumpers, the DNP AC-sense header). Every CPL row has a matching
BOM (or hand-solder) row and vice versa — JLCPCB's upload rejects a CPL
carrying a designator the BOM doesn't have, so this was checked directly
rather than assumed. **Both difference lists are empty.**

Corrected from the design spec's estimate: §6.4 of the hardware-design spec
projected **6 unique Extended parts / $18** in feeder fees. The as-built
board carries **11 / $33** — C107114 (30 pF crystal load caps), C160404
(Qwiic connector) and C165948 (USB-C receptacle) were Basic on rev A's BOM
line but are Extended in the parts actually used here, and the CT front-end
pulled in more Extended parts than originally scoped (the crystal, the
6.8 Ω burden resistor, and the SRV05-4 TVS array's specific LCSC line, in
addition to the ADE7953 itself). Three new subsystems — the ULN2003 aux
bank, the SRV05-4 TVS arrays as a *category*, and the watchdog's AO3401A —
landed at zero feeder cost by being Basic parts; the increase over rev A's
4/$12 is concentrated in the analog/sensing front end and the CT protection
components, not in the parts the spec anticipated.

## PR #301 review round — the clipped schematic

A review of PR #301 found a fab-package defect that every gate in this
document had missed, and it is worth recording *why* it was missed.

**What was wrong.** `gen_sch.py` declared `(paper "A3")` — 420 × 297 mm —
while `SCH_AT` spread the rev B blocks over roughly 565 × 522 mm. Fifty of
the 143 designators fell outside the media box, including the entire ADE7953
CT front-end, the ULN2003 aux bank, and the touch, watchdog and test-point
rows. `pdf/bisque-controller-schematic.pdf` is a fab deliverable and the
artifact a human actually reviews, and roughly 40% of the circuit was simply
not in it. Measured: the old PDF carried 93 designators, the A1 one carries
142.

**Why nothing caught it.** Every checker in `generator/` validates
*connectivity* — `check_netlist.py`, `check_pcb.py`, `check_pinmap.py` (and,
at the time, `check_isolation.py`). Connectivity is complete no matter where a symbol sits on
a page, so all of them stayed green on a schematic that could not be read.
This is the same shape of blind spot as the 0.078 mm drill web recorded
below: a whole class of defect that no existing check could express, rather
than a check that was wrong.

**Fixed.** The sheet is now **A1** (841 × 594 mm). A2 (594 × 420) was
rejected — it is about 100 mm too short in y for the content. A1 is a
standard KiCad paper size, so no `User` dimensions have to survive a round
trip through anyone's plot dialog, and it leaves margin for another block
without a second page change.

**Guarded.** `generator/check_sch_bounds.py` parses the generated schematic,
reads whatever `(paper …)` it declares, and fails if any placed item —
symbol, global label, free text, wire endpoint — falls outside it, allowing
a 10 mm frame border plus 25 mm of label reach on the max sides. It was run
against the A3 declaration first and reported 547 off-sheet items across 62
designators; on A1 it reports none. It runs in `make pcb-check`.

**Also in that round:** `make pcb` was documented as regenerating "fab
outputs" and ran no export step at all, so it could succeed while leaving
the committed gerbers, BOM, CPL and PDFs describing the previous board. It
now runs `pcb-build` → `pcb-fab` → `pcb-check`, with the gerber layer list
pinned to include `In1.Cu,In2.Cu` (a package without them fabricates as
2-layer with every ground and power connection missing) and stale gerbers
deleted before re-export. The minutes-long 3D raytrace moved to its own
`make pcb-render`; nothing in a fab order reads `3d/`.

**And `SJ3`/`SJ4` now exist.** The spec (§5.1) and this board's README both
promised a per-channel solder jumper tying the opto collector to board +5 V,
open by default. It had never been implemented. It was implemented in that
round — and then removed again in the next one, along with the optocouplers
themselves. See below.

## The opto-isolation reversal

**What changed.** `U8`/`U9` (LTV-817S), `SJ3`/`SJ4`, the `ISO_BARRIER`
four-layer pour keepout, the matching router keepout with its per-net
`allow_nets` exemption, `check_isolation.py` and `check_pcb.py`'s barrier
check are all **gone**. Both SSR channels revert to rev A's direct low-side
MOSFET drive: `SSRn_CTRL` → 100 Ω → gate of an AO3400A (`Q5`/`Q6`), source to
GND, drain = the switched low side on `J4`/`J9` pin 2, 10 kΩ gate pulldown for
boot safety, indicator LED across the terminal pair. `J4`/`J9` pin 1 is
`SSR_EN`, board +5 V gated by the watchdog.

**Why.** An optocoupler isolates only if the SSR control loop is powered from
a supply that is not this board. Closing the loop with board `+5V` and board
`GND` — exactly what `SJ3`/`SJ4` existed to permit, and what this
controller's wiring does in practice — puts both sides of the barrier in one
SELV domain and leaves the opto as a sacrificial part in series with the SSR
input. The as-built terminals could not have closed an isolated loop at all:
neither `J4` nor `J9` carried a `GND` pin. Meanwhile the costs were real on
every board: two parts, an ~21 × 24 mm pour keepout on all four copper
layers in the densest corner, a routing keepout on top of it, and a checker.
The owner's decision is that the loop is board-powered, so the isolation is
not preserved by the wiring and is not worth its cost. **Do not re-add
opto-isolation without also specifying an off-board control supply and a
terminal that carries it.**

**The watchdog survived, and moved to the supply side.** `Q3`, the charge
pump (`C38`/`D7`/`C39`/`R46`) and `SJ2` all remain, and still gate both SSR
channels and nothing in the ULN2003 aux bank. `Q3`'s drain is now `SSR_PG`,
the gate of `Q4` (AO3401A, P-channel) in the +5 V feed; `Q4`'s drain is
`SSR_EN`, the rail both terminals hang off; `R47` (100 kΩ) is the fail-safe
pull-up, and `SJ2` now shorts `SSR_PG` to GND. The two-parts-cheaper stacked
low-side arrangement was rejected on arithmetic: at the ESP32's guaranteed
`V_OH` (2.64 V) a channel FET whose source rides on `SSR_EN` has 140 mV of
margin to the AO3400A's lowest guaranteed `R_DS(on)` spec point *before*
subtracting `Q3`'s own drop, and that drop is unbounded by the datasheet at
the 2.16 V gate the pump delivers in the worst corner. High-side drops `Q3`'s
load from ~30 mA to 50 µA — provable from its own `V_GS(th)` test condition —
and puts both switching FETs at or past a guaranteed spec point. Full working
in `generator/design.py`'s watchdog block.

**`check_isolation.py` was deleted, not neutered.** With no barrier there is
nothing left for it to assert; a checker that passes vacuously is worse than
no checker, because it reads as coverage. `check_pcb.py`'s `ISO_BARRIER`
equality assertion went with it. `make pcb-check` is one step shorter and
every remaining step still passes.

**Numbers after the reversal:** 0 DRC errors, 0 unconnected, 0 footprint
errors, 0 warnings (109 silkscreen-only warnings until the silk packer
landed); 141 components; 93 nets, 0 netlist
mismatches; 2271 copper items checked; BOM/CPL designator sets equal at 109,
no line without an LCSC part; gerbers still carry `In1_Cu`/`In2_Cu`.

## Open items

- **Sourcing flag: LCSC `C17774` (6.8 Ω 0805 1% resistor, R31/R34 — the CT
  burden resistors) was down to approximately **970 units** in stock as of
  this review, with no Basic-part alternative at that value/package/tolerance
  found on LCSC. Two are needed per board. **Re-check stock immediately
  before ordering** — at low quantity this is the kind of line that goes to
  zero between review and order without warning, and there is no drop-in
  Basic substitute queued if it does.
- **`CERT-001` — modular certification, carried forward from rev A, with the
  rev B antenna caveat attached.** Rev A's note: "the ESP32-S3-WROOM-1
  carries modular certification." Rev B uses the **WROOM-1U** variant, whose
  modular approval is granted against specific antenna types and gains —
  fitting a non-approved (e.g. high-gain) external antenna on the U.FL
  pigtail steps outside that approval. Confirm the antenna actually populated
  in the field is on Espressif's approved list before treating a rev B unit
  as carrying the module's certification; the certification does not
  automatically extend to an arbitrary U.FL antenna choice the way it did to
  rev A's fixed on-package antenna.
- **The hardware watchdog ships before its firmware kick task.**
  `KILN_PIN_WDT_KICK` (GPIO 36) is defined and wired to the charge pump that
  gates both SSR channels, but nothing in firmware toggles it yet. Every
  rev B board needs the `SJ2` ("WDT DEFEAT") solder jumper fitted until the
  kick task lands, or **the SSRs will not energize under any firmware
  command.** This is a firmware gap, not a fab-readiness blocker — the board
  is correct as designed — but it belongs in bring-up notes for anyone
  assembling a board ahead of the kick task, since it presents as a dead
  board rather than an obviously-missing feature.
- **U7's rotation was wrong — RESOLVED, and this entry called it.** The ADE7953
  carried a **+90° CPL correction** from the old `JLC_ROTATION` table's `^QFN-`
  rule, which this review flagged as community-maintained, not vendor-published,
  and never re-derived. It was **180° out**: fitting LCSC's own LFCSP-28 land
  pattern onto our footprint puts their pin 1 on ours only at **+270°** (worst
  pad 0.075 mm; every other quarter-turn misses by 4 mm or more). A square QFN
  looks placed either way in a preview — the pads overlap — so the error is
  invisible at exactly the part where it is unreworkable. Five other parts were
  wrong the same way; see the note below. The corrections are now derived
  per-part from LCSC's library by `generator/check_jlc_placement.py`, which
  `make pcb-check` runs, and the family table is gone.
- **Six CPL placements were corrected after the assembly preview showed them.**
  U4/D5/D6 (SOT-23-**6**) inherited the 3-pin `^SOT-23 -> 180` rule, but LCSC
  draws that land across the pins rather than along them: **+270°**, a 90° error
  that was visible in the preview. U7 as above. U1 and J1 needed no rotation but
  are the two parts on the board where the two libraries disagree about the
  footprint *origin* — KiCad anchors the WROOM-1U and the USB-C receptacle on
  the body centre, LCSC on the pad pattern — so their CPL coordinates now carry
  **-0.477 mm** and **-1.571 mm** in Y. All six were the parts flagged by eye in
  JLCPCB's preview; the fit reproduced exactly that set and nothing else, which
  is the strongest evidence available that the model is right.
- **Verified against JLCPCB's own SMT DFM, before and after.** Two runs of
  dfm.jlcdfm.com with SMT DFM enabled, on the old and new CPL:

  | SMT DFM check | old CPL | new CPL |
  |---|---|---|
  | Pin without pad | **14** (pictured: D5) | **0** |
  | Lead area overlapping pad (insufficient overlap) | **50** (pictured: U7) | **1** |
  | Lead to hole distance | **16** | **0** |
  | Missing hole for component pin | **2** | **0** |
  | Component through-hole misalignment | **2**, at **1.42 mm** (pictured: J1) | **0** |
  | Component clipped by board outline | 1 warning | 0 |
  | Pin edge past pad edge (4 checks) | 42 | 48 |

  Every "the part is not where its pads are" finding went to zero. J1's measured
  **1.42 mm** through-hole misalignment is the independent confirmation of the
  1.571 mm origin correction — the two differ by the 0.15 mm the two libraries
  disagree on for the shell legs, which is the one part of that footprint no
  placement can fix. The edge findings *rose* because they are only measurable
  once a pin is on its pad at all: findings moved out of the catastrophic
  bucket into the cosmetic one, 85 serious to 1.
- **The one remaining placement finding is U7's exposed pad, and it is correct
  as drawn.** Our land is `EP3.1x3.1`; LCSC models the part's EP as 3.30 SQ, so
  JLC measures 88% overlap and flags it. ADI's own package drawing for the
  ADE7953 (CP-28-10, 5 x 5 mm LFCSP) specifies the EP as **3.14 SQ**
  (3.04-3.24) — our land matches the real package and LCSC's 3.30 model is the
  outlier, 0.06 mm above the package's own maximum. Likewise the 48 pin-edge
  findings are library land-width differences, not misplacement: KiCad draws
  0.5 mm-pitch QFN lands 0.25 mm wide (the package's *nominal* lead width, per
  the same drawing: b = 0.20/0.25/0.30), LCSC draws them 0.28 mm. Widening ours
  to clear the flag would cut the gap between adjacent lands from 0.25 mm to
  0.20 mm, at or below the solder-mask dam JLCPCB can print at this pitch —
  trading a 25 um overhang for a real bridging risk on a 28-pin part. Left as
  drawn deliberately.
- **Measure the watchdog's decay on board 1 — it is a safety-path assumption.**
  `C38` (100 nF), `C39` (1 µF) and `R46` (1 MΩ) are engineering estimates, not
  datasheet-derived, and are labelled `ASSUMPTION` in `design.py`. The
  arithmetic gives a decay through the AO3400A's 1.45 V max threshold of
  **0.40 s** at the ESP32's guaranteed `V_OH` and **0.72 s** typical — inside
  the intended 0.5–1 s band, and the worst corner fails *faster*, which is the
  safe direction. But that is arithmetic. On the first board, confirm `Q3`
  actually conducts and time the drop after the kick stops. All three parts are
  0805 and reworkable if the measurement disagrees. Related: at the guaranteed
  `V_OH` the gate sits at ~2.16 V, below the 2.5 V point where the AO3400A
  datasheet guarantees any `R_DS(on)` — judged benign because `Q3` is a
  ~20 mA return-path switch whose current is set by the 220 Ω/680 Ω series
  resistors, so even several ohms costs under 100 mV against ~2 V of headroom.
- **Datasheet coverage inherited from Task 4's pre-layout risk retirement.**
  The ADE7953's `IRMS`-without-voltage-channel question, the MAX31856
  pinout/filter, and the WROOM-1U CPL rotation/origin were all confirmed
  against real datasheets before layout (see the Task 4 report); this review
  does not re-litigate them, only records that the layout that shipped is
  the one that was cleared.
- **GND via hole-to-hole spacing — RESOLVED, and the original entry here was
  wrong.** This item previously concluded that the tightest hole pair on the
  board was via-to-via at 0.45 mm, which clears JLCPCB's published 0.2 mm
  floor, and that **no change was needed**. That measurement looked at the
  wrong pair. It compared the two GND stitching vias beside J1 with *each
  other* (`(44.0, 28.5)` / `(44.0, 29.25)`, 0.75 mm centre-to-centre, 0.45 mm
  web) and never compared either of them with the **USB-C shield slot** they
  sat next to.

  **The defect (found by an independent third-party board review, not by our
  own pipeline).** J1's shield pads are oval *slots*, not round holes:
  `(size 1 2.1) (drill oval 0.6 1.7)` at global `(43.68, 27.53)` and
  `(52.32, 27.53)`. A slot drill is a capsule — a 0.55 mm segment with a
  0.3 mm radius — so it reaches 0.55 mm further along its long axis than a
  0.6 mm round hole does. Against the stitching vias at `(44.0, 28.5)` and
  `(52.0, 28.5)` (0.3 mm drill) the true web is:

  | Slot | Via | Web |
  |---|---|---|
  | (43.68, 27.53) | (44.00, 28.50) | **0.078 mm** |
  | (52.32, 27.53) | (52.00, 28.50) | **0.078 mm** |

  Nearest slot-axis point `(43.68, 28.08)`; centre distance
  `√(0.32² + 0.42²) = 0.528`; web `= 0.528 − 0.30 − 0.15 = 0.078 mm`. Against
  JLCPCB's published 0.2 mm minimum that breaks out at the drill.

  **Why three checkers stayed silent.** All the copper involved is GND, and
  every check we had was net-aware: KiCad's DRC reported nothing,
  `check_pcb.py` skips same-net pairs by construction, and `router.py`'s
  hole-gap test measured centre-to-centre against `drill/2` — modelling every
  hole as a *circle*, which understates a 1.7 mm slot by 0.55 mm. (Two
  further modelling errors compounded it: `kicad_build.py` collapsed the
  drill to `GetDrillSize().x`, discarding the slot length, and `gen_pcb.py`'s
  `(drill oval …)` parse fell through `num()` to `0.0`, i.e. "SMD pad, no
  hole at all".) **Hole-to-hole is a mechanical constraint at the drill bit —
  net identity is irrelevant to it**, and treating it as an electrical rule
  is what made it invisible.

  **What now guards it.** Two changes, both in the generator — the board file
  is generated and is never hand-edited:
  1. `router.py` models a drill as the capsule it is (`Shape.hole_dist()`,
     fed slot diameter/length/angle and the true hole centre by
     `kicad_build.py` and `gen_pcb.py`), and `via_ok()` enforces
     `HOLE_TO_HOLE = 0.30 mm` against it regardless of net — 0.30 rather than
     JLCPCB's 0.20 floor, for margin on a constraint whose failure mode is a
     broken-out hole discovered at the fab. The four stitching vias moved to
     `(44.0, 29.0)`, `(44.75, 29.75)`, `(51.25, 29.75)`, `(52.0, 29.0)`;
     routing stayed complete at 0 unconnected.
  2. `generator/check_drill_clearance.py` (new, wired into `make pcb-check`)
     re-checks the *finished* board: every drilled aperture against every
     other, pads and vias alike, round and oval, **ignoring nets**, failing
     non-zero below 0.30 mm. It was written before the fix and run against
     the then-current board, where it reported exactly these two 0.078 mm
     pairs and nothing else; after the generator fix it reports
     "492 drilled apertures … no hole-to-hole violations".

  JLCPCB's PCB Capabilities page
  (https://jlcpcb.com/capabilities/pcb-capabilities, fetched 2026-08-11)
  states **"Via Hole-to-Hole Spacing: 0.2mm"**; the previously-cited
  "commonly quoted 0.5 mm" figure was unconfirmed and did not come from
  JLCPCB's own page.

## Not performed / limits on confidence

Carried forward from rev A's review, and not newly re-verified for rev B:

- **SPICE simulation skipped** — no `ngspice`/`ltspice`/`xyce` on this
  machine. Value-computation checks on the SSR gate/indicator resistors, the
  watchdog charge-pump RC and its high-side gate arithmetic, and the CT
  anti-alias filter are
  static (datasheet-arithmetic) only, the same limitation rev A's review
  recorded for its own analog values.
- **Datasheet coverage is not exhaustive.** The parts load-bearing for this
  respin's safety-relevant claims (MAX31856, ADE7953, ULN2003, BAT54S) were
  checked against real datasheets during Task 4 and while writing
  `design.py`'s inline component comments; the AO3400A/AO3401A gate
  arithmetic behind the watchdog topology choice is worked in `design.py`'s
  watchdog block against the published spec points, but no new datasheet
  extraction was done for it. Parts unchanged from rev A
  (AMS1117, AO3400A, WS2812B, USBLC6-2SC6) were not re-verified here and
  carry whatever confidence rev A's review already assigned them.
