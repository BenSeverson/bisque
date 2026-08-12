# JLCPCB Fabrication Readiness Review — Rev B

Board: `bisque-controller` — **4-layer**, 100 × 100 mm, 1.6 mm, 141 components
(109 machine-placed SMD across 41 BOM lines + 13 hand-fitted THT/wafer parts +
4 mounting holes)
Reviewed: 2026-08-11, against KiCad 10.0.5 and the Task 14 board build.
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
`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md` §7 passes,
including the two rev-B-specific ones (isolation barrier, pin-map agreement).
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
- **102 warnings, all silkscreen** (2 `silk_edge_clearance`, 24
  `silk_over_copper`, 76 `silk_overlap`) — same category and same order of
  magnitude as rev A's silkscreen-only warning set; nothing new in kind.

Independent checks beyond KiCad's own DRC, all passing:

| Check | Result |
|---|---|
| `check_pinmap.py` (design.py ↔ Kconfig) | 29 GPIO assignments agree |
| `check_isolation.py` (opto barrier, all 4 copper layers) | 4 isolated nets, barrier intact |
| `check_netlist.py` (schematic round-trip) | 96 nets compared, 0 mismatches |
| `check_pcb.py` (independent connectivity) | 2332 copper items checked, ALL CHECKS PASS |
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
109 parts to JLCPCB (41 BOM lines), 13 hand-soldered, LCSC verified 2026-08-11
11 unique Extended part(s) -> $33 in feeder fees
JLCPCB rotation corrections applied (11)
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
bank, the LTV-817S optocouplers, and the SRV05-4 TVS arrays as a *category*
— landed at zero feeder cost by being Basic parts; the increase over rev A's
4/$12 is concentrated in the analog/sensing front end and the CT protection
components, not in the parts the spec anticipated.

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
- **Datasheet coverage inherited from Task 4's pre-layout risk retirement.**
  The ADE7953's `IRMS`-without-voltage-channel question, the MAX31856
  pinout/filter, and the WROOM-1U CPL rotation/origin were all confirmed
  against real datasheets before layout (see the Task 4 report); this review
  does not re-litigate them, only records that the layout that shipped is
  the one that was cleared.
- **GND via hole-to-hole spacing — checked against JLCPCB's published
  capability, not just assumed.** Two via pairs on the board (e.g.
  `(44.0, 28.5)` / `(44.0, 29.25)`) sit 0.75 mm centre-to-centre with 0.30 mm
  drills, i.e. a 0.45 mm hole-edge-to-hole-edge gap. `router.py`'s own
  hole-gap constant (`router.py:278`) enforces only 0.30 mm, so this pair is
  the tightest on the board relative to what the router itself requires.
  JLCPCB's PCB Capabilities page
  (https://jlcpcb.com/capabilities/pcb-capabilities, fetched 2026-08-11)
  states **"Via Hole-to-Hole Spacing: 0.2mm"** (a separate, larger 0.45 mm
  figure is listed for *pad*-to-pad hole spacing, which doesn't apply here —
  these are plain vias, not pads). 0.45 mm clears the 0.2 mm via minimum with
  margin, so **no layout change was made**; the previously-cited "commonly
  quoted 0.5 mm" figure was unconfirmed and did not come from JLCPCB's own
  page.

## Not performed / limits on confidence

Carried forward from rev A's review, and not newly re-verified for rev B:

- **SPICE simulation skipped** — no `ngspice`/`ltspice`/`xyce` on this
  machine. Value-computation checks on the new opto LED current-limiting
  resistors, the watchdog charge-pump RC, and the CT anti-alias filter are
  static (datasheet-arithmetic) only, the same limitation rev A's review
  recorded for its own analog values.
- **Datasheet coverage is not exhaustive.** The parts load-bearing for this
  respin's safety-relevant claims (MAX31856, ADE7953, LTV-817S, ULN2003,
  BAT54S) were checked against real datasheets during Task 4 and while
  writing `design.py`'s inline component comments; parts unchanged from rev A
  (AMS1117, AO3400A, WS2812B, USBLC6-2SC6) were not re-verified here and
  carry whatever confidence rev A's review already assigned them.
