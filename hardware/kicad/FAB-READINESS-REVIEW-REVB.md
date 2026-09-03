# JLCPCB Fabrication Readiness Review — Rev B

Board: `bisque-controller` — **4-layer**, 100 × 100 mm, 1.6 mm, **143 components**
(108 machine-placed SMD across 38 BOM lines + 13 hand-fitted THT/wafer parts +
4 mounting holes + 3 fiducials + 15 non-assembled features: 12 test pads,
2 solder jumpers, 1 DNP header)

Review lineage:
- 2026-08-11 — first pass, against KiCad 10.0.5 and the Task 14 board build
- 2026-08-12 — after the PR #301 fix wave (schematic sheet size + `SJ3`/`SJ4`)
- 2026-08-12 — after the **opto-isolation reversal** (removed `U8`/`U9`,
  `SJ3`/`SJ4`, the pour keepout, the router keepout and `check_isolation.py`;
  added `Q4`/`Q5`/`Q6`/`R47`)
- 2026-08-17 — full re-review after the fiducial / SRV05-4 /
  oscillator / pour / silk / schematic-fusing wave. Schematic `2f322e8e…`,
  board `2f26da9b…`, working tree clean at `75c551d`.
- **2026-09-02 — current.** Pre-prototype review of the board as committed at
  `7fa2fd9` (TLV1117LV33, SN74LVC1G123 one-shot, derived block legends):
  16 independent review lenses plus direct re-measurement of every
  medium-and-above finding. Everything from "## Verdict" onward below is the
  2026-08-17 round, preserved as written; the new round is the section that
  follows this list.

Rev B is a respin, not a variant: the thermocouple front-end, module variant,
output bank, and layer count all changed, and no attempt was made to keep rev A
hardware compatible with rev B firmware defaults. The one item that carries
forward unchanged is `CERT-001`, below.

## 2026-09-02 round — pre-prototype review

**Ask:** review the schematic and PCB before the first prototype run — layout,
silkscreen legibility, routing quality, circuit completeness — and say whether
the board will be unusable or need significant rework.

### Verdict

**Nothing makes the board unusable, and every subsystem is wired to its
datasheet. But this exact package should not be ordered as-is.** Ten defects
are one-line edits in `design.py` / `gen_pcb.py` and one `make pcb` (~6 min)
before the order, and each of them is a bodge, a filed hole or a wiring trap
after it. Two firmware items gate board 1 regardless of hardware. One process
gate the working-tree README described did not exist — the JLC rules file was
silently ignored by KiCad — and is now fixed, tracked and self-testing (A11,
`124ba4f`): the board passes JLC's process for real rather than vacuously.

### Status, 2026-09-02 evening (branch `hw/rev-b-prefab-fixes`)

Most of section A is landed, and the architecture changed underneath it: the
board now takes **24 V** and makes its own 5 V (`U11`, XL1509-5.0), which was
not in the review at all. That collapses four separate rev-B1 items - the
`+5V` rail stopped being "the input minus D1", so the WS2812B threshold, the
SSR drive and the relay coil no longer move with the installer's trim pot.

| Item | State |
|---|---|
| A1 mounting-hole grid | **fixed** - true 90 x 90; fixing the board beat fixing four doc sites |
| A2 TP11 in J12's column | **NOT fixed**, deliberately - assertion added, debt declared in `gen_pcb.TP_LEGEND_OK`, three placements tried and each left a different net unroutable |
| A3 J11 marks | **attempted, reverted** - see below |
| A4 chip-select pull-ups | **fixed** - R50-R53 |
| A5 display SDO | **fixed** - R56 |
| A6 exposed-pad vias | **fixed** - `EP_VIA_GRID`, U7/U2/U1, derived from real pad geometry |
| A7 ADE REF decoupling | **fixed** - 103.1 mm / 9 vias -> 15.4 / 2, by promoting it out of the late analog group |
| A8 USB_DN detour | **resolved** - now 33.2 mm / 5 vias against USB_DP's 50.8 / 8; the review measured 94.0 / 7. The intervening re-routes took it out |
| A9 TC2 filtered legs | **fixed** - TC2_P_F 47.6 mm / 6 vias -> 17.4 / 2, now within a millimetre of channel 1 |
| A10 CT channel A | **fixed** - R59/C40, U7 pin 6 off GND |
| A11 `.kicad_dru` | fixed previously (`124ba4f`) |
| C: VIN overvoltage | **fixed** - F1 + D8, scaled to 24 V (an SMAJ5.0A on a 24 V rail is a short) |
| C: display loom damping | **fixed** - R54/R55/R57/R58 |
| C: VP/VN floating | **fixed** - R60/R61 |
| C: `WDT_OK` pulldown | **fixed** - R49, and the design note that argued against it was wrong in the fail-dangerous direction |
| C: 5 V relays under-driven | **moot** - 24 V coils |
| C: WS2812B margin | **fixed** - D3 is silicon now, not an SS14; a *regulated* 5.0 V rail made the old Schottky a 10 mV margin |
| C: return/stitching vias | one added under J7; the broad 220-of-232 item is open |
| C: `+5V` single power vias (Track 3 #7) | **attempted, not landed** - see below |

**Why `+5V` still transitions layers on single vias.** A post-routing pass was
written and measured: **0 added, 13 had no room.** Two things kill the cheap
version, and the second is the real one:

- Adjacent grid cells are 0.25 mm apart where two 0.6 mm vias need >= 0.8 mm,
  so the neighbour search never finds a legal cell.
- More fundamentally, a via at any *free* cell is not connected to the rail on
  either layer. Paralleling a transition means the rail must have copper at
  the companion's position on BOTH layers, which needs a short spur on each -
  new router capability, not a placement tweak. It belongs in `_commit`, where
  the path is in hand, and that is an inline change to the hot loop of a
  router this board has repeatedly punished for taking space early.

The rails work as they are - roughly 1 A of via for a sub-1 A rail. This is a
redundancy item, not a capacity one.

Gates: 0 nets unrouted, **0 DRC violations**, silk 0/0/0, netlist round-trip
102 nets / 0 mismatches, all 13 `make pcb-check` checkers pass. Every new part
except D8/F1/L1 reuses an existing feeder, so the BOM gained three fee-bearing
lines ($9), not fourteen.

**Why A3 was reverted.** J11's four marks are x-locked over their own pins and
south of J11 is 0.61 mm of board edge, so the only fix is to open the northern
gap - which means moving J5/J6/J7. That was tried and it works: the gap goes
1.57 -> 3.07 mm and the marks fit at 1.0 mm. It also cascades, and every step
of the cascade cost something:

1. moving the header row 1.5 mm north collides with the display damping
   resistors, so those move up 2.0 mm;
2. which puts R52/R57's reference designators on J9's silk outline (3
   `silk_overlap` warnings), so those two move south of J5;
3. which re-rolls the route enough to leave USB_DP and CC1's hand seeds
   dangling - 2.3 mm and 3.3 mm of unconnected copper on USB signals, the
   failure mode `USB_STUB_TERMS` exists to prevent.

Two antenna stubs on USB is a worse board than four legible-but-cramped
labels, so this is reverted. It is a placement exercise for a spin that is
re-laying that edge anyway, not a pre-fab silk fix.

**The 180 deg silk rotation from section D does not work and should be struck
from the review.** It was implemented and reverted. Rotating the text gives a
board in neither orientation: gr_text rotates, reference designators rotate in
the file and render upright anyway (KiCad's KeepUpright flag normalises them),
and the flame is a gr_poly that rotates with nothing - so the nameplate ends
up upside-down under a right-way-up logo. Consistency would need KeepUpright
off on every designator and the brand mark inverted, both worse than the
problem. The reasoning is recorded in gen_pcb.py above the silk tables.

Still to do before ordering: **A3** (above), the broad **stitching-via** item
(220 of 232 signal vias have no GND via within 1.5 mm), and the rest of the
silk batch - block names still print in the 1.2-2.1 mm gaps between the
8.6 mm terminal blocks, and the per-terminal marks are still at JLC's 0.8 mm
floor where 1.0 mm would read better.

Decision path:

1. Land the ten remaining "fix before ordering" edits (A11 is done), run
   `make pcb`, re-run this review's spot checks (they are all scripted
   below), order.
2. Or order as-is and accept: two filed mounting holes, four bodged pull-ups,
   one trace cut if the display's SDO turns out not to tri-state, an ADE7953
   with an ungrounded thermal pad, and a CT terminal whose silk invites a
   wiring error.

### Verification basis

| Gate | Result (2026-09-01/02, KiCad 10.0.6) |
|---|---|
| `kicad-cli pcb drc --severity-all --schematic-parity` | 0 violations, 0 unconnected, 423 parity warnings (see hygiene) |
| `kicad-cli sch erc --severity-all` | 1 error (U3/U5 SDO both `Output` on SPI_MISO — expected on a tri-state bus), 202 warnings (power-symbol cache, off-grid, VIN/VLED label aliasing) |
| `make pcb-check` — all 13 checkers | exit 0 (93 nets, 0 mismatches; 29 GPIOs agree with Kconfig; 478 apertures, min web 0.300 mm; gerbers.zip current) |
| `gen_jlc.py` vs committed `jlcpcb/*.csv` | byte-identical |
| kicad-happy analyzers (schematic, PCB `--full --proximity`, gerber, cross, EMC, thermal @ 50 °C) | run fresh; every error-level finding triaged (see refuted list) |
| Review lenses | 16 of 17 independent lenses returned (power, ESP32, thermocouple, ADE7953, SSR/watchdog, aux/buzzer/LED, inputs/I²C/headers, PDN/thermal, analog/crosstalk, USB/ESD/return, silk visual, silk geometric, DFM/BOM/CPL, mechanical, routing, firmware/bring-up); the delta/hygiene lens was done by hand |
| Independent re-measurement | every medium-and-above finding re-measured with `pcbnew` / `kicad-cli` / datasheet text before it appears below; low/nit items are reported as the reviewers stated them |
| Datasheets read | SN74LVC1G123 (TI SCES586E), TFOM 3.579545 MHz XO, TLV1117LV, ADE7953 Rev C, MAX31856, ESP32-S3 module v1.8 + series v2.2, WS2812B, ULN2003A, AO3400A/AO3401A, LCDWIKI MSP4021 schematic (QDtech 2019-09-27) and ST7796S v1.0 (fetched), EasyEDA symbol data for the three diodes and two LEDs |

### A. Fix before ordering — each is a generator edit and one `make pcb`

| # | Finding | Measured | Fix |
|---|---|---|---|
| A1 | **Mounting-hole grid is 89 × 90 mm, not the 90 × 90 mm the enclosure README and door template drill** | `H1` (25.5, 25.0), `H2` (114.5, 25.0), `H3` (25.5, 115.0), `H4` (114.5, 115.0); `generate_panel_template.py` `PCB_HOLE_GRID = 90.0` | `design.py`: H1/H3 x = 25.0, H2/H4 x = 115.0 (nothing lies within 3.6 mm of the holes); or set the template to 89 × 90 for this build |
| A2 | **TP11's `CT A+` legend prints inside J12's terminal-mark column, 0.4 mm above the `A-` screw mark** — the CTA_N screw reads as both `CT A+` and `A-` | `CT A+` at (106.50, 85.70), box y 84.95–86.45; `A-` at (107.38, 86.92) = J12 pad 2 (CTA_N) | Move TP11 out of the legend strip (west of D6 or south of J12) or set `TP_LABEL_AT["TP11"]` north/west of the pad; add a `kicad_build.py` assertion that no TP label lands in a connector's `PIN_LEGENDS` column |
| A3 | **J11's `IN1 IN2 IN3 GND` marks are wedged between connector bodies** | text boxes y 107.03–108.53; J6/J7 silk outline bottom 107.05, J11 silk top 108.62 (0.02 / 0.09 mm); wire entry faces the edge so there is no other side | Move the J5/J6/J7 row ~1.5 mm north in `design.py` and print these four at 1.0 mm; give J11 a block name |
| A4 | **No pull-up on any SPI chip select, and current firmware never drives two of them** (`TC2_CS` GPIO35, `T_CS` GPIO5) | nets have exactly U1 + slave; GPIO 5/8/10/35 have no pull at reset (ESP32-S3 DS Table 2-1); `main.c` configures only TC1_CS and LCD_CS | Four 10 k to +3V3 (TC1_CS, TC2_CS, LCD_CS, T_CS). Board 1 without them: drive GPIO35 and GPIO5 high before `spi_bus_initialize()` |
| A5 | **Display SDO is hard-wired to the shared SPI_MISO (J5.9) with no series or DNP element**; the ST7796S datasheet never states SDO goes high-Z when deselected, the module has no series resistor, and the thermocouples share the line | `design.py` J5 pin 9 = SPI_MISO; R39–R43 damp only the five touch lines | 33 Ω (or DNP 0 Ω) in series on J5.9. Bring-up: scope TP6 with the panel plugged in while TC1 is selected; cut J5.9 if MISO is not released |
| A6 | **U7 ADE7953 exposed pad has no vias** (datasheet Table 5: "Connect the pad to AGND and DGND"; prior-review item 2, still open) | 0 vias in the 3.1 mm pad, nearest GND via 3.36 mm; `PULL_LOW` does not enter the pad | Exempt exposed pads in `check_via_in_pad.py` and drop a 2×2/3×3 grid of 0.3 mm GND vias via `MANUAL_VIAS`. Same policy fix gives U2's tab (nearest +3V3 via 1.5 mm, Tj ≈ 94 °C at 50 °C ambient, prior item 3) and U1's thermal pad (Espressif draws 9 vias; nearest GND via 1.0–2.5 mm) their vias |
| A7 | **ADE7953 REF decoupling reaches pin 13 through 36–42 mm of copper and 6 vias**, 10 mm of it 0.2 mm from I²C_SCL | pin 13 (96.00, 74.38); C34 (93, 79) 41.7 mm path, C33 (89, 79) 36.5 mm; net 42.3 mm total. Datasheet p.68: ceramic caps "closest to the ADE7953" | Seed/route `ADE_REF` first with a direct run south to C34 (move C33/C34 to ~(96, 77.5)); target < 5 mm, 0 vias. Same treatment for `ADE_VINTD` (12.7 mm, 2 vias) |
| A8 | **USB_DN detours 60 mm through the SSR/watchdog band** — a regression from the one-shot rebuild; the README still claims a 0.28 mm pair skew | USB_DP 38.1 mm / 5 vias, y ≤ 42.1; USB_DN 94.0 mm / 7 vias, y to 72.5, 69 mm outside `USB_KEEPOUT`; pad-to-pad 32.95 vs 90.0 mm | Seed DN alongside DP (`USB_SEEDS`) or promote the pair to route first; correct README "stack-up" paragraph and `gen_pcb.py:357`. Electrically harmless at Full Speed, but it is exactly the routing the docs say does not exist |
| A9 | **Channel-2 thermocouple filtered nodes are 2–3× longer than channel 1 and loop into the ADE7953 corridor** | TC2_P_F 34.7 mm / 5 vias, TC2_N_F 44.3 mm / 4 vias vs TC1 15.3 / 2 and 21.8 / 3; loop reaches y 62.8 | Promote `TC2_*_F` (and `TC2_N`) ahead of the ADE/I²C nets or seed direct escapes from U5 pins 2–4 toward R17/C20/C22; target ≤ 15 mm, ≤ 2 vias per leg |
| A10 | **CT channel A is single-ended but the ADE7953 limits single-ended IAP to ±250 mV** (Table 5 pins 5/6, p.20); channel B is allowed ±500 mV | 5.1 Ω burden: 250 mV pk = 34.7 mA rms → **69 A rms** full scale for a 2000:1 CT (channel B: 139 A). Fine for a kiln zone; wrong in the README and in any shared calibration constant | Make channel A differential (R + 33 nF on IAN like IAP, IAN off GND) or document the per-channel full scale and calibrate separately in firmware |
| A11 | **RESOLVED in `124ba4f`.** **`bisque-controller.kicad_dru` was silently ignored by KiCad** — the last rule's `(condition "…")` string spanned two lines, and kicad-cli drops the whole file without a message. The README credited the DRC report to these rules; the file was also untracked | Sentinel test on a copy: committed file + `track_width (min 5mm)` → **0** violations; sentinel alone → 398; condition joined onto one line → sentinel fires 199×, board passes JLC rules with 0 | Done: condition joined onto one line, file tracked, and `kicad_build.py::verify_dru_loaded()` now appends that sentinel to a scratch copy of board+project+rules on every build and fails the build if it does not fire (one extra `kicad-cli pcb drc`, 2.27 s). `bisque-controller-drc.rpt` regenerated: still 0 violations, now with the rules genuinely loaded |

### B. Firmware gates for board 1

- **MAX31856 driver (RB-1, #306).** `components/thermocouple/thermocouple.c` is the rev A MAX31855 driver: SPI mode 0, one 32-bit read, no register writes. The MAX31856 needs CPHA = 1, CR0/CR1 configuration and a fault decode; until it lands every board reads a permanent TC fault and `safety_task` trips after 5 s. Keep the device clock ≤ 5 MHz on the shared bus (it is 1 MHz today).
- **Drive every chip select high at boot** (A4) before the display's 40 MHz bursts start.
- **Active buzzer driven with a 4 kHz PWM (RB-14, #342).** BZ1 is an active TMB12A05; drive GPIO7 as a level.
- **Status LED data floats until `status_led_init`** runs after Wi-Fi init; expect random colours at boot (cosmetic).
- **Bench checklist predates rev B**: add SJ2-open, lid-jumper-or-`-1`, PSU-voltage-before-landing-the-wire, and driver-state steps.

### C. Fix in rev B1 — real margin or robustness cost, not blocking

- **No overvoltage protection on VIN.** U2 is 6 V abs-max, +5V = VIN − ~0.4 V; a 12/24 V aux supply landed on J2 by mistake takes out U2, LED1 and the display. Silk `5–6 VDC ONLY` at J2 now; SMAJ5.0A + PTC on the next spin.
- **5 V relays on the aux bank are under-driven.** With SJ1 bridged, a coil sees +5V (≈4.6 V) minus the ULN2003 Darlington drop (0.9–1.1 V at 100–200 mA) ≈ 3.5–3.7 V, below a typical 3.75 V must-operate. Feed `AUX_VP` from VIN ahead of D1, or specify relays with ≤ 3.5 V must-operate. Document a simultaneous-current rule for U6 (the 500 mA figure is per channel, one channel on).
- **WS2812B data margin is PSU-dependent.** VIH = 0.7·VLED; at VIN 5.0 V → VLED ≈ 4.3 V → VIH 3.0 V against a 3.3 V drive; at VIN ≥ 5.35 V the margin is gone. Trimming the PSU up to help the SSR/relay drops hurts the LED; a 74AHCT1G125 on +5V or a second diode in VLED removes the trade.
- **SSR input voltage is ≈ 4.5 V** (VIN − D1 − Q4 − Q5): fine for 3–32 V-input SSRs, thin for parts specified "5–24 V" with a 4 V must-operate. Note it in the enclosure BOM.
- **+5V changes layers through single 0.6/0.3 vias** — (44.0, 59.0) and (41.25, 70.0) are each the only path to Q4/J5/D3/BZ1/C11/R47. ≈1 A-class vias for a < 1 A rail, so it works, but power transitions should get two vias in the router.
- **Layer transitions have no local return** (prior item 5, still open): 220 of 232 signal vias lack a GND via within 1.5 mm; SPI_SCLK 8/8, USB 12/12, I²C 14/14. Add stitching vias at the fast-net transitions and a 100 nF GND–+3V3 cap at each cluster.
- **The display loom carries 40 MHz SCLK/MOSI/MISO with no series damping**; only the touch lines got 33 Ω. Add 22–33 Ω on SCLK/MOSI/DC/CS at J5, or lower the clock. The nav loom (J6) lands straight on GPIO38–42 with no series R, cap or TVS; D5 protects J11 but nothing protects J6.
- **SSR outputs have no transient protection** (documented candidate); Q5/Q6 are 30 V parts on a long off-board loom.
- **`WDT_OK` has no pulldown**; the design note says R47 covers a floating Q3 gate, but R47 holds `SSR_PG`, not the gate. Harmless (Q5/Q6 are held off independently) — 100 k on `WDT_OK` is belt-and-braces. One-shot worst-case window is nearer 1.45 s than the documented 1.65 s once C38's X5R bias derating is included; the 1.1 s firmware budget still fits.
- **VP/VN float unless the DNP J13 is fitted** — two resistors to GND remove the floating PGA inputs the datasheet gives no guidance for.
- **Cold junction is 17 mm from the MAX31856 die** with U1 20 mm away; measure the gradient on board 1 before trusting ±1 °C.

### D. Silkscreen — the explicit ask

Correct and unambiguous: all 50 per-terminal marks sit on their own pad's axis with zero error; `+`/`-`, `5V`/`OUT`, `V+ 1 2 3`, `K+`/`K-`, `A+ … B-` all match their nets; buzzer `+` is over pad 1 (+5V); LED1's pin-1 mark is at the chamfer; `RESET`/`BOOT`, `WDT DEFEAT`, `STATUS`, `USB`, `PWR` are nearest the part they name; no silk on pads or fiducial windows; hidden references are exactly H1–H4/FID1–3.

Problems, best first: A2 (TP11 in the CT column), A3 (J11 marks), then:

- `SSR2`, `AUX OUT`, `SSR1` block names print in the 1.2–2.1 mm gaps between 8.6 mm-tall terminal blocks (`SSR2` is 0.02 mm from J9 and 0.36 mm from J4); readable only from directly above. Put the block name where the reference designator sits on the east side (hide J2/J4/J9/J10 refs) or rotate it.
- `5V IN` has no rating; U2 dies above 6 V. Add `5–6 VDC`.
- In the enclosure's specified orientation (south edge up) **every legend reads upside-down**. A 180° text rotation in `gen_pcb.py` costs nothing.
- Header pin-name rows sit 0.5 mm from the KK bodies and run together; J5/J6/J7/J11 carry no block name.
- Reference designators nearer a neighbour than their own part: C15/C16, LED2, TP11, R33, R9, J6, R44. `TP9`/`TP10` labels `SSR1`/`SSR2` share a row with LED3/LED4's designators 28 mm from the SSR blocks.
- 185 of the texts are at JLC's 0.8 mm absolute floor with a 0.16 mm stroke; the per-terminal marks would be worth 1.0 mm.
- `5V IN` is 1.75 mm from FID1's centre — outside the 1 mm window, but close.

### E. Routing quality — the explicit ask

Complete: 0 unconnected, 0 DRC at `--severity-all --all-track-errors`, every fine-pitch track ≥ 0.200 mm from a foreign pad, all copper ≥ 0.55 mm from the edge, inner planes each one solid polygon, outer-pour fragments all anchored (island removal = always), broadside coupling nil (two planes between F and B), USB shield-slot web 0.524 mm (prior 0.078 mm defect closed).

Defects: A7 (REF), A8 (USB_DN), A9 (TC2 filtered legs), and the single power vias and missing return vias in section C. Cosmetic: nine collinear same-net overlaps and eight near-parallel stub overlaps from the router; 110 silk items over tented vias; 30+ foreign-net segments through the pour-only `USB_KEEPOUT`.

### F. Documentation and hygiene

- `gen_pcb.py` SILK comment: "SJ2 must be FITTED on this rev — nothing kicks the watchdog GPIO yet" — the opposite of `jlcpcb/README.md` and `pin-assignments.md`. `wdt_kick.h` still says the one-shot "gates BOTH SSR opto channels".
- README and `design.py` still describe AMS1117 headroom and a `VLED ≈ 4.6 V` that ignores D1; README/CLAUDE.md quote the pre-regression USB skew.
- `docs/pin-assignments.md` describes a `+3V3` pin on J11 that does not exist; `lid_state.h` says the default lid GPIO is 21.
- Title-block date is hard-coded `2026-07-20` (`gen_sch.py:1881`, `kicad_build.py:198`).
- ~~In-repo `bisque-controller-drc.rpt` predates the board commit and cannot contain the rules the README credits it with (A11).~~ *FIXED in `124ba4f`* — regenerated by `make pcb-cosmetic`; it now does carry them, and still reports 0.
- ~~`bisque-controller.kicad_dru` is untracked.~~ *FIXED in `124ba4f`* — now tracked. (A Freerouting experiment — `bisque-controller-freeroute.*`, two `.dsn` files and a `.lck` — sat untracked beside it when this review started and was removed during it; that board was never the one reviewed.)
- Schematic parity (423 warnings): PCB footprints carry no library nickname or MPN field, local-label nets are `/X` in the schematic and `X` on the board. A GUI "Update PCB from Schematic" would rename 114 nets; the generator should emit both.
- Datasheets still missing on disk: SRV05-4, SS34, SS14, 1N4148W, C12891.
- Feeder-fee accounting in the README is stale (8 fee-bearing Extended parts, not 6); C17408 appears on two BOM rows as `100R 1%` and `100R`.

### G. Confirmed correct

Every pin of U1 (41), U3/U5 (14 each), U7 (29), U10 (8), U6 (16), U4/D5/D6, Y1, Q2–Q6, D1–D4, LED1–4 and every connector was checked against its datasheet or the module vendor's document, not the KiCad symbol. In particular: U10 pin 5 is the true Q (the DCT package has no Q̄), Y1's floating enable means "oscillation out", BIAS on the thermocouple side of the 100 Ω matches MAX31856 Figure 8, IAP/IAN/IBP/IBN/VP/VN/REF/VINTA/VINTD/PULL_HIGH/PULL_LOW numbering matches ADE7953 Figure 4, the EN and IO0 networks are the module datasheet's, GPIO46 is safe (the MSP4021 has no pull-up on RESET; its logic is 3.3 V via an XC6206; its LED pin is a transistor base), diode and LED polarity in the CPL matches LCSC's pad numbering (SS34/SS14/1N4148W pin 1 = K; LEDs via `PIN_REMAP`), TLV1117LV output/input capacitance and stability, the watchdog failure-mode table (kick stopped / stuck high / stuck low / MCU in reset / +3V3 lost), the 5 Hz kick against the 900 ms heartbeat, `SSR_EN` off through boot, all wire-entry faces off-board, M3 hardware clearance, JLC copper/mask/paste/fiducial capabilities, BOM/CPL/hand-solder set arithmetic (109 + 13 + 22 = 144), and every BOM line's LCSC value/package/rating.

### H. Refuted or downgraded

- "GND plane split into 3 islands" / "+5V plane split" (cross-analysis) — no +5V plane exists; In1.Cu is one polygon; outer-pour fragments are all connected.
- "GPIO46 strapping conflict from a display pull-up" — the QDtech schematic shows no pull-up on TFT_RESET; low, provision only.
- "Keepout violations" (36), reference-plane gaps (77), IO filtering (8), DC diff-pair skew (15), LED1 no resistor — analyzer artefacts, as triaged in the 2026-08-17 round.
- "SDO/SDO output conflict" (ERC) — MAX31856 SDO is high-Z when CS is high (Table 5); the bus is legitimate.

### I. Sourcing snapshot (jlcsearch, 2026-09-02)

All BOM lines in stock. Thin lines to re-check at order time: Molex 22272081 (J7) 754, XD-2510-14A (J5) 1 271, WJ500V 4-pos (J10/J11/J12) 1 852, A2547WV-6P (J6) 3 058, ESP32-S3-WROOM-1U-N16R2 3 507, ADE7953 4 846, XO 6 566, SM04B-SRSS-TB 7 284, MAX31856 7 744, SN74LVC1G123 8 800.

### J. Not performed / limits

- One review lens (delta/hygiene) never returned from the multi-agent run; its scope was covered by hand in F and I.
- Adversarial verification was applied to medium-and-above findings only; low/nit items are the reviewers' claims with their stated evidence.
- No SPICE (no simulator installed); no thermal simulation — Tj figures use JEDEC RθJA; no CT or thermocouple was measured.
- Vendor figures recalled rather than fetched: SSR must-operate voltages, relay must-operate, SS34/SS14 Vf curves, C12891 DC-bias curve.
- Whether this ST7796S module tri-states SDO is unproven either way (A5 is the hedge).


## Verdict

**No new blockers. The fab package is internally consistent and matches the
current sources.** Every gate that the prior review passed still passes, and the
one that mattered most for this wave — the schematic changed twice *after* the
board was last generated — is verified clean: `check_netlist.py` compares 92 nets
with 0 mismatches, so the net-fusing commits (`842da7c`, `75c551d`) changed
drawing only, not connectivity.

Nothing below is a reason to hold an order. Items 1–3 are margin and
robustness items worth resolving on the next board build; 4–7 are cheap
housekeeping.

## Verification basis

What the claims in this report actually rest on:

| Gate | Result |
|---|---|
| KiCad DRC (`bisque-controller-drc.rpt`) | 0 violations, 0 unconnected pads, 0 footprint errors |
| `make pcb-check` — all 12 checkers | **exit 0** |
| ├ `check_netlist.py` schematic↔board | **92 nets compared, 0 mismatches** |
| ├ `check_silk.py` | over-copper 0, off-board 0, silk-on-silk 0, under-a-part 0 |
| ├ `check_pinmap.py` (design.py ↔ Kconfig) | 29 GPIO assignments agree |
| ├ `check_mpn.py` (schematic ↔ gen_jlc.LCSC) | 121 sourced parts match, 22 unsourced |
| ├ `check_via_in_pad.py` | no via encroaches an SMD pad |
| ├ `check_drill_clearance.py` | 476 apertures, min web 0.300 mm |
| ├ `check_placement.py` | 0 courtyard overlaps, 0 parts outside board |
| ├ `check_jlc_placement.py` | 108 parts / 36 LCSC land patterns fitted |
| ├ `check_gerber_zip.py` | `jlcpcb/gerbers.zip` matches `gerbers/` (14 files) |
| ├ `check_canonical.py` | idempotent, uuids unique (4655) |
| └ `gen_datasheet_manifest.py --check` | manifest current — 10/14 present, 4 missing |
| Analyzers (fresh, run `2026-08-17_1938`) | schematic, PCB `--full --proximity`, cross-domain, EMC, thermal, gerber |

Fab-output freshness: `gerbers/`, `gerbers.zip`, `BOM.csv` and `CPL.csv` carry
mtimes older than the board file, which looks alarming and isn't — git shows the
board's *content* last changed in `98e386f`, the same commit that regenerated
the gerbers. The later commits touched the schematic only.

Datasheets read directly for this review: **AMS1117** (dropout, Note 4),
**ADE7953 Rev C** (Table 5 / Figure 4, EPAD), **AO3400A / AO3401A** (SOT-23 pin
diagram).

## Findings

### 1. LDO headroom is thin, and every analyzer overstates it — *medium*

`+5V` is not 5.0 V. The rail sits behind the ORing Schottky D1 (SS34), so U2's
input is roughly `VIN − 0.4 V ≈ 4.6 V`. Every tool in the run assumed 5.0 V
(`rail_voltages`, `power_budget`, `analyze_thermal`), so all of them are
optimistic about the input side.

The AMS1117 datasheet guarantees dropout **only at 0.8 A: 1.1 V typ, 1.3 V max**,
with Note 4 stating no figure is specified above that and the general description
promising only that it decreases at lower current. Taking the guaranteed worst
case, U2 needs 3.3 + 1.3 = **4.6 V in — exactly what is available, with zero
margin**. Typical dropout at the ~250–400 mA this board draws is well under that,
so the rail will almost certainly behave; the exposure is a 5 V supply at the
low end of its tolerance, or cable drop on USB, coinciding with an ESP32-S3
Wi-Fi TX burst.

Not a fab blocker — it is a first-article measurement. Suggest measuring `+3V3`
at TP under sustained Wi-Fi TX from the lowest-spec supply you intend to
support, and specifying ≥4.9 V for the J2 adapter.

*Caveat:* the 0.4 V Schottky drop is a conventional figure — **no SS34 datasheet
is on disk** (see finding 6), so that number is unverified.

### 2. U7 (ADE7953) exposed pad has zero vias — *medium*

Pad 29 is 3.10 × 3.10 mm on GND; the nearest GND via is **3.36 mm away**, so the
EP reaches the ground system only laterally through the F.Cu pour. The datasheet
is explicit (Rev C, Table 5, p.10, and the Figure 4 note): *"Connect the pad to
AGND and DGND"*, and AD's own reference layout routes those traces directly into
the pad.

Connectivity itself is fine — DRC reports 0 unconnected pads — so this is a
noise-floor and thermal-path item on an analog metering front-end, not a
netlist error. Four to nine vias in the EP down to the In1.Cu GND plane costs
nothing electrically (same net).

The 3×3 `F.Paste`-only sub-pad pattern under the EP is already correct
windowpane practice; leave it alone.

### 3. U2's SOT-223 tab has no thermal vias, and the Tj headline is quoted at the wrong ambient — *medium*

The tab (pad 2, 2.0 × 3.8 mm) is on `+3V3`, and In2.Cu is a **90.6 %-fill +3V3
plane** sitting directly underneath. Vias from tab to plane are free — same net —
and there are currently none.

The thermal analyzer reports Tj 68.7 °C, margin 56 °C, score 97. That is at
**25 °C ambient**, which is not the ambient a kiln controller lives in:

| Ambient | U2 Tj | Margin to 125 °C | Score |
|---|---|---|---|
| 25 °C | 68.7 °C | 56.3 °C | 97 |
| 40 °C | 83.7 °C | 41.3 °C | 97 |
| **50 °C** | **93.7 °C** | **31.3 °C** | 94 |
| 60 °C | 103.7 °C | 21.3 °C | 94 |

Still inside spec everywhere, but at 50 °C U2 crosses the 85 °C threshold that
starts to matter for the electrolytics and MLCCs near it. Finding 1 works in
your favour here: real dissipation is `(4.6 − 3.3) × I`, not `(5.0 − 3.3) × I`,
so ~0.56 W rather than the modelled 0.73 W.

### 4. Both inner planes were declared `signal` in the stackup — *low, FIXED*

In1.Cu (GND, 92.9 % fill) and In2.Cu (+3V3, 90.6 %) were typed `signal`, which
is why EMC reported `SU-001 "Adjacent signal layers"` three times against a
stackup that is in fact textbook.

**Fixed.** `gen_pcb.COPPER_LAYER_TYPE` now declares both inner layers `power`,
and it is read twice — by the text emitter and by `kicad_build.apply_layer_types()`
— because **pcbnew rebuilds the layer table from its own model on save and
drops whatever the input text said.** Setting it in the emitter alone was
silently a no-op: the first rebuild produced a byte-identical board. Unlike
`BOARD_STACKUP`, KiCad 10 does wrap `SetLayerType`, so this goes through the
API rather than `apply_stackup()`'s text patch. `SU-001` is now 0 and EMC's
error count fell 58 → 55.

### 5. 19 signal-via layer transitions lack an adjacent GND stitching via — *low*

`RP-001`, deterministic. Includes SPI_SCLK, USB_DP and USB_DN. Low real risk at
these speeds — Full-Speed USB and few-MHz SPI — but the USB pair is the cheapest
place to add them if the board is respun for any other reason.

### 6. `datasheets/manifest.json` described a design that no longer exists — *housekeeping, FIXED*

The manifest claims **all 26 parts failed to download** while 13 PDFs sit in the
directory, and it still lists parts that were replaced: `USBLC6-2SC6` for U4,
`MAX31855KASA+` for U3, `ESP32-S3-WROOM-1-N16R8` for U1. Datasheets for parts
actually fitted and *not* on disk: **SRV05-4** (U4, D5, D6), **SS34** (D1, D2),
**SS14** (D3), **1N4148W** (D4).

Consequence for this review: the SS34 drop in finding 1 is unverified, and the
SRV05-4 clamp topology behind my dismissal of `UC-002` (below) rests on the part
convention plus the prior review's record of having read it during the swap —
not on a datasheet I could open.

**Fixed, and made underivable-from-stale.** The manifest is now generated by
`generator/gen_datasheet_manifest.py` from two authoritative inputs — the values
in `design.COMPONENTS` and the PDFs actually on disk — so a retired part cannot
survive in it: nothing maps to it. It reports **10/14 present, 4 missing**
(`SRV05-4`, `SS34`, `SS14`, `1N4148W`), records the two superseded PDFs as
`retired_material` with the reason rather than deleting them, and fails on any
PDF that is in neither table. `make datasheets-manifest` regenerates it;
`make pcb-check` verifies it.

It is **not** a CI gate, deliberately: `datasheets/*` is gitignored, so the cache
does not exist in a fresh clone. That invisibility to git is also exactly why the
old manifest rotted — no diff ever contradicted it — so the guard is a generator
a human re-runs, not a reviewer. With no cache present the script exits 0.

The four missing datasheets are still missing; fetching them is a network
operation and was not performed here.

### 7. A stale sourcing flag in this document's own Open Items — *housekeeping, now corrected*

Through the previous round, Open Items flagged **`C7471632`, the ADE7953's
3.579545 MHz crystal (~1.7 k stock)** as one of the two thinnest BOM lines. That
part is gone — Y1 is now a packaged oscillator, `C2838127`, and `C7471632`
appears nowhere in `BOM.csv`. **Corrected in Open Items above.** Still live and
carried forward there: the module `C3013945` stock flag, `CERT-001` (WROOM-1U
modular approval vs. whichever U.FL antenna is actually fitted), the `SJ2` /
WDT-kick firmware gap, and the board-1 watchdog decay measurement.

## Triaged false positives

308 findings came back across six analyzers. These are the groups that account
for most of the severity, each dismissed with its root cause — worth recording
so the next review doesn't re-litigate them:

| Finding | Count | Why it's wrong |
|---|---|---|
| `KO-001` keepout violation | **39** (every PCB "error") | Bare bbox containment. The zone declares `(vias allowed) (tracks allowed) (pads allowed)` and forbids only `copperpour` — it's the outer-layer pour keepout over the USB pair from `e93bbe0`. The finding's own text says "(bbox check)". |
| `PS-002` +5V / VBUS "plane split", `RP-002` "+5V plane gap" | 3 + 5 | **There is no +5V or VBUS zone.** All six zones are 1 keepout + 2 `+3V3` + 3 `GND`. A plane split on a net with no plane is a category error; these are ordinary routed nets whose track groups the union-find didn't bridge. |
| `SS-001` sourcing blocker (<50 % MPN) | 1 | **38/38 assembled BOM lines and 13/13 hand-solder parts carry LCSC part numbers.** Sourcing lives in `gen_jlc.py` → `BOM.csv`, not as MPN properties on symbols. **Fixed at source anyway:** `gen_sch.py` now emits hidden `MPN` and `LCSC` properties from that same table, guarded by `check_mpn.py`, so coverage is 89.5 % (51/57 — the 6 without are test points, jumpers, fiducials, mounting holes and the DNP header, which correctly have none) and `SS-001` is gone. |
| `LR-001` / `PP-001` on LED1 | 2 | WS2812B is a constant-current smart LED — no series resistor exists or is wanted. `VLED` is fed through D3 **deliberately**: the schematic's own note reads *"VDD dropped ~4.6V for 3.3V data margin"*. The DC-path BFS accepts a wire, 0 Ω, inductor, ferrite or bridged jumper — but not a diode. |
| `IO-001` "no EMC filtering near J*" | 8 | Every external connector is filtered: J3 → R14/R15 into the MAX31856 with C15–C17; J12 → R31/R32 + D6 TVS; J11 → the 1 k + 10 k + 100 nF network with SRV05-4. |
| `DP-001/003/004` diff-pair skew & layer changes | 15 | Suffix `_P`/`_N` matching applied to **DC thermocouple inputs** (TC1/TC2) and **50/60 Hz CT inputs** (CTA/CTB). A 25 ps / 4.8 mm match requirement is meaningless at DC. |
| `SU-001` adjacent signal layers | 3 | Stackup layer typing — see finding 4. |
| `GR-004` paste 45 % of copper | 1 | 106 THT + 2 NPTH pads, plus test pads, fiducials and solder jumpers, correctly get no paste. Of 405 SMD pads, **384 have paste**. |
| `GP-001` reference plane gap | 77 | Bulk heuristic (`confidence: heuristic`, `evidence_source: heuristic_rule`) across ~50 nets. Both inner planes are >90 % filled. Not individually actionable. |
| `UC-002` no ESD on VBUS | 1 | U4 pin 5 (VP) is on VBUS and pin 2 (VN) on GND — VBUS *is* the SRV05-4's clamp rail. See the caveat in finding 6. |

`UC-001` (no decoupling on VBUS) is *not* dismissed: VBUS genuinely carries no
capacitor, only D2's anode and U4's VP. Bulk sits downstream of D2 on `+5V`
(C1/C3 22 µF, C11 10 µF). Harmless in practice for this topology; a 4.7 µF on
VBUS would satisfy the USB 2.0 §7.2.4.1 expectation if you care about strict
compliance.

## Delta since the prior review

`diff_analysis.py`, run `2026-08-16_1606` → `2026-08-17_1938` — 11 changes,
classified **major**, and all of them intended:

- **+** FID1/FID2/FID3 (fiducials)
- **~** U4: `USBLC6-2SC6` → `SRV05-4`
- **~** Y1: `3.579545MHz` crystal → `3.579545MHz XO` (Abracon 4-pin oscillator);
  **−** C26, and C25 30 pF → 100 nF as its decoupling
- **~** R31/R34 burden: `6R8` → `5R1`

No unexplained drift.

## Open items

- **Sourcing flag: the module `C3013945`** (ESP32-S3-WROOM-1U-N16R2, ~3.2 k in
  stock at the last check). A single-sourced Extended part with no fee-free
  equivalent, one per board. **Re-check stock immediately before ordering** —
  at these quantities a line can go to zero between review and order without
  warning.
  *Superseded:* earlier rounds of this review also flagged `C7471632`, the
  ADE7953's 3.579545 MHz **crystal** (~1.7 k stock). That part is gone — Y1 is
  now a packaged oscillator, `C2838127` — and `C7471632` appears nowhere in
  `BOM.csv`. The 6.8 Ω burden-resistor flag (`C17774`) closed earlier still;
  R31/R34 are 5.1 Ω (`C17724`, Basic).

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
- **The hardware watchdog and its firmware kick have both since landed.**
  `KILN_PIN_WDT_KICK` (GPIO 36) retriggers `U10` (SN74LVC1G123 retriggerable
  one-shot) gating both SSR channels, and firmware kicks it at 5 Hz, gated on
  `safety_task`'s heartbeat (`components/safety/wdt_kick.h`). Leave the `SJ2`
  ("WDT DEFEAT") solder jumper **open** on boards built from this package —
  fitting it defeats the only firmware-death heat cutoff. (This bullet
  originally predated both halves: it described the diode charge pump and
  instructed fitting `SJ2` because no kick task existed yet. That instruction
  now applies only to boards assembled from the pre-one-shot package.)

- **Measure the watchdog window on board 1 — it is a safety-path assumption.**
  The worst-case window arithmetic (1.65–2.71 s from `R46` 100 kΩ × `C38`
  22 µF, `design.py`'s watchdog block) extrapolates the SN74LVC1G123's
  K = 1.0–1.1 far beyond the datasheet's 10 kΩ × 0.1 µF spec anchor, and
  `C38` as ordered (`C12891`, X5R) is rated only to +85 °C, with its ±15 %
  temperature characteristic guaranteed no further. On the first board, time
  the actual window at `TP12` across supply and temperature, and confirm the
  SSR rail drops on all four failure shapes: kick stopped, pin stuck high,
  pin stuck low, and MCU held in reset. The timing parts are reworkable if
  the measurement disagrees. (An earlier version of this bullet timed the
  charge pump's *decay* through `C39`/1 MΩ values that no longer exist —
  superseded with the pump itself.)

- **`datasheets/manifest.json` is stale** — see finding 6. It claims all 26
  parts failed while 13 PDFs are on disk, and still lists retired parts
  (`USBLC6-2SC6` for U4, `MAX31855KASA+` for U3,
  `ESP32-S3-WROOM-1-N16R8` for U1). Datasheets missing for parts actually
  fitted: **SRV05-4** (U4, D5, D6), **SS34** (D1, D2), **SS14** (D3),
  **1N4148W** (D4).

## Design history — decisions and defects, recorded

Everything below predates the 2026-08-17 round and is preserved as the record of
why the board is shaped the way it is. Numbers in this part describe the state
at the time each entry was written, except where marked.

### The escalation ladder

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

### BOM/CPL parity check

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
board now carries exactly that — **6 / $18** — but it read **11 / $33** at
the time of this review, and closing the gap turned up two separate
problems rather than one.

Two were accounting, not design: C107114 (30 pF crystal load caps) and
C7420333 (the BAT54S watchdog diode) are **Preferred Extended**, which is
fee-free on Economic PCBA exactly as Basic is, and `gen_jlc.LCSC`'s flag was
being read as "is Basic". They were never chargeable. That alone was $6 of
the $33.

Three were real, and all three had fee-free substitutes that are also better
parts: D5/D6's Extended SRV05-4 line (C558418) and U4's USBLC6-2SC6 (C7519)
collapse onto one Preferred SRV05-4 (C7420376), and the 6.8 Ω CT burden
resistor (C17774) moves to 5.1 Ω (C17724, Basic) because JLCPCB stocks no
6.8 Ω part in either fee-free library in any package.

What is left is structural: the fee-free library contains **no connectors at
all**, so C160404 and C165948 are unavoidable, and the module, both
MAX31856s, the ADE7953 and its crystal have no fee-free equivalent. $18 is
this board's floor short of hand-soldering J14.

**Re-counted 2026-08-17.** The as-built package is now **108 machine-placed
parts across 38 BOM lines** plus 13 hand-soldered, after the SRV05-4
consolidation, the crystal → oscillator swap (which retired `C26`) and the three
added fiducials. BOM and CPL designator sets were re-derived directly from
`jlcpcb/BOM.csv` and `jlcpcb/CPL.csv` for this round: **108 each, both
difference lists empty**. The $18 feeder-fee floor is carried forward from the
last fab regeneration and was not re-derived here.

### PR #301 review round — the clipped schematic

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

### The opto-isolation reversal

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
landed); 141 components; 92 nets, 0 netlist
mismatches; 2271 copper items checked; BOM/CPL designator sets equal at 109,
no line without an LCSC part; gerbers still carry `In1_Cu`/`In2_Cu`.

### Resolved items and verified-as-drawn decisions

Kept because each records a defect class or a deliberate choice, not because
anything is outstanding.

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

> **Note (2026-08-17):** the U7 exposed-pad entry directly above concerns the
> *land size* (3.1 mm sq vs LCSC's 3.30 model) and stands. It is a separate
> question from finding 2 in this review, which is that the EP carries **no
> vias** — nearest GND via 3.36 mm. The land is right; the stitching is thin.

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

- **SPICE simulation — skipped.** `which ngspice ltspice xyce` returns nothing on
  this machine. The AMS1117 headroom arithmetic in finding 1 is static datasheet
  reasoning, not simulated.
- **Lifecycle / obsolescence audit — not run.** `lifecycle_audit.py` reads MPNs
  from the analyzer's BOM section, and the schematic carries none (finding 6).
  The LCSC codes that do exist are in `BOM.csv`, which the tool doesn't read.
  Stock re-check before ordering remains a manual step.
- **Structured datasheet extraction — not available.** `datasheets/extracted/` is
  empty, so every datasheet claim here comes from reading the PDF text directly,
  cited inline.
- **SRV05-4, SS34, SS14, 1N4148W not verified against datasheets** — not on disk.
- **No board rebuild or 3D re-render.** This review changed nothing; `make pcb`
  was not run and the committed `3d/.render-stamp` is untouched.
- **`GP-001` (77 findings) was triaged as a class, not net by net.** If you want
  per-net reference-plane confidence, that needs a targeted pass.
