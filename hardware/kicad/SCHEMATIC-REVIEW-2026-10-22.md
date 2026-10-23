# Schematic review — 2026-10-22

> **Applied later the same day (rev B.3):** findings 1, 2, 3 (ERC now
> 0 errors / 0 warnings), 4 (hierarchical labels, sheet pins, root block
> diagram; no global labels remain), 9, 10, the `single_global_label`
> half of 19, and the test-point half of 16 (TP4–TP11 now sit beside
> their nets on `mcu` / `ct`).
>
> **Second batch, same day:** 5 (every PWR_FLAG now sits where its rail
> is created: J2.1, J2.2, Q8 source, L1 output, J1 VBUS), 7 (U3/U5 use a
> project `bisque:MAX31856` with SDO typed tri-state; the ERC exclusion is
> gone), 14 (Q4 flipped source-up), 15 (one Value string per LCSC part),
> the rest of 16 (every test point's Value is its net name), and a
> standalone `make erc` target with `lib_symbol_mismatch`,
> `endpoint_off_grid` and `same_local_global_label` promoted to errors.
> ERC is deliberately **not** in CI.
>
> **Third batch, same day:** 6 (D8, Q5–Q7 and U2 use `bisque:SMAJ30A`,
> `bisque:CJ2310`, `bisque:TLV1117LV33`), 8 (MPN is the manufacturer's
> number, plus `Manufacturer` and a `Datasheet` URL on all 160 sourced
> parts, from LCSC's product records; `check_mpn.py` now checks shape, not
> equality), 11 (J11 labels read along their wires), 17 (designator gaps
> noted on the root sheet), 18 (U6 I4–I7 grounded), E2 (module-variant
> note beside U1).
>
> **Fourth batch (2026-10-23):** 12 and 13. The two thermocouple
> front-ends, the CT front-end and the three protected inputs are drawn
> as inline chains (connector on the left, series parts in the signal
> path, caps hanging off the nodes, one label per filtered node into the
> IC); the clamp arrays D5/D6 keep a label-fed block beside each chain.
> Decoupling now hangs from short rails at the pins it serves: U1's 3V3,
> U3/U5's AVDD/DVDD, U7's VDD/VINTD/VINTA, and U2 is drawn as an inline
> 5 V → 3.3 V chain with C1/C2 on its input and C3/C4 on its output.
> E1 was closed in the third batch (no pull-up on the module's RESET).
> Still open: E3–E5, which are design decisions, not drawing fixes.
>
> **Test points (2026-10-23):** TP1, TP2, TP7, TP8 and TP11 were dropped;
> each sat on a net a connector pin already exposes (`+3V3` and I2C on
> J7/J14, `+5V` on J5, `CTA_P` on J12 pin 1). The seven that remain
> (TP3–TP6, TP9, TP10, TP12) are on nets nothing else reaches, and on the
> board every one of them already sits inline on its net's route (the
> longest dedicated stub is TP12's 3.3 mm from R46, pinned there by SJ2's
> courtyard), so none was moved. The copper that fed the five dropped pads
> (eight segments and one via, 15.5 mm, mostly +5V's spur from U2.3) is
> gone and DRC is at 0/0.
>
> **J13 (2026-10-23):** the DNP SELV header on the ADE7953's voltage
> channel is gone; true power measurement is not a planned feature, so
> the provision for an off-board AC-sense accessory went with it. VP/VN
> stay held at GND by R60/R61. On the board the header's two through-hole
> pads were also the layer change in each net's route, so a via now sits
> where each pad was. `gen_jlc.DNP` is empty.

Reviewed the Rev B.2 schematic on branch `hw/erc-sdo-exclusion` at `e5dcc7a`
(root `bisque-controller.kicad_sch` + the seven sheets under `sheets/`), the
exported netlist, the project ERC configuration, the sourcing fields, and the
design notes. Nothing was changed. This is a **schematic** review: drawing
conventions, connectivity hygiene, symbol/part honesty, metadata, and the
electrical items that the schematic itself exposes. The electrical findings
from the 2026-10-05 review (TVS/buck coordination, CT channel A range, the
grounded-return bypass, watchdog timing qualification, EP via-in-paste) are
**still open** and are not re-derived here; see the status table at the end.

## Checks run

| Check | Result |
|---|---|
| `kicad-cli sch erc --severity-all` | **0 errors, 230 warnings** (173 `lib_symbol_mismatch`, 55 `endpoint_off_grid`, 2 `same_local_global_label`); 1 excluded `pin_to_pin` (U3/U5 SDO) |
| Konnect `find_orphan_items` / `find_shorted_nets` / `find_single_pin_nets` | 0 / 0 / 0 |
| Konnect `run_design_review` (8 sheets, 361 symbols, 151 named nets) | status complete; its 6 "errors" are per-sheet artefacts (every rail has decoupling and a test point on another sheet) and are not real |
| `make pcb-check-portable` | ALL CHECKS PASS (bounds, layout, uuids, mpn, netlist, pinmap, drill, 3D, USB pair, gerber zip) |
| Netlist walk, 137 nets / 182 symbols | every net has ≥ 2 pins; every unconnected pin carries a no-connect flag |
| Diode orientation from the netlist (D3, D4, D7, D8, D9, D10, D11) | all correct for their function |
| TPS2116 MODE/PR1 wiring vs datasheet truth table | correct (MODE = VIN1 → priority mode; PR1 divider from BUCK_5V) |
| Rendered every sheet and read them | see findings |

## Verdict

**Electrically the schematic is clean and internally consistent: no shorts,
no floating nets, no mis-oriented polarised parts, and ERC is at zero
errors.** What it is not yet is a *release-grade drawing*. Almost everything
below is drawing hygiene, metadata honesty, or a convention that the
generator that used to emit these sheets never followed. The three things I
would do first, in order of payoff per minute:

1. **Update the power symbols from the library** (clears 173 of the 230 ERC
   warnings in one click, finding 1).
2. **Decide on a hierarchy convention** and stop using global labels for
   48 nets that live on one sheet (finding 4). Note ERC cannot police
   this; the project's ERC severities are KiCad's stock defaults and ERC
   is not run by `make pcb-check` or CI at all (finding 19).
3. **Fix the stale notes and the title blocks** so the drawing stops
   referring to `design.py` and a crystal that no longer exists (findings
   9, 10).

---

## Findings

Severity: **P1** fix before the next fab/assembly order; **P2** fix before
a tagged release of the drawing; **P3** cleanup. Nothing here is a
"will not work" defect.

### 1. P2 — All 173 power symbols differ from the library copy (ERC `lib_symbol_mismatch`)

Every `power:GND`, `+3V3`, `+5V` and `VBUS` instance is flagged. The diff
is a single line each: the embedded symbol's **Description** has
over-escaped quotes (`\\\"GND\\\"` where the library has `\"GND\"`) — a
string-escaping bug in the retired generator, not a real symbol change.
The 173 warnings bury the eleven that matter.

**Fix:** Eeschema → Tools → *Update Symbols from Library…* on all power
symbols (or Konnect `sch_components` refresh). Re-run ERC; the count should
drop to 57.

### 2. P2 — 18 power symbols sit off the 1.27 mm grid, bridged by sub-millimetre stub wires (ERC `endpoint_off_grid`, 55 hits)

Found on `mcu` (10), `ct` (3), `power` (2), `ssr` (2), `io` (1) — e.g. the
GND at (313.476, 58.42) on `mcu`, the VBUS at (33.568, 175.26) on `power`.
Each one is placed 0.03–0.3 mm off grid and joined to its wire by a
0.0381 mm vertical stub plus a 0.15–0.27 mm horizontal one. They connect
today, but any hand edit that drags the wire will leave the stub behind
and open the net silently, and the warnings mask real off-grid work.

**Fix:** select each flagged symbol, snap to grid, delete the stubs.
Konnect `fix_connectivity` (dry-run first) will do the snap. After
findings 1 and 2, ERC should read **0 errors / 2 warnings**.

### 3. P3 — A local and a global label share a name on two sheets (`VIN` on `power`, `VLED` on `mcu`)

In both cases the global label exists only so a **PWR_FLAG** could be hung
on a stub in a "flags corner" (power sheet, bottom-left; mcu sheet, top of
the LED block). KiCad merges the two into one net, so there is no
connectivity bug — I confirmed `VIN` = {J2.1, F1.1} and
`VLED` = {D3.1, C10.1, LED1.1} in the netlist — but the duplicate name is
exactly the ambiguity the warning is for, and `VIN`/`VLED` are single-sheet
nets that should not be global at all.

**Fix:** delete the two global labels; put the PWR_FLAG directly on the
existing wire (J2 pin 1; D3 cathode).

### 4. P2 — Hierarchy is global-label-only; 48 of 67 global labels are single-sheet

The root sheet draws seven empty boxes with no sheet pins, and every
cross-sheet connection is a global label. That is a legal KiCad style, but
the consequence is that the root page carries no information (it is an
index, not a block diagram) and the reader cannot tell a bus that leaves
the sheet from one that does not. Worse, 48 global labels are used on
**one sheet only** (`USB_DN/DP`, all five `BTN_*`, all the `LCD_*_R` and
`T_*_R` nets, `EN`, `IO0`, `BUCK_5V`, `SSR_EN`, `SSR_RTN`, `AUX_VP`,
`ADE_*`, `CTA_*`, `CTB_*`, `TC1_N_F`, `TC2_N_F`, `WDT_CT_N`, `VIN`,
`VLED`, …). No ERC rule catches this: `single_global_label` (ignored by
KiCad's own default, and in this project) only fires when a global label
has exactly **one instance** in the whole design — enabling it here
reports just `VIN` and `VLED`, the two from finding 3 — so a "global
label used on one sheet only" check would have to be a repo script.

**Fix (minimum):** convert single-sheet globals to local labels (keep
`BUCK_5V`/`SSR_EN`/`SSR_RTN` global only if you want a test point to reach
them from `test`), set `single_global_label` to *warning* so the
one-instance case is caught, and add a "global label on one sheet" check
beside `check_sch_layout.py`.
**Fix (preferred):** give each sheet hierarchical labels for the nets that
actually cross (`SPI_*`, `I2C_*`, `TC?_CS`, `SSR?_CTRL`, `WDT_KICK`,
`AUX1-3`, `ALARM`, `IN1-3`, `LED_DATA`, `VIN_P`, `+5V`, `+3V3`), import
them as sheet pins (Konnect `import_sheet_pins`), and wire the root sheet
as a block diagram. Power rails can stay as power symbols.

### 5. P2 — PWR_FLAGs are parked in a corner rather than at the source of each rail

`power` sheet, bottom-left: a `VBUS` power symbol with a dog-leg wire to a
flag, a lone `VIN` global label with a flag, flags on `BUCK_5V` and
`VIN_P`, and a flagged orphan `GND`. Two of the four flags show the
"PWR_FLAG" text, two have it hidden, so they read as different things.
Convention is to place the flag where the rail is created (J2.1 for `VIN`,
Q8 source for `VIN_P`, U11.OUT/L1 for `BUCK_5V`, J1.VBUS for `VBUS`), so a
reader sees *why* ERC accepts that net as driven.

**Fix:** move each flag to its source, unhide the value text on all of
them, delete the corner.

### 6. P2 — Symbols that are not the fitted part

| Ref | Fitted part | Symbol used | Risk |
|---|---|---|---|
| D8 | SMAJ30**A** (unidirectional TVS) | `Device:D_TVS` (bidirectional glyph) | The drawing shows a part with no polarity; the SMA footprint pin 1 is the cathode and the netlist has it right (D8.1 = VIN_F), but a reader cannot see that and a bidirectional substitute would not clamp reverse polarity the same way. Use a unidirectional TVS symbol. |
| Q5, Q6, Q7 | CJ2310 (60 V) | `Transistor_FET:2N7002` | Pinout matches (G-S-D), but the symbol's datasheet/description say 2N7002, 60 V vs 60 V happens to agree, and anyone opening the datasheet link reads the wrong part. |
| U2 | TLV1117**LV**33 | `Regulator_Linear:TLV1117-33` | The LV part has a different input range (≤ 5.5 V) and needs a ceramic output cap; the symbol link points at the non-LV sheet. Prior-review item, still open. |

**Fix:** derive project-library symbols (Konnect `library` toolset) with the
right name, datasheet, and for D8 the right glyph; Q5–Q7 can simply point
at `Transistor_FET:CJ2310`-style derived symbol with the CJ datasheet.

### 7. P2 — The U3/U5 SDO conflict is handled by an ERC exclusion, not by the symbol

`e5dcc7a` added an `erc_exclusions` entry (with a good explanatory string)
for the two MAX31856 SDO pins on `SPI_MISO`. That works, but it is tied to
the two symbol UUIDs: replace either symbol (finding 6 style refresh, a
copy/paste, a resync) and the error silently returns. The honest fix is the
one the exclusion text itself states: SDO is tri-state while CS is high.

**Fix:** derive a project `MAX31856` symbol with SDO typed **tri-state**
(or bidirectional) and drop the exclusion. Same treatment is the right one
for any future shared-MISO device.

### 8. P2 — Sourcing fields: MPN holds the LCSC number; Datasheet is empty on 158 of 182 parts

`MPN` == `LCSC` on all 160 sourced parts (e.g. C1 MPN = `C12891`), and
`generator/check_mpn.py` *enforces* that equality, which cements the wrong
convention. A real MPN (`CL31A226KAHNNNE`) plus a `Manufacturer` field is
what a second source, a Mouser order, or a datasheet lookup needs; the
C-number is a distributor SKU. `hardware/kicad/datasheets/` already holds
30 PDFs with a manifest, yet only the 24 ICs/semis have a Datasheet link.

**Fix:** add `Manufacturer` + real `MPN`, keep `LCSC` as the distributor
field, point `Datasheet` at `${KIPRJMOD}/datasheets/<file>.pdf` (the
manifest already maps refs to files), and relax `check_mpn.py` to "both
present" rather than "equal".

### 9. P2 — Stale notes on the drawing

- Root sheet notes: "Y1/C25/C26 load caps are an ASSUMED value (unverified
  C_L), see design.py comment." **Y1 is now a packaged oscillator**, C26
  no longer exists, C25 is its bypass, and `design.py` was retired on
  2026-10-06. The note states the opposite of the design.
- `ssr` sheet notes: "see design.py's SSR block" — file no longer exists;
  the reasoning now lives in `DESIGN-NOTES.md`.
- `test` sheet title: "Test points, mounting, fiducials, **power flags**" —
  there are no power flags on that sheet (they are on `power`).
- Root notes mention the PCF8574A address collision (0x38) — fine as an
  expansion warning, but say so ("if you add a PCF8574A…").

**Fix:** reword; reference `DESIGN-NOTES.md §Y1` / `§Q5` instead.

### 10. P2 — Title blocks: rev/date not bumped, titles overflow the block, one sheet is A2

- Every sheet says **Rev B.2, 2026-09-21**. Since then the AUX bank was
  re-pinned (58ba889), TC1_CS/IN3 traded GPIOs (d74cc0a), and the ERC
  fixes landed. A GPIO swap is a rev change for anyone holding an older
  print. Bump to B.3 (or at least the date) and consider
  `${CURRENT_DATE}` / a git-derived text variable via `scripts/version.sh`.
- Sheet titles on `mcu`, `thermocouples`, `test` are longer than the
  title block and are clipped in the PDF ("…headers, b", "…(MAX31856 x2)"
  past the border). Shorten or move detail to Comment 3.
- `ct.kicad_sch` is **A2** while every other sheet is A3, and its content
  fills about a quarter of the page. Set it to A3 like the rest.
- Comments 3–9 are blank on all sheets; the sub-sheet title blocks repeat
  the root's two comments. Fine, but a per-sheet "block owner / see
  DESIGN-NOTES §…" line would be more useful than the duplicated stack-up.

### 11. P3 — Label text collisions the repo checker cannot see

`generator/check_sch_layout.py` deliberately skips labels ("Global labels
and wires are deliberately NOT checked"), so it passes while:

- `io` sheet, J11: the `IN2_RAW` label is drawn over J11's pin-2 wire and
  the vertical `IN1_RAW` label crosses pins 1–3's wires.
- `io` sheet, J10: `AUX_VP` sits on top of `AUX1_OUT` / pin 2.
- `power` sheet, LED2: the `GND` symbol with a flag diamond is squeezed
  against the `+3V3` symbol.

**Fix:** nudge the labels; consider extending the checker to label boxes
(it already has `text_box()`).

### 12. P3 — Drawing readability: label ladders instead of signal chains

The `ct`, `thermocouples` and `io` sheets draw the analogue front-ends as
rows of unconnected resistors/capacitors with a label on each end
(`CTA_P → R31 → CTA_N`, `CTA_P → R32 → CTA_F`, `CTA_F → C31 → GND`, …).
The reader has to reassemble the burden → filter → pin chain from label
names. The same is true of the MAX31856 input filter (R14/R15/C15/C16/C17
scattered around U3 with `TC1_N_F` appearing four times) and IN2/IN3
(C23/R28/R29/C24 in a separate row below D5). Resistor ladders are the
accepted idiom for pull-ups and series damping (R39–R58 are fine as
drawn); they are not for signal paths.

**Fix:** redraw the three front-ends inline, connector on the left, IC pin
on the right. This is the single biggest readability win on the drawing.

### 13. P3 — Decoupling drawn away from its IC

U1's 10 µF/100 nF (C7, C6) live in the reset block; U2's input/output caps
(C1–C4) are a row at the bottom of `power`; the MAX31856 AVDD/DVDD caps
(C13/C14, C18/C19) and C17/C22 are off to the right; the ADE7953 VDD caps
(C35/C36) and VINTA/VINTD/REF caps are in the ladder row. Convention is to
draw them at the pin they serve (or in a boxed "U7 decoupling" group) so a
reviewer can tick each supply pin.

### 14. P3 — Q4 is drawn upside down for a high-side switch

`ssr` sheet: Q4 (P-FET, +5 V high side) has its drain (pin 3, `SSR_EN`)
at the top and the source (pin 2) at the bottom, with the +5 V symbol
tucked beside the body and the source wire looping down and around to it.
Flip it so source/+5 V is up and `SSR_EN` leaves downward; same for Q8 on
`power` where the orientation is correct but the +5 V/VIN_P symbol is
placed inside the loop.

### 15. P3 — Inconsistent value strings for the same part

| LCSC | Value strings in use |
|---|---|
| C12891 (22 µF 25 V X5R 1206) | `22uF/25V` (C1, C3) and `22uF` (C38, C44, C45) |
| C17408 (100 Ω 1 %) | `100R 1%` (R14–R17) and `100R` (R11) |
| C8465 / C42377749 (terminal blocks) | function names (`24V_IN`, `SSR1`, `CT`, …) |

Connector Value = function is a reasonable convention; passives should be
one string per part so a BOM grouped by Value does not split. Decide
whether the voltage/tolerance lives in Value (`22uF/25V`) or in fields
(`Voltage`, `Tolerance`) and apply it everywhere. The 10 µF/50 V input caps
C41/C42 and the 100 nF parts have no rating in Value today.

### 16. P3 — Test points: generic value, split across two sheets

TP1–TP11 are on `test` with Value `TP`; TP12 (`WDT_CT_P`) is on `ssr`.
Either is fine, but pick one. Giving each TP a Value that names its net
(`TP_3V3`, `TP_MISO`) makes the BOM, the assembly drawing and the silk
self-describing.

### 17. P3 — Reference designator gaps

C8, C9, C26, D1, D2, Q1 are unused (deleted parts). Harmless, and
renumbering would break every reference in `DESIGN-NOTES.md`, the reviews
and `jlcpcb/README.md` — so **do not re-annotate**; just note the gaps in
the notes so nobody thinks a part is missing from the netlist.

### 18. P3 — ULN2003 unused inputs left open

U6 I4–I7 are no-connect. ULN2003 inputs have an internal 2.7 kΩ/3 kΩ
base network, so open inputs are safe (TI does not require termination),
but tying them to GND is the usual belt-and-braces and costs four stubs.

### 19. P2 — ERC is not part of any check target, and its severities are stock defaults

`make pcb-check`, `pcb-check-portable` and the CI workflows never run
`kicad-cli sch erc`; the 230 warnings above were only visible by running
it by hand. The project's `rule_severities` are byte-for-byte KiCad 10's
defaults (verified against `erc_settings.cpp`), which leave exactly four
rules at *ignore*: `single_global_label`, `footprint_filter`,
`four_way_junction`, `simulation_model_issue`. Enabling them on a scratch
copy reports: `single_global_label` 2 (VIN, VLED), `footprint_filter` 4
(F1 1812 vs `*polyfuse*`, U8/U9 SOP-4 vs `SOIC*4.55x2.6mm*`, U7 QFN-28 vs
`LFCSP*` — all naming mismatches on land patterns the JLC fit checker
already validates), `four_way_junction` 0, `simulation_model_issue` 0.

**Fix:** add an `erc` step to `make pcb-check` (it needs `kicad-cli`, so
not the portable subset) with `--exit-code-violations`; set
`single_global_label` and `footprint_filter` to *warning*; once findings
1–3 are done, promote `lib_symbol_mismatch`, `endpoint_off_grid` and
`same_local_global_label` to *error* so a regression fails the gate
instead of adding to a warning pile nobody reads. Leave
`simulation_model_issue` ignored (no SPICE models here) and
`four_way_junction` at your preference (it is a drafting-style rule;
the design currently has none).

---

## Electrical observations new to this review

None of these is a blocker; they are things the schematic makes visible
that the earlier reviews did not list.

### E1. P2 — LCD_RST is on GPIO46, a boot-mode strapping pin

U1 pin 16 = GPIO46 → `LCD_RST` → J5.4. The ESP32-S3 datasheet lists
GPIO46 as a strapping pin (chip boot mode with GPIO0, and ROM message
printing), default weak pull-down. Normal SPI boot is unaffected (GPIO46
is don't-care when GPIO0 = 1). But **download mode requires GPIO0 = 0 and
GPIO46 = 0**; if the MSP4021 module has the usual 10 kΩ pull-up on its
RESET pin, GPIO46 is held high at boot and the BOOT button no longer
enters the flasher (native USB-JTAG/OTG DFU still works, so it is not a
brick). Check the module's RST pin against ground and, if it pulls up,
swap LCD_RST with a non-strapping output (IO45 is free but is itself a
strapping pin; IO37 is free on the R2 module — see E2). Add a one-line
note on the `mcu` sheet either way.

### E2. P3 — The pin map silently depends on the N16**R2** (quad PSRAM) module

U1 pins 28/29 = GPIO35/GPIO36 carry `TC2_CS` and `WDT_KICK`; only GPIO37
is marked NC "PSRAM". That is correct for the R2 (quad PSRAM) part. On any
**R8** (octal PSRAM) variant GPIO35–37 are all consumed by the PSRAM bus,
and the cached datasheet in `datasheets/` is the **N16R8** one. Put "R2 or
no-PSRAM modules only — GPIO35/36 are PSRAM DQ4/DQ5 on R8" on the sheet
next to U1 so a BOM substitution cannot pass review.

### E3. P3 — ADE7953 reset is RC-only; the MCU cannot reset it

R30/C37 give a power-on stretch (per DESIGN-NOTES §R30) and no GPIO
reaches `ADE_RESET`. The part has a software reset over I2C, so this is a
choice, not a fault — but if the ADE7953 ever wedges its I2C engine the
only recovery is a power cycle of the whole board. If a GPIO is ever
freed, this is a candidate for it.

### E4. P3 — No VBUS sense

The MCU cannot tell USB-only from 24 V power. It does not need to for
safety (the SSR terminals are fed from `VIN_P`, so USB-only cannot drive
a load), but firmware could use a divided `VBUS` on a spare input to warn
"no 24 V — SSRs will not fire" instead of silently timing out. One
resistor pair and a GPIO.

### E5. P3 — Watchdog timing capacitor is a 22 µF X5R

C38 is the same CL31A226 (X5R, 25 V) as the bulk caps. At 3.3 V bias the
DC-bias loss is small, but X5R carries ±15 % over temperature plus aging,
on top of ±10 % tolerance, and the prior review's point stands that the
LVC1G123's bounds are only specified at 10 kΩ/0.1 µF. If the deadline
must be guaranteed rather than estimated, a 1 MΩ/2.2 µF X7R or a film cap
narrows the spread (check the one-shot's Rext range first).

---

## Things that are right and worth keeping

- Every polarised part checked from the netlist is oriented correctly:
  D11 cathode on `VIN_P` (clamps V_GS of Q8 at 8.2 V), D8 cathode on
  `VIN_F`, D7 cathode on `SW_5V`, D3 anode on +5 V, D9/D10 cathodes on
  `VIN_P`, D4 cathode on +5 V.
- Reverse-polarity path is sound in both directions: with −24 V applied
  the unidirectional TVS forward-conducts and F1 trips; Q8 only ever sees
  ~0.7 V.
- TPS2116 is in true priority mode (MODE = VIN1, PR1 = 30 k/10 k from
  BUCK_5V), so a 5.25 V host cannot take the SSR terminals from the buck,
  and the no-buck case falls through to VBUS per the truth table.
- All chip selects (R50–R53) and AUX outputs (R23–R25) have boot-state
  resistors; `WDT_KICK` has a pull-down so a high-Z MCU reads as "no
  kick".
- Both I2C devices share one 4.7 k pull-up pair; both headers (J7, J14)
  break the same bus out.
- Every unused pin has a no-connect flag; the ERC exclusion carries a
  reason string; block headings and per-block notes are on every sheet;
  fonts are uniform (1.27 mm text, 2 mm bold headings).
- Y1's open EN pin is justified from its datasheet (OPEN = enabled) in
  `DESIGN-NOTES.md §Y1`.

## Status of the 2026-10-05 findings (not re-reviewed, checked for change only)

| # | Finding | Status at e5dcc7a |
|---|---|---|
| 1 | TVS clamp (48 V) above XL1509/SS34/AO3401A ratings | **Open** — D8 still SMAJ30A, U11 XL1509, D7 SS34 |
| 2 | CT channel A pseudo-differential (R33 to GND) | **Open** — R33 1 k to GND unchanged |
| 3 | Grounded SSR return bypasses Q7 | **Open** — architecture unchanged |
| 4 | Watchdog timing not guaranteed at 100 k/22 µF | **Open** |
| 5 | 17 EP vias in paste | PCB item, not re-checked |
| 11 | Failed Q5 can over-stress Q6 gate | **Open** |
| 12 | D8/U2 symbol honesty, MPN = C-number | **Open** — folded into findings 6 and 8 above |
| ERC | 4 errors | **Fixed** — 0 errors (U11/U12 power flags added, PWR_FLAG on VOUT removed, SDO excluded) |

## Suggested order of work

1. Update power symbols from library; snap the 18 off-grid power symbols;
   delete the two duplicate global labels. ERC → 0/0. (≈ 20 min)
2. Reword the stale notes, bump rev/date, set `ct` to A3, shorten the three
   overflowing titles. (≈ 20 min)
3. Decide global-vs-hierarchical; convert the 48 single-sheet globals;
   re-enable `single_global_label`. (≈ 1–2 h; worth doing before any more
   sheet edits so the rule catches regressions)
4. Project-library symbols for D8, Q5–Q7, U2, MAX31856 (tri-state SDO);
   drop the ERC exclusion. (≈ 1 h)
5. Sourcing fields: Manufacturer + real MPN, Datasheet links; relax
   `check_mpn.py`. (≈ 1 h, mostly table work)
6. Redraw the three analogue front-ends inline; move PWR_FLAGs and
   decoupling to their sources; flip Q4. (≈ 2 h)
7. Confirm the MSP4021 RST pull-up (E1) and add the module-variant note
   (E2) to the `mcu` sheet.
