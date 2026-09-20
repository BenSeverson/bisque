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
- 2026-09-02 — pre-prototype review of the board as committed at
  `7fa2fd9` (TLV1117LV33, SN74LVC1G123 one-shot, derived block legends):
  16 independent review lenses plus direct re-measurement of every
  medium-and-above finding.
- **2026-09-18 — current.** Pre-order review of the board as committed at
  `cb7d412` (24 V input with the XL1509 buck, CS pull-ups, display damping,
  differential CT, exposed-pad via grids): one reviewer plus measurement
  scripts and live sourcing data, after the planned multi-agent pass was
  lost to a usage limit. Everything from "## Verdict" onward below is the
  2026-08-17 round, preserved as written; the two later rounds are the
  sections that follow this list, newest first.

Rev B is a respin, not a variant: the thermocouple front-end, module variant,
output bank, and layer count all changed, and no attempt was made to keep rev A
hardware compatible with rev B firmware defaults. The one item that carries
forward unchanged is `CERT-001`, below.

## 2026-09-18 round — pre-order review

**Ask:** full review of the schematic and PCB before placing the first
JLCPCB order (5 boards, top-side SMT, hand-fitted THT).

Board as committed at `cb7d412` (working tree clean under `hardware/kicad/`;
`hardware/kicad-konnect/` is an untracked Konnect scratch project from
2026-09-10 and is not part of the order). Schematic `105780bb…`, board
`69e601d9…`. Since the 2026-09-02 round the board gained the 24 V input
(F1/D8/U11/L1/D7/C41–C45), the chip-select pull-ups, the display damping
row, the differential CT channel, the exposed-pad via grids and the J13 DNP
marking — 30 hardware commits. The power stage had never been reviewed; it
got the deepest look.

### Verdict

**Nothing found makes the board unusable or the package unorderable, and
the gates are all green. One generator edit is worth landing before the
order — an electrolytic footprint on the buck output (A1) — because the
alternative is a bodge across C44 on a power stage that has never been
built. Everything else is a bench check on board 1, a rev-C item, or an
order-form choice.** The prior round's A-list is verified fixed except A2
(TP11 legend, accepted debt) and A7 (REF decoupling, improved not closed).

### Status, 2026-09-19 — A1 landed, documentation corrected

**A1 is fixed and the package is rebuilt.** `C46`, a 100 uF 16 V aluminium
electrolytic (LCSC `C2977550`, `CP_Elec_5x5.4`), now sits across `+5V` at
(97.5, 113.25) with 0.66 mm of courtyard clearance to C44, 3.40 mm from
FID3's centre to the can body (the assembly camera needs to see the
fiducial), and a ~7.8 mm run to C44's `+5V` pad. The reasoning — why an
ESR zero and not more ceramic, why D5 and not D6.3 — is written out at C46
in `design.py` so it survives the next person who sees an electrolytic
beside two MLCCs and tries to tidy it up.

Rebuild result, `make pcb` + `make pcb-check` + `make pcb-render`:

| Gate | Result |
|---|---|
| Router | **0 nets unrouted** at pass 3 (the rip-up log shows it re-routing T_CS, LCD_SDO_R and LCD_DC around the new part, then closing) |
| `kicad-cli pcb drc` (JLC `.kicad_dru`) | **0 violations, 0 unconnected pads, 0 footprint errors** |
| `make pcb-check`, all 14 checkers | exit 0 — netlist round-trip, schematic uuid round-trip, 29 GPIOs vs Kconfig, drill web 0.300 mm, 148 3D models resolve, `gerbers.zip` current, silk 0/0/0/0, no via in an SMD pad |
| `check_jlc_placement` | 134 parts / 40 LCSC land patterns fitted (was 133 / 39) |
| `check_mpn` | 147 sourced parts (was 146) |
| Fab files | BOM 43 lines / 134 placements, CPL 134; C46 present in both at (97.500, -113.250) rot 0; absent from the hand-solder and Mouser lists, correctly |
| Feeder fees | **11 lines / $33**, up from 10 / $30 — C2977550 is the new one. LCSC lists no aluminium electrolytic in either fee-free library, so there is no way to avoid it |
| 3D renders | re-raytraced (`make pcb` stops at `pcb-check`, so `pcb-render` needed running separately) |

**One thing to eyeball before you submit the order, and it is the only
check the toolchain cannot make for you.** C46 is the board's first
polarised two-pad part, and a two-pad symmetric land is exactly the case
geometric fitting cannot police: rotating it 180 degrees still makes the
pads coincide, so only the pad *numbering* carries the polarity. The
evidence that rotation 0 is right is good — both KiCad and LCSC put pad 1
on the chamfered end, KiCad draws a `+` at pad 1 in silk and fab, and the
two lands differ only by 0.2 mm about a shared origin — but it is
convention rather than a measurement. **Open JLCPCB's assembly preview
after uploading BOM+CPL and confirm C46's `+` faces the board's `+` mark**
(west, toward J14). A reversed 100 uF electrolytic vents on first power-up.

Documentation fixed in the same pass:

| Item | Change |
|---|---|
| Surface finish | `README.md`'s capability table said HASL against a board that declares **ENIG**; corrected, with a note that JLC takes the finish from the order form and that `"ImpedanceControlled": true` is a stack-up declaration, not a thing to buy |
| USB pair figures | `CLAUDE.md` and `README.md` both carried pre-A8 numbers. Re-measured: DP J1.B6→U1.14 **39.372 mm / 6 vias** against DN J1.B7→U1.13 **29.119 mm / 4** — a **10.25 mm (~69 ps)** skew, not the 0.278 mm claimed; **11.3%** of DP's 50.81 mm runs within a 0.30 mm **edge** gap, not 0.0%. Both files now name the convention, because at 0.3 mm wide on 0.2 mm clearance a *centre-to-centre* figure can never fall below 0.5 mm — "0.0% within 0.30 mm" was vacuously true, which is how it survived two rounds |
| Lid default | `lid_state.h` said GPIO 21; Kconfig and the board say **GPIO 4** |
| Enclosure README | two places still called the box supply "the 5 V supply" / "the 5 V feed" against its own text; it is **24 V** into J2 |
| `jlcpcb/README.md` | new **SJ1** section: bridging it with an external 24 V coil rail landed on J10.1 puts 24 V onto `+5V`, whose loads include a 6 V-max LDO |
| `bench-smoke-test.md` | had no rev B content. Now opens with the four things that stop the board dead (24 V supply, SJ2 open, SJ1 open, lid input satisfied) and a first-power-up section for the never-built power stage |
| Feeder accounting | README's 10 lines / $30 / "122 of 133" updated to 11 / $33 / "122 of 134" |
| Title block | hard-coded `2026-07-20` → `2026-09-19` in `gen_sch.py` and `kicad_build.py` |
| `lcsc_pads.py` | not a doc fix but found while making one: `--refresh` had been failing with "rate limit?" on what is actually a **CloudFront 403 against curl's default User-Agent**. It now sends a browser UA and the error message distinguishes the two cases |

**Not done, deliberately:** the duplicate `C17408` BOM rows (`100R 1%` for
R14–R17 against `100R` for R6/R19/R11) are still two lines. Merging them
means editing four component *values*, which is a schematic change with no
defect behind it — JLC's matcher takes both rows fine. Everything else in
sections C and E remains as written: bench checks on board 1, and rev-C
items.

### Verification basis

| Gate | Result (2026-09-18, KiCad 10.0.6) |
|---|---|
| `make pcb-check` — all 14 checkers | exit 0 (29 GPIOs agree with Kconfig; netlist round-trip 102 nets / 0 mismatches; sch uuid round-trip; drill web ≥ 0.300 mm; 147 3D models resolve; `gerbers.zip` matches `gerbers/`; JLC placement 133 parts fitted; 0 via-in-SMD-pad; silk 0/0/0/0) |
| `kicad-cli pcb drc --severity-all --schematic-parity --all-track-errors --refill-zones` (with the JLC `.kicad_dru`) | 0 violations, 0 unconnected, 478 parity notes (146 missing-MPN-field, 189 footprint lib-nickname, 22 Description, 121 net_conflict = 30 no-connects + `/X` vs `X` local-label names — generator cosmetics, unchanged) |
| Same DRC with mask dam 0.10 mm / mask-to-copper 0.05 mm enabled (scratch copy) | **0 violations** — the README's claim holds |
| `kicad-cli sch erc --severity-all` | 0 errors (SDO/SDO on SPI_MISO = tri-state bus; U11 VIN "not driven" = VIN_P has no PWR_FLAG); 167 power-symbol cache warnings, 52 off-grid, 2 same_local_global_label (VIN, VLED) |
| Konnect `run_design_review` / `find_shorted_nets` / `find_orphan_items` / `check_bom_health` / `validate_for_manufacturing` | 0 shorts, 0 orphans, BOM 0 issues, READY; one audit error "VBUS has no decoupling" (see C); its 33 "single-pin nets" are the fused local labels the netlist round-trip proves connected; its "2 copper layers" is its own parser |
| kicad-happy analyzers (schematic, PCB `--full --proximity`, gerber, cross, EMC, thermal @ 50 °C) | run fresh; every error-level finding triaged — all are the known artefacts (keepout, plane-split, LED1 resistor, PP-001 VLED, IO-001, diff-pair rules) except TV-001/VP-001 (EP vias, addressed below) |
| Fab files | BOM 133 + hand-solder 13 + not-assembled 22 (12 TP, 3 FID, 4 H, SJ1/SJ2, J13) = 168 = `design.py`, disjoint; J13 carries the DNP attribute; `.gbrjob` declares the JLC04161H-7628 stack (0.2104 / 1.065 / 0.2104 mm), 4 layers, 1.6 mm, **ENIG** |
| Live JLC/LCSC stock and fee status (jlcsearch, 2026-09-18) | all 43 lines in stock; 10 fee-bearing lines = $30 as the README says (F1, J1, J14, L1, U1, U10, U2, U3/U5, U7, Y1); D8 and SRV05-4 are Preferred |
| Measurement | every number below was measured on the committed board with `pcbnew` 10.0.6 or read from the gerbers; scripts are in the session scratchpad (`agents/*/measure*.py`, `mine/fab_checks.py`) |
| Datasheets read this round | XL1509 Rev 2.0 (XLSEMI, fetched from LCSC: pin table p.2, abs max p.5, layout/CFF note p.8, design tables p.9), LCDWIKI MSP4021/3520 manual (14-pin table), SRV05-4, WS2812B, 1N4148W, ADE7953 Rev C (CS/I²C selection), plus the prior round's set for the unchanged blocks |

**Process note.** The planned 16-lens adversarial workflow hit the session
usage limit after 1.86 M subagent tokens with no agent returning; its
measurement scripts and datasheet extracts survived and were reused. This
round is therefore one reviewer plus scripts, not sixteen plus verifiers —
findings below are measured, but they have not had the independent
refutation pass the 2026-09-02 round had. See "Not performed".

### A. Worth a generator edit before ordering

| # | Finding | Measured | Fix |
|---|---|---|---|
| A1 | **The XL1509 buck has an all-ceramic output.** The datasheet's 5 V design table (p.9) lists only 180 µF/35 V electrolytic (Panasonic HFQ) or 100 µF/10 V tantalum (AVX TPS) for COUT, and p.8 says a feed-forward cap "provides additional stability for … very low ESR output capacitors" — which the fixed-5.0 part cannot fit, because FB (pin 3) is tied straight to the output. The part is an LM2596-class voltage-mode regulator whose internal compensation assumes the ESR zero of an electrolytic; ceramic-only outputs on that family are the textbook instability case | C44/C45 = 2 × 22 µF X5R 1206 (C12891), ~16 µF each at 5 V bias, ESR of a few mΩ. Input: C41/C42 2 × 10 µF/50 V X5R at 24 V bias ≈ 10 µF total against the datasheet's 470 µF CIN | Add an SMD aluminium electrolytic footprint on +5V beside C44 (100–220 µF / 16 V, 6.3 mm can; pick a JLC Basic line so it is fee-free, or leave the pads for a hand-fitted radial) and optionally 47–100 µF / 50 V on VIN_P beside C41. Two footprints in `design.py`, one `make pcb`. If the ceramic loop happens to be stable the parts cost nothing; if it is not, board 1 has a 5 V rail oscillating under the LDO, the SSR gate rail and the WS2812B, and the fix is a cap tacked across C44 |

### B. Order-form choices (no board change)

- **Finish: the package says ENIG, the README says HASL.** `gen_pcb.py:565`
  chose ENIG deliberately (0.5 mm-pitch QFN-28 with a 3.1 mm exposed pad,
  9-via module pad) and the `.gbrjob` carries `"Finish": "ENIG"`;
  `README.md:459`'s capability table still says HASL. Order **ENIG** and fix
  the table. JLC takes the finish from the order form, not the gbrjob.
- **Impedance control: do not buy it.** The gbrjob's
  `"ImpedanceControlled": true` is only the stack-up declaration; the one
  target (USB FS at 90 Ω) is documented as uncoupled and accepted.
- **Via covering: tented** (the board tents both sides; 469 of 470 vias have
  no mask opening — the one exception is under U1's thermal pad opening,
  by design).
- **Order number:** the board carries no `JLCJLCJLCJLC` marker, so JLC will
  place its order number on the silk wherever it likes — on this board that
  is a legend. Pick "remove order number" (small fee) or add the marker in
  an empty pour area in rev C.
- **Stock at order time** (5 boards need 5 + JLC attrition of each):
  D8 SMAJ30A C19077547 **651** (Preferred) — fallbacks C908776 (197 k,
  Extended) or the bidirectional SMAJ30CA C19077548 (Preferred, 14 k; with
  D1 blocking reverse polarity a bidirectional clamp is electrically fine
  here); ESP32-S3-WROOM-1U-N16R2 3 507; MAX31856 7 744; ADE7953 4 846; XO
  6 566; SN74LVC1G123 8 800; TLV1117LV33 98 k. The thin hand-solder lines
  (J7 22-27-2081 at 754, J5 XD-2510-14A at 1 271) come from Mouser anyway.

### C. Bench checks on board 1 (cannot be settled on paper)

| # | Check | Why |
|---|---|---|
| C1 | **USB-only power back-feeds the buck.** With VIN_P at 0 V, U11 pin 3 (FB, tied to +5V) and pin 2 (SW, DC through L1) sit at VBUS − D2 ≈ 4.4–4.8 V. XL1509 abs max (p.5) rates FB and the switch pin at "−0.3 to Vin". The LM2596 it clones rates FB to +25 V and the output to −1 V, so this is probably a clone-datasheet artefact — but USB-only is every flashing session. Measure current into U11 (lift nothing: measure VBUS current with and without U11's +5V path, or U11 case temperature) on USB alone. If it draws or warms, rev C needs an ideal-diode or accepts a Schottky between the buck and +5V | Datasheet limit on paper in a routine operating mode |
| C2 | **Scope the +5V rail** at C44 under the real load (Wi-Fi TX + backlight + both SSR LEDs) for subharmonic or ~kHz oscillation. This is the A1 question answered with hardware | Ceramic-only COUT |
| C3 | **Bring the SPI bus up at 20 MHz, then raise.** SPI_SCLK is a 124 mm, 8-via multi-drop net: U1 → U3 32 mm, U5 37 mm, touch damper R39 71 mm, display damper R54 85 mm, then ≤ 150 mm of loom. The 33 Ω dampers sit at the connector end, so the two MAX31856 stubs are undamped branches on a 40 MHz clock; SPI_SCLK also runs 11 mm at 0.2 mm from SSR2_CTRL and SPI_MISO parallels SPI_SCLK for 19.9 mm on B.Cu. Ringing at the MAX31856 SCLK pins or the display is the expected failure mode; the clock is a firmware knob | Multi-drop 40 MHz over 85 mm + loom |
| C4 | **Cold-junction gradient** (prior C item, unchanged): U3/U5 are 27/31 mm from U1 and 59/60 mm from U2; J3/J8 are 17 mm from their chips. Log CJ temperature vs a reference over a warm-up | On-die CJ with 0.5–1 W parts 30 mm away |
| C5 | **WS2812B data threshold at idle.** At the LED's ~1 mA dark current D3 drops ~0.55–0.6 V (1N4148W: 0.715 V max at 1 mA), so VLED ≈ 4.4 V and VIH ≥ 0.7 × 4.4 = 3.08 V against an ESP32-S3 VOH that is 3.2 V typical and 2.64 V spec minimum. The design note assumed 0.65–0.85 V. Works on typical silicon; if colours are wrong at boot or idle, that is why (rev C: 74AHCT1G125 or a second diode) | Margin lives inside the VOH tolerance |
| C6 | **Buzzer drive** (prior B item, still open): `components/safety/safety.c:24` still chops ALARM at 4 kHz through LEDC; BZ1 is an active TMB12A05 and wants a level (`d4ccca1` documents this, the code is unchanged). It will sound, modulated; fix in firmware before judging the part | Firmware |

### D. Prior-round status, re-measured

| Item | State now |
|---|---|
| A1 hole grid | **fixed** — H1–H4 at (25,25) (115,25) (25,115) (115,115): 90 × 90 mm, all four GND |
| A2 TP11 legend | **accepted debt**, unchanged — `TP_LEGEND_OK = {("CT A+","J12")}`; `CT A+` still prints beside J12's `A-` mark |
| A4 CS pull-ups | **fixed** — R50 TC1_CS, R51 TC2_CS, R52 LCD_CS, R53 T_CS, 10 k to +3V3, measured on the pads |
| A5 display SDO | **fixed** — R56 33 Ω between SPI_MISO and J5.9 |
| A6 EP vias | **fixed** — U7 4 × 0.3 mm in the 3.1 mm EP (GND), U2 4 × 0.3 mm in the tab (+3V3, In2), U1 9 × 0.3 mm (Espressif's grid). The thermal analyzer's "U2 no thermal vias" is wrong; TV-001's "4 < 5" for U7 is a threshold, not a datasheet number |
| A7 ADE REF | **improved, not closed** — U7.13 → C34 10.0 mm / 2 vias, → C33 15.1 mm / 2 vias (was 42 mm); target was < 5 mm / 0 vias |
| A8 USB_DN detour | **resolved** — USB_DN 33.2 mm / 5 vias total |
| A9 TC2 filtered legs | **fixed** — TC2_P_F 17.4 mm / 2 vias vs TC1_P_F 15.7 / 2; TC2_N_F 24.2 / 3 vs TC1_N_F 24.2 / 2 |
| A10 CT channel A | **fixed** — U7.6 (IAN) = CTA_FN through R59 1 k with C40 33 nF; both channels ±500 mV, 139 A rms at 5.1 Ω / 2000:1, as the enclosure README now states |
| A11 `.kicad_dru` | loads; JLC-rule DRC 0 violations |
| C: F1 + D8, R54–R58, R60/R61, R49, D3 silicon | all present on the measured nets |
| C: `+5V` single power vias | **open** — 5 transitions, one 0.6/0.3 via each: (40.0, 72.0) (41.0, 60.5) (44.25, 52.25) (90.0, 95.75) (91.25, 97.0). Rev C |
| C: stitching vias | **open** — 15 of 285 signal vias have a GND via within 1.5 mm (31 within 2 mm); 118 GND vias + 58 GND THT pads on the board. SPI_SCLK 0/8, SPI_MOSI 1/10, SPI_MISO 1/9, USB_DP 2/8, USB_DN 0/5, I2C 0/14. Mitigated by the 4-layer stack (F.Cu references the In1 GND plane directly; B.Cu references the +3V3 plane) — a rev-C EMI item, not a function item |
| C: SSR outputs no clamp; nav loom J6 no series R / ESD; display loom J5 no ESD | **open**, rev C. J1/J11/J12 carry SRV05-4s (pin 2 GND, pin 5 VCC verified against the SRV05-4 datasheet: U4 VCC = VBUS, D5/D6 VCC = +3V3) |
| D silk block names | the render shows `24V IN`, `AUX OUT`, `SSR1`, `SSR2`, `TC1`, `TC2`, `CT` above their blocks; per-terminal marks on every screw; `WDT DEFEAT`, `AUX=5V`, `AC SENSE DNP`, `STATUS`, `PWR`, `USB`, `RESET`/`BOOT`, nameplate with rev. Text is upside-down in the enclosure's orientation (struck as unfixable last round) |
| F: `wdt_kick.h` "opto" wording | fixed |
| F: `pin-assignments.md` J11 `+3V3` pin | fixed |
| F: `lid_state.h:17` "defaults to GPIO 21" | **open** — Kconfig default is 4 |
| F: title-block date | **open** — `2026-07-20` hard-coded at `gen_sch.py:1901` and `kicad_build.py:212` |
| F: USB skew claims | **stale** — CLAUDE.md and `README.md:387` still quote 32.3/32.6 mm and 40.1/37.0 mm pairs. Measured pad-to-pad through the copper: USB_DP 42.9 mm (A6) / 39.4 mm (B6) over 6 vias, USB_DN 29.8 / 29.1 mm over 4 vias; 11 % of DP runs within 0.3 mm of DN. Electrically irrelevant at Full Speed; the docs are wrong |
| F: `bench-smoke-test.md` | **open** — still no rev-B steps (SJ2 open, lid jumper or `-1`, 24 V before landing the wire, USB-only back-feed check, SPI clock) |
| I: sourcing | see B |

### E. New findings — rev C unless noted

- **CT anti-alias caps are 30–38 mm from the ADE7953.** U7.5 (IAP) → C31
  38.0 mm / 4 vias (R32 → C31 alone is 21 mm), U7.6 (IAN) → C40 30.5 mm /
  2 vias, U7.9 (IBP) → C32 36.6 mm / 8 vias; CTA_F runs 4.5 mm within
  0.5 mm of I²C_SDA. The RC corner is 4.8 kHz and the chip integrates at
  50/60 Hz, so it measures — but the datasheet puts the filter at the pins,
  and the filtered node is the 1 kΩ side. Move C31/C32/C40 to within ~3 mm
  of pins 5/6/9 (medium).
- **Buck hot loop 39 mm² (perimeter 31 mm).** SW_5V leaves U11 pin 2 on
  F.Cu, crosses to B.Cu through two vias and comes back to D7; D7's anode
  returns to C41/C42's GND pads through In1 (F.Cu pour is not continuous
  along the loop; nearest GND vias 1.0–1.5 mm from each pad). The plane
  0.21 mm below keeps the loop inductance low, so this is an EMI item, not a
  function one; the datasheet's own layout note (p.2) wants the GND pin
  outside the diode-to-output-cap ground path. Rev C: SW_5V on F.Cu only,
  D7 anode adjacent to C42's GND pad (medium).
- **ADE7953 VDD decoupling is 7–8 mm out** (C36 7.0 mm and C35 7.9 mm from
  pin 17, through the +3V3 plane); VINTA/VINTD are 6.9–9.6 mm; MAX31856
  supply caps 5–9 mm (design note acknowledges). Low.
- **TC2_N (raw) is 35.6 mm against TC1_N's 21.4 mm** and runs 5.35 mm
  parallel to TXD0 on B.Cu (UART console edges into the pre-filter leg).
  Low — C22 is on the filtered side.
- **VBUS has no local capacitor or clamp** (Konnect, analyzer). D2 → C1 is
  the only bulk; U4's VCC pin references VBUS. Add 1 µF at J1 in rev C. Low.
- **SJ1 is a 24 V-onto-+5V trap.** With `AUX_VP` fed from the 24 V rail at
  J10.1, bridging SJ1 puts 24 V on +5V (U2 is 6 V abs max; LED1, BZ1 and the
  SSR gate rail follow). The silk says `AUX=5V` and the enclosure README
  says leave it open; add the one-line warning to `jlcpcb/README.md`'s
  bring-up section beside SJ2. Docs.
- **BOM has two rows for C17408** (`100R 1%` R14–R17 and `100R` R6/R19/R11).
  JLC accepts it; merge for tidiness. Nit.
- **Enclosure README** still says "the 5 V supply" (line 4) and "the 5 V
  feed" (line 89) against its own line 207 (24 V in, 5 V made on board).
  Docs.

### F. Confirmed correct this round

- **Power stage wiring vs the XL1509 datasheet:** pin 1 VIN, pin 2 SW,
  pin 3 FB tied to the 5 V output (fixed version, per the typical
  application), pin 4 ON/OFF grounded (active low, "floating is default
  low"), pins 5–8 GND; catch diode D7 cathode on SW; L1 SW → +5V; inductor
  ripple 0.56 A p-p at 24 V, 1.28 A peak against L1's 2.6 A saturation; F1
  hold 0.75 A (≈ 0.5 A derated to 60 °C) against ~0.25 A input; D8 30 V
  standoff / 33.3 V breakdown vs 26.4 V at +10 % trim and the XL1509's 45 V
  abs max; D1 blocks reversed 24 V (D8 conducts forward and F1 trips); D2
  ORing: with both supplies VBUS ≤ 5.25 V against a regulated 5.0 V
  conducts negligibly.
- **Every diode/LED orientation** on the KiCad `Device:D` convention
  (pin 1 = K): D1 K→VIN_P, D2 K→+5V, D3 K→VLED, D4 K→+5V (buzzer flyback),
  D7 K→SW_5V, D8 K→VIN_F, LED2/3/4 cathodes on their resistors.
- **J5 pin order matches the LCDWIKI 14-pin header exactly** (VCC, GND, CS,
  RESET, DC/RS, SDI, SCK, LED, SDO, T_CLK, T_CS, T_DIN, T_DO, T_IRQ); VCC is
  +5V (module accepts 3.3–5 V; its XC6206 makes 3.3 V and its backlight
  draws from VCC, so the display adds nothing to the +3V3 budget). J1 USB-C:
  both D± pairs tied, CC1/CC2 5.1 k, SBU NC, shield to GND. J7: 3V3 GND TX
  RX SDA SCL 3V3 GND with TXD0/RXD0 = GPIO43/44. J14 Qwiic: GND 3V3 SDA SCL.
  J6: five buttons + GND.
- **Watchdog chain** pin-for-pin against SCES586E: A̅ low, B = WDT_KICK
  (rising edge, 5 Hz from the 100 ms SSR timer), CLR̅ high, Q = WDT_OK with
  R49 100 k pulldown, Cext/Rext-Cext on C38 22 µF / R46 100 k, Q3 → SSR_PG
  (R47 100 k to +5V) → Q4 → SSR_EN 0.5 mm to J4.1/J9.1; Q5/Q6 gates through
  R6/R19 100 Ω with R7/R20 10 k pulldowns; SJ2 shorts SSR_PG to GND. Every
  single fault considered (kick stuck high/low, +3V3 lost, MCU in reset or
  download mode, U10 unpowered) leaves SSR_EN off.
- **Reset-state of every dangerous output** is pinned by a resistor:
  SSR1/2_CTRL (R7/R20), AUX1–3 (R23–R25), ALARM (R8), WDT_KICK (R48),
  IO0 (R2 pull-up), EN (R1/C5). LCD_RST (GPIO46) has no pull on the board
  and the module has none on RESET, so BOOT-button download mode is not
  blocked; GPIO45 NC selects 3.3 V VDD_SPI; GPIO3 floats at reset
  (backlight undefined until firmware — cosmetic); N16R2 is quad PSRAM so
  GPIO35/36/37 are free.
- **ADE7953:** CS and SCLK pulled high (R38/R37 10 k) — the datasheet
  requires CS high for I²C; the part locks the interface on first use;
  PULL_HIGH/PULL_LOW tied; XO enable floating = running; VP/VN to R60/R61
  and the DNP J13 only. **No mains-referenced copper exists on the board.**
- **Planes:** In1 GND is one polygon (327 holes, the two largest voids are
  connector anti-pad clusters under SSR_EN at J4 and I²C/RXD0 at J7); In2
  +3V3 is one polygon; the cross-analyzer's "GND 2 islands" is refuted. Every
  decoupling cap's GND pad has a GND via within 1.4 mm.
- **Rails:** VIN/VIN_F/VIN_P/SW_5V 0.8 mm, +5V 0.7 mm, SSR_EN 0.5 mm, VBUS
  0.4–0.5 mm; all above IPC-2221 for their currents.
- **Thermal (estimates, 50 °C ambient):** U2 ≈ 0.5 W average on a 0.3 A
  +3V3 budget (ESP32 + 2 × MAX31856 + ADE7953 + pull-ups; the display is on
  +5V) → Tj ≈ 75–85 °C, ≈ 100 °C at 0.5 A Wi-Fi peaks, inside 125 °C with
  the tab's four vias into In2; U11 ≈ 0.3–0.4 W → Tj ≈ 80–90 °C at the
  datasheet's 100 °C/W free-air figure; D7 ≈ 0.26 W in an SMA. No rev-C
  change needed; measure U2 on board 1.
- **Fab package:** 4 copper + 2 mask + 2 paste + 2 silk + edge + drill +
  map + gbrjob; paste on U7's EP is 9 windows of 0.83 mm (64 %), on U1's
  pad 9 of 0.9 mm (48 %), U2's tab 100 % with its 4 vias inside the mask
  opening (wicking into the +3V3 vias is acceptable on a thermal tab); test
  pads and fiducials carry no paste; FID1–3 at (28.6,33.0) (107.8,28.2)
  (103.4,111.6), 1 mm copper, non-symmetric; parts nearest the routed edge
  are J1 (0.20 mm courtyard, by design for the receptacle), F1 0.70 mm and
  the terminal blocks 0.86 mm, all above JLC's 0.2 mm copper-to-edge with
  copper itself ≥ 0.55 mm. Mask dam and sliver checks pass at JLC's
  0.10 / 0.05 mm.
- **Enclosure fit:** 90 × 90 grid matches `generate_panel_template.py`
  (`PCB_HOLE_GRID = 90.0`); with the south edge up, J5/J6/J7/J11/J14 face
  the display, J1 faces down, J2/J10/J4/J9 face the hinge loom, J3/J8/J12
  the other side, as the enclosure README lays out; grounded M3 holes bond
  board GND to the earthed door as intended.
- **Firmware gates:** MAX31856 driver merged (`#339`: SPI mode 1, 1 MHz,
  CR0/CR1/MASK setup with read-back); TC2_CS and T_CS driven idle-high in
  `main.c:97` before the bus starts; TC1_CS/LCD_CS owned by their drivers;
  WDT kick at 5 Hz; lid default GPIO 4 with the jumper-or-`-1` rule
  documented.

### G. Refuted or downgraded this round

- "U2 has no thermal vias / Tj 94 °C" (thermal analyzer) — four 0.3 mm
  vias in the tab reach the In2 +3V3 plane; the estimate above supersedes.
- "+5V plane split 5 islands", "VBUS plane split", "GND 2 islands",
  46 keepout violations, 39 reference-plane gaps, 8 IO-filtering errors,
  diff-pair skew/layer errors, "LED1 no resistor", "LED1 VDD no DC path" —
  the same artefacts as the last two rounds, re-confirmed against the
  board.
- Konnect "33 single-pin nets" — fused local labels; 0 shorts, 0 orphans,
  102 nets round-trip.
- "F1 0.75 mm from board edge" (PM-002) — 0.70 mm courtyard to a routed
  edge, copper ≥ 0.55 mm; inside JLC's capability and JLC panelises with
  rails for SMT.

### H. Not performed / limits

- The 16-lens adversarial workflow died on the usage limit (17/17 agents,
  1.86 M tokens, zero returns); no finding here has had an independent
  refutation pass. The A1 and C1 judgements rest on the XL1509 datasheet
  text and LM2596-family behaviour, not on a simulation or a scope.
- No SPICE (no simulator installed); no thermal simulation; no EMC
  pre-compliance beyond the loop-area and stitching arithmetic.
- CPL rotations were not re-derived independently this round
  (`check_jlc_placement.py` passes; the 2026-09-02 round verified them
  against LCSC's patterns).
- ESP32-S3 reset pull-state table was not re-read; the reset-state
  conclusions rest on the board's own pull resistors, which cover every
  output that matters.
- Vendor figures recalled rather than fetched: SSR-40DA input current,
  HDR-15-24 output capacitance, 1N4148W typical Vf at 1 mA (the maximum was
  read), MLCC DC-bias curves for C12891/C13585.
- The display module manual on disk is the MSP3520 (3.5") manual; the
  MSP4021 shares the 14-pin header order and voltage spec, per LCDWIKI, but
  the 4.0" manual itself was not fetched.

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
| A3 J11 marks | **downgraded - the premise is a measurement artefact**, see below |
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

**A3 is mostly not a defect, and the fix was reverted.** The review reports
the four marks as wedged into 1.57 mm "with 0.02 / 0.09 mm" of margin. Those
are KiCad **bounding boxes**, not ink. A bbox is ~1.9x the glyph, so a 0.8 mm
mark gets a 1.50 mm box: the boxes touch their neighbours while the printed
strokes are nowhere near them.

Measured off `gerbers/bisque-controller-F_Silkscreen.gto`, which is what the
fab actually images:

| | value |
|---|---|
| ink, centreline | y 107.342 .. 108.142 (0.80 mm, the nominal glyph) |
| ink edge, +/- half the 0.16 mm stroke | y 107.262 .. 108.222 |
| clearance to J6/J7's outline (107.05) | **+0.212 mm** |
| clearance to J11's outline (108.62) | **+0.398 mm** |

(`GND` first measured 1.15 mm tall; three of those points sit at a single y
across 1.63 mm of x, which is J7's outline running through the window, not a
glyph. All four marks are 0.80 mm.)

They are also **0.8 mm like 228 of the board's 245 silk texts** - the JLC
floor the whole board is drawn at, not a size unique to this connector.

So there is nothing to fix by moving parts. What moving parts would buy is
printing these four at 1.0 mm, and that is blocked by the silk placer's
bounding-box model rather than by the board: a 1.0 mm glyph carries a 1.88 mm
box against a 1.57 mm gap, while its *ink* would still clear by 0.285 mm each
side. If the 1.0 mm is ever wanted, the cheap route is teaching the placer to
collide on ink for locked legends - not relaying the south edge.

For the record, the relayout was implemented before this was measured, and
J11's four marks are x-locked over their own pins and
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
