# JLCPCB Fabrication Readiness Review

Board: `bisque-controller` — 2-layer, 100 × 80 mm, 1.6 mm, 52 footprints (41 SMD / 7 THT + 4 mounting holes)
Reviewed: 2026-07-29 against KiCad 10.0.5, analyzer run `analysis/2026-07-29_1621/`
Status: **blockers resolved 2026-07-29** — see "What was fixed" below.
Update 2026-07-30: display moved from +3V3 to +5V — see "Display moved to +5V" below.
Update 2026-07-30: assembly cost reduction + via-in-pad fix — see "Cost reduction pass" below.
Update 2026-08-05: lid-switch input filter added (R12/R13/C12) — see "Lid switch input filter" below.

## Verdict

**Ready to order, bare or assembled.** Everything that was a hard blocker has been
fixed, and the one remaining thing to eyeball in JLCPCB's order preview is the
orientation of the polarized two-terminal parts (D1–D4, LED2, LED3).

The through-hole-assembly question that used to sit here is gone: as of the cost-reduction
pass below there are no through-hole parts in the assembly BOM at all, so the order is
Economic (SMD, top-side) and nothing depends on JLC's narrower THT coverage.

## What was fixed

### 1. C9 was the wrong package — fixed

The BOM assigned C9 (10 nF thermocouple input filter) to LCSC **C57112**, which is
`0603B103K500NT`, an imperial **0603** capacitor, on an 0805 land pattern. Every other
passive matched its LCSC package; this one did not.

Now **C1710** (`CL21B103KBANNNC`, 10 nF 50 V X7R 0805, Basic part) — correct package,
same voltage rating and dielectric.

### 2. Six designators had no LCSC part number — fixed

`BZ1, J5, J6, J7, SW1, SW2` shipped with a blank `LCSC Part #`, so JLCPCB would not have
populated them. All six are through-hole. Each now has a verified part:

| Ref | LCSC | Part | Stock |
|---|---|---|---|
| BZ1 | C96093 | TMB12A05 active magnetic buzzer, 5 V, 12 mm THT, 7.6 mm pitch | 17k |
| J5, J7 | C240822 | Molex 22-27-2081 KK-254 wafer 1×08 vertical | 1.5k |
| J6 | C239381 | A2547WV-6P KK-254 wafer 1×06 | 1.6k |
| SW1, SW2 | C393938 | TS665CJ 6×6 mm THT tactile switch, 5 mm | 169k |

`A2547WV-8P` (C239383) was rejected for J5/J7 — zero stock. The genuine Molex part is
carried instead.

Consequence worth noting: four of these are Extended parts, so the board now carries ten
unique Extended parts rather than six. Full assembly costs more than the previous
SMD-only-plus-hand-soldering plan. That is the expected price of dropping the
hand-solderable constraint, not a regression.

*(Superseded 2026-07-30 — the cost-reduction pass below puts the through-hole parts back
on a soldering iron and takes the board to four unique Extended parts. Note also that the
count of through-hole Extended parts was **five**, not six as originally written here and
in the README: C8465, C240822, C239381, C96093, C393938.)*

### 3. CPL carried no JLCPCB rotation correction — fixed

`gen_jlc.py` wrote the raw KiCad angle straight through and deferred rotation checking to
the order preview, which does not reliably catch 180° errors on polarized parts.

`gen_jlc.py` now has a `JLC_ROTATION` table applied during CPL generation, and prints
every correction it makes so a regeneration is auditable. Five parts are corrected:

| Ref | Footprint | KiCad | CPL | Offset |
|---|---|---|---|---|
| U2 | SOT-223-3_TabPin2 | 0° | 180° | +180 |
| Q1 | SOT-23 | 0° | 180° | +180 |
| Q2 | SOT-23 | 0° | 180° | +180 |
| U4 | SOT-23-6 | 90° | 270° | +180 |
| U3 | SOIC-8_3.9x4.9mm_P1.27mm | 90° | 0° | +270 |

**Correction to this review's first draft.** The initial version of this document listed
a wider offset table taken from generic guidance — including +180° for the SMA diodes
(D1–D3) and SOD-123 (D4), and "verify" for the LEDs, USB-C and the WS2812B. That was
heuristic and, for the diodes, would have been actively harmful: applying +180° to D1/D2
would have reversed the reverse-polarity protection Schottkys.

The offsets above instead come from the community-maintained table in
[bennymeg/Fabrication-Toolkit](https://github.com/bennymeg/Fabrication-Toolkit)
(`plugins/transformations.csv`), which is derived from real JLCPCB order feedback. That
table has **no** entry for SMA, SOD-123, chip passives, chip LEDs, PLCC-4, USB-C,
terminal blocks, 2.54 mm headers or 6 mm tactile switches — for those families KiCad's
orientation already matches JLCPCB's. Only multi-pin plastic and gull-wing packages
(SOT-23, SOT-223, SOIC) need correcting, which is consistent with how EIA-481 tape
orientation differs from KiCad's footprint convention for exactly those bodies.

Still worth a glance at the placement preview for D1–D4 and LED2/LED3 (LED1 is
hand-fitted now, so it is not in the CPL): the cost of looking is zero and the cost of a
flip is a dead board.

### 4. Gerbers were stale — fixed

`gerbers/` was exported at 19:34 (per the drill file's own timestamp) and the board was
rewritten later, then committed again in `c5801e6` after the last gerber commit
`54fc15c`.

Re-exported with KiCad 10.0.5. Comparing geometry with apertures resolved, the old and
new outputs are byte-identical on B_Cu, F/B_Mask, F/B_Paste, F/B_Silkscreen, Edge_Cuts
and the drill file. F_Cu differs by exactly three GND-pour outline vertices near the
USB-C connector collapsing to two, shifting about 80 µm — the zone refill moving to
`kicad-cli` in `c5801e6`. Electrically irrelevant, but the fab package now matches the
committed board.

Root cause addressed too: the README's regen workflow documented
`kicad-cli pcb export gerbers -o gerbers/`, which does not reproduce the committed layer
set (it also emits Fab/Courtyard/User layers) and omitted the drill export and
`gen_jlc.py` entirely. The workflow now lists the full fab-output regeneration with the
correct `--layers` list and drill flags, plus a note that zone fills must be current
before export.

## Display moved to +5V (2026-07-30)

The user is building with a specific 4.0" LCDWIKI ST7796S module (MSP4020/MSP4021,
480×320 — same resolution and driver IC the firmware already targets, just larger
glass) and asked to move it from +3V3 to +5V power.

**Pin compatibility verified against the module's own manual** (extracted directly —
LCDWiki's product page returned generic marketing copy, and the linked PDF turned out
to be a 24-page scan with no embedded fonts, so `WebFetch`'s text extraction failed
silently; rendering it with PyMuPDF and reading the real text got the actual pin table).
Pins 1–8 are VCC/GND/CS/RESET/DC/SDI(MOSI)/SCK/LED — an exact match for J5's existing
8-pin assignment, so no connector or footprint change was needed. VCC is rated
"3.3V~5V", and every reference wiring diagram in the manual — including the 3.3V-logic
STM32 boards — ties VCC to 5V while driving CS/RESET/DC/MOSI/SCK directly from 3.3V
GPIOs with no level shifter shown. MISO/SDO and the five touch pins (touch variant
only) aren't wired, consistent with current firmware not reading from the panel.

**Change made:** `J5` pin 1 and `C12` (its local decoupling cap, previously the
identified purpose of that cap) moved from `+3V3` to `+5V` in `design.py`. The
hardcoded silkscreen pin label at J5 (`gen_pcb.py`'s `J5_PINS` list, shared with
`kicad_build.py`) updated from `"3V3"` to `"5V"` — this list is plain strings, not
derived from the net, so it would otherwise have silkscreened a label that no longer
matched the copper. J7's `"3V3"` label is untouched and still correct (J7 pin 1 stays
on +3V3). Schematic netlist round-trip still passes (42 nets, 0 mismatches — renaming
an existing net doesn't add one).

**This is the actual fix for the AMS1117 thermal margin flagged below**, more so than
the +3V3 ground-pour improvement that section proposed. The display's backlight and
panel logic were the single largest unmodeled load on U2 — the schematic analyzer's
power budget only sums ICs on a rail (240 mA for U1 + 5 mA for U3, missing the display
entirely), which is what made the analyzer's own 68 °C estimate too optimistic in the
first place. With that load moved to +5V, U2's load is back to just U1 + U3 (~245 mA),
and recomputing at the AMS1117 datasheet's own baseline θJA (90 °C/W for SOT-223 — see
the correction below) gives Tj ≈ 90 °C at a 60 °C enclosure ambient, comfortably under
the 125 °C limit, without needing the ground-pour change at all. +5V picks up the
extra ~150–180 mA display current instead; that rail is already uniformly 0.7 mm and
the current no longer passes through a lossy LDO stage, so no board changes were
needed there.

**Regenerating the board surfaced a real (if narrow) DRC regression, now fixed in the
generator.** Renaming J5/C12's net changes both nets' terminal sets, which changes
what the router's Steiner-tree pathing produces for +3V3 and +5V — including a new
+5V track near (84, 72) that hadn't existed before. That, combined with real KiCad
zone-fill clearances, left one of the 197 GND stitching vias (placed by `stitch_vias()`
on a fixed grid, unrelated to any component) isolated from copper on one layer.
`heal_islands()` didn't catch it because it only bridges pour *islands lacking a via*,
not a via sitting in a clearance gap the real fill carves out — a different failure
mode. Added `drop_disconnected_stitch_vias()` to `kicad_build.py`: after the
refill+DRC pass, it parses the DRC report for any `Via [GND]` the connectivity check
still calls unconnected and removes it (never touches a via on any other net — GND has
no point-to-point routing per the `route_all()` assert, so every GND via is decorative
stitching, safe to drop; a real signal via being unconnected would be a genuine bug and
this code path can't touch one). Verified deterministic across two rebuilds; DRC now
reports 0 errors / 0 unconnected again (14 violations, same composition as before: 7
silkscreen-clearance, 6 silkscreen-clipped-by-mask, 1 dangling VBUS stub), and
`check_pcb.py`'s independent connectivity check still passes (975 items — one fewer
than before, the dropped via).

Gerbers, drill, drill map, BOM, CPL, schematic PDF and the board preview were all
regenerated from the rebuilt board.

## Cost reduction pass (2026-07-30)

Goal: cut JLCPCB assembly cost, accepting hand-soldering for larger parts. Every LCSC
tier/price figure below was re-checked live against the catalog on 2026-07-30.

**Where the money was going.** The BOM is $9.83/board and 76 % of that is two chips
(ESP32-S3 module $5.15, MAX31855 $2.37). Against that, ten unique Extended parts were
costing a flat **$30** in feeder fees, and nine through-hole parts forced Standard
assembly. $15 of those fees bought placement of $1.53/board of connectors and a buzzer.

**Changes:**

1. **SW1/SW2 THT → SMD.** XKB TS-1187A (`C318884`) is a JLCPCB **Basic** part — $0.018,
   918k stock — and KiCad ships the matching footprint
   (`Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A`, pads numbered 1/1/2/2, a drop-in for
   the existing `SW_Push` symbol). Removes one feeder fee *and* two through-hole parts
   while keeping them machine-placed. Both switches moved to clear DRC: SW1 to
   (55.0, 23.2) — its pads were 0.25 mm from the board edge against a 0.3 mm rule — and
   SW2 to (101.0, 50.2), since the new courtyard overlapped U1's (which extends to
   y = 46.49, taking in the antenna keep-out).
2. **Seven through-hole parts + LED1 hand-fitted.** `HAND_SOLDER` in `gen_jlc.py` drops
   BZ1, J2–J7 and LED1 from both BOM and CPL (they must leave together — JLCPCB rejects a
   CPL with designators the BOM lacks) and writes `jlcpcb/hand-solder-parts.csv` instead.
3. **LED1 specifically.** Checked whether the WS2812B could stay on the line for free: no
   addressable RGB LED at LCSC is a Basic part, across WS2812/SK6812/XL-xxxx. Replacing it
   with discrete R/G/B 0805s is worse, not better — KT-0805B (blue) is Extended and
   KT-0805R (red) had 10 in stock, so it would re-add feeder fees, burn three GPIOs and
   need `components/status_led/` rewritten. Hand-soldering a 5050 with four
   edge-accessible pads is the cheap answer.

**Result: 10 unique Extended parts → 4** (module, MAX31855, USBLC6, USB-C), so $30 → $12
in feeder fees, and Standard → **Economic** assembly. This also retires the "confirm JLC
will place the THT parts" risk entirely.

Considered and rejected: cheaper module variants (N16R2 saves $0.53/board but needs
`CONFIG_SPIRAM_MODE_OCT` → quad; N8R8 saves $0.43 but the 16 MB partition table does not
fit 8 MB); a TVS on J4 (no Basic-part TVS exists at LCSC, so it would cost a fifth feeder
fee); consolidating resistor values (all Basic already — saves nothing). The bare board is
already at the cheapest fab tier and nothing about it changed.

### Via-in-pad — fixed

The item below understated this: the real count was **14 via/pad conflicts** across 12
designators (`C5.1, C10.2, D4.2, LED3.1, R9.2, R10.2, U1.8, U1.9, U1.19, U3.6, U3.7,
U4.1, U4.2, U4.6`), not six. All were **same-net**, which is exactly why KiCad's DRC never
reported one — clearance rules skip same-net copper, so the defect was invisible to the
existing checks.

Root cause was in `router.py`: `via_ok()` tested clearance via `_clear_of()`, which skips
obstacles on the via's own net, so a via could legally land on top of a pad it shared a
net with. Added `VIA_PAD_GAP` (0.15 mm) — SMD pads now block via placement regardless of
net. Tenting was not an option: the pad's own mask opening exposes the barrel anyway, and
filled-and-capped via-in-pad is a JLCPCB upcharge.

New checker `generator/check_via_in_pad.py` verifies this, hit-testing against pcbnew's
real pad shapes rather than re-deriving rotated geometry from the board text. It reports
14 conflicts on the previous board and 0 on the current one.

Two latent bugs surfaced while making the above pass DRC, both now fixed:

- **`heal_islands()` counted any via as an anchor**, including signal vias, which are
  isolated from a GND pour by clearance and bridge nothing.
- **`heal_islands()` only handled islands with *no* anchor.** The new build produced a
  different failure: a group of three islands (one F.Cu, two B.Cu) bridged to each other
  but never back to the main pour. Every island had a via, so the old test passed them all
  while KiCad reported "Missing connection between Zone [GND] and Zone [GND]" and the
  function printed "healed 0". Rewritten around a union-find over islands linked by
  layer-bridging GND points; anything outside the largest component gets a via placed where
  it overlaps main-component copper on the opposite layer. One via at (96.8, 72.8) now
  heals it.
- **`check_pcb.py` squared circles off to their bounding box** when measuring pad-to-via
  clearance, over-reporting by up to (√2−1)·r on a diagonal. That invented two clearance
  failures for a via sitting off C5's pad corner — geometry KiCad's exact-shape DRC passes
  at 0.290 mm against a 0.2 mm rule. Now exact for circle-vs-rect. It still passes the
  previous board, so this did not mask a real finding.

C5 also moved (rotated 90° in place) so its GND pad faces open pour: at rot 0 the sliver
between C5, R1 and the module was too narrow to take a stitching via once vias were barred
from pads, stranding the pad on F.Cu.

### Verification after the pass

- **KiCad DRC**: 14 violations, **0 errors, 0 unconnected pads, 0 footprint errors** —
  same composition as before (7 silkscreen-clearance, 6 silkscreen-clipped-by-mask, 1
  dangling VBUS stub).
- **`check_pcb.py`**: ALL CHECKS PASS (989 copper items).
- **`check_via_in_pad.py`**: PASS, 196 vias vs 158 SMD pads.
- **Netlist round-trip**: 42 nets, 0 mismatches.
- **BOM/CPL parity**: 37 designators each, no orphans either way, no line without an LCSC
  part, no overlap with the 8 hand-soldered refs.
- **Determinism**: two consecutive rebuilds give byte-identical tracks (560 segments) and
  vias (196), and the same island structure. The F.Cu zone fill differs by 2 vertices out
  of 7352 — KiCad's filler, the same sub-micron nondeterminism already noted for the
  gerber re-export above.
- Gerbers, drill, drill map, BOM, CPL, hand-solder list, preview SVG, schematic PDF and
  the 3D renders were all regenerated from the rebuilt board. Smallest drill is still
  0.300 mm.

## Lid switch input filter (2026-08-05)

`LID_SW` (IO21, aux header J7 pin 6) was a bare GPIO on a header pin, relying on the
ESP32's internal ~45 kΩ pull-up. Firmware issue #83 turns it into a **firing
interlock**, so a false "lid open" now cuts a firing — and unlike the nav switch's
short in-enclosure run, this cable goes to a hot kiln lid alongside the SSR output and
mains wiring.

**Change made:** J7 pin 6 now lands on a new net `LID_IN` and reaches U1.23 (`LID_SW`)
through **R12** (1 kΩ series), with **R13** (10 kΩ) to +3V3 and **C12** (100 nF) to
GND. Corner ≈ 1.8 kHz with the switch closed (C12 across R12∥R13 ≈ 0.9 kΩ), ≈ 160 Hz
with it open — fast enough to leave mechanical bounce to the firmware's 500 ms
sampling, slow enough to swallow EMI transients.
Closed-switch level 3.3 V × 1k/11k = 0.30 V, inside the ESP32's 0.25 × VDD (0.83 V)
V_IL.

No discrete TVS was added: the only one on the board is the USBLC6 (U4), fitted for
USB 2.0's low-capacitance requirement, and the other externally exposed nets (TC_P at
J3, the nav switch at J6) rely on an RC plus the pin's own clamp diodes. A TVS would
have added a unique **Extended** part ($3 feeder fee) for one input and been
inconsistent with the rest of the board.

**Assembly impact: none beyond three joints each.** All three parts reuse LCSC lines
already on the BOM — C17513 (1 kΩ), C17414 (10 kΩ), C49678 (100 nF), all **Basic** —
so the BOM stays at 24 lines / 23 unique parts / 4 Extended, and $12 of feeder fees.
Placements 37 → 40, machine-soldered joints 170 → 176 (+$0.01/board).

**Verification:** KiCad 10.0.5 DRC **0 errors, 0 unconnected** (14 violations, all the
same silk/lib-path warnings as before); `check_pcb.py` ALL CHECKS PASS;
`check_via_in_pad.py` PASS; `check_canonical.py` ALL CHECKS PASS; schematic netlist
round-trip 43 nets, 0 mismatches; rebuild byte-identical.

**Placement note:** R12 and C12 sit in the free band between LED1 and J7 so the shunt
is at the point of entry. R13 is 6 mm north, on the +3V3 B.Cu trunk — placing it
beside C12 forced a 0.7 mm +3V3 spur across the F.Cu pour above J7 pins 1–2 and
starved J7 pin 2's thermal relief (a DRC *error*, not a warning). A pull-up's position
is electrically irrelevant, so it moved rather than the pour being patched.

## Still worth fixing (quality, not blockers)

- **0.15 mm dangling VBUS track** at (98.45, 89.60) — KiCad flags it as `track_dangling`,
  locally downgraded to a warning. The net is electrically complete (the 0.4 mm-wide
  tracks overlap across a 0.05 mm centreline offset), so this is a leftover fragment, but
  it is the one DRC item that is not silkscreen noise.
- **No fiducials** (36 SMD parts). JLCPCB works from board edges and does not require
  them, so this is optional — but the analyzer rates it an error against IPC-7351.
- **No test points** on any of 39 nets. Fine for a hobby board, awkward for bring-up.
- **No ESD/TVS on J4 (SSR drive)**, which runs off-board toward mains wiring. There is a
  100 Ω gate series and 10 kΩ pulldown, and an SSR input is resistive so no flyback is
  needed — but a surge path back into the MOSFET gate is a real robustness gap. Adding one
  costs a fifth $3 feeder fee (no Basic-part TVS at LCSC), so hand-solder it if wanted.
- **SMD tact switches are held by solder pads only**, where the previous 6 mm through-hole
  part had legs through the board. Fine for RESET/BOOT, which are pressed rarely; worth
  knowing if the enclosure ever pushes on them.

## Verified good

- **DRC** re-run on the current board with KiCad 10.0.5: 14 violations, **0 errors,
  0 unconnected pads, 0 footprint errors**. Thirteen of the fourteen are silkscreen
  overlap/clipping; the fourteenth is the VBUS stub above.
- **JLCPCB 2-layer capability** — every metric clears with margin:

  | Metric | Board | JLCPCB min |
  |---|---|---|
  | Min track width | 0.25 mm | 0.127 mm |
  | Min spacing | 0.20 mm | 0.127 mm |
  | Min drill | 0.30 mm | 0.20 mm |
  | Min annular ring | 0.15 mm | 0.125 mm |
  | Board size | 100 × 80 mm | 6 × 6 mm |
  | Thickness | 1.6 mm | 0.4–2.4 mm |

  DFM tier: standard, 0 violations. Vias are uniform 0.6/0.3 mm through-hole (196 of
  them). `kicad_build.py` deliberately upsizes the library's 0.2 mm module thermal-via
  drills to 0.3 mm to stay inside the standard drill range — confirmed in the drill file,
  whose smallest tool is 0.300 mm.
- **CPL is faithful to the built board** — all 37 positions match the raw `.kicad_pcb`
  exactly, with rotations differing only by the five intended corrections above. All
  parts top-side, so single-sided assembly. The 4 mounting holes and the 8 hand-soldered
  parts are correctly absent from both BOM and CPL.
- **All 28 LCSC part numbers resolve to the intended part and are in stock** (verified
  live against LCSC and jlcsearch on 2026-07-29, re-checked 2026-07-30). The assembly BOM
  carries 23 of them — 19 Basic, 4 Extended — and the hand-solder list the other 5. Lowest
  stock among machine-placed parts is U3 MAX31855 at 2,145; the KK-254 wafers are lower
  still (8.2k / 4.5k) but are hand-fitted now, so they are not tied to LCSC at all.
  No BOM line carries a `CONFIRM` or blank marker.
- **Paste layer is correct** — 157 apertures for exactly 157 paste-enabled SMD pads (149
  before, plus 8 for the two new SMD tact switches). The analyzer's GR-004 "paste vs
  copper" finding is a false positive: the copper count also includes through-hole pads
  and vias. (U1 pad 41, the module's centre ground pad, has mask but no paste — upstream
  KiCad footprint behaviour, and 13 thermal vias carry the ground/thermal path.)
  Note the stencil still carries apertures for LED1, which is hand-fitted; harmless, and
  useful if you paste it rather than using an iron.
- **Both GND zones are filled** (F.Cu 69.9 %, B.Cu 84.4 %).
- **Schematic netlist round-trip passes** after the title-block edit: 42 nets, 0 mismatches.
- **Pin maps verified** for U1, U2, U3, U4:
  - U1 ESP32-S3-WROOM-1-N16R8: **IO35/IO36/IO37 correctly left unconnected** — the
    N16R8's octal PSRAM uses them internally. EN has the standard 10 kΩ + 1 µF RC.
    IO45 (VDD_SPI select) left NC so the internal pulldown picks 3.3 V. IO46 (LCD_RST)
    and IO3 (LCD_BL) are strapping pins used as outputs — benign here, and IO46's
    internal pulldown conveniently holds the display in reset through boot.
  - U2 AMS1117-3.3 SOT-223: 1=GND, 2=VO (tab), 3=VI, footprint `TabPin2`. Correct.
  - U3 MAX31855KASA+ SOIC-8: 1=GND, 2=T−(to GND), 3=T+, 4=VCC, 5=SCK, 6=CS, 7=SO, 8=NC.
    Matches the standard pinout; T− grounded and the 10 nF differential filter across the
    inputs both follow the datasheet's typical application.
  - U4 USBLC6-2SC6 SOT-23-6: 1/6=I/O1 (USB_DN), 2=GND, 3/4=I/O2 (USB_DP), 5=VBUS. Correct.
- **The reported +3V3 / VBUS "plane splits" are analyzer artifacts, not real opens.** The
  generator's router connects copper by overlap and mid-segment T-junctions rather than
  exact shared endpoints — e.g. the +3V3 segment ending at (61.60, 31.60) lands on the
  interior of the segment spanning (61.60, 30.40)–(61.60, 32.80), and the VBUS tracks meet
  with a 0.05 mm centreline offset between 0.4 mm-wide traces. KiCad's connectivity engine
  resolves both correctly, which is why DRC reports 0 unconnected. The same root cause
  explains the GP-001 reference-plane-gap and RP-001 stitching-via findings.
- **EMC** risk score 28. Nothing fab-blocking. `DC-002` (no decoupling near U4) is a false
  positive — the USBLC6 is a diode array with no supply pin to decouple. `CERT-001` notes
  the wireless module; the ESP32-S3-WROOM-1 carries modular certification.

## Not performed / limits on confidence

- **SPICE simulation skipped** — no `ngspice`, `ltspice`, or `xyce` on this machine.
  Value-computation checks on the EN RC and LED current-limiting resistors are static only.
- **Datasheet coverage is partial.** LCSC sync retrieved 4 PDFs (ESP32-S3-WROOM-1,
  AMS1117-3.3, AO3400A, WS2812B); the sync's own keyword verification flagged AO3400A
  and AMS1117 as unconfirmed. For AMS1117 this was a false alarm, found while digging
  into the thermal numbers: it *is* the genuine Advanced Monolithic Systems datasheet
  (confirmed by extracting the θJA / dropout / current-limit tables directly), the
  keyword check just failed because the PDF stores text glyph-by-glyph with a space
  after every character, which a naive substring search doesn't match. AO3400A likely
  has the same issue but wasn't re-checked. **MAX31855 and USBLC6-2SC6 datasheets could
  not be downloaded** (ADI and LCSC both refused). Their pinouts above were checked
  against package conventions and symbol pin names, not the manufacturer PDF — a
  consistency-plus-domain-knowledge check, not a datasheet-verified one. The analyzer's
  `DS-001` finding reflects this.
- **Rotation offsets are empirical, not vendor-published.** JLCPCB does not publish a
  per-package rotation reference; the `JLC_ROTATION` table is the community consensus.
  It is far better than no correction, but the order preview remains the final check.
- **THT assembly availability not confirmed.** Stock and part identity are verified; JLC's
  willingness to place each through-hole part is not something the LCSC API exposes.
- **No formal lifecycle/EOL audit** — no NRND/obsolete status queried (`--lifecycle` not
  run; no distributor API keys configured).
- **Board PDF (`pdf/bisque-controller-board.pdf`) not regenerated** — `kicad-cli pcb
  export pdf` requires an explicit layer list and the original set is not recorded, so
  reproducing it would have been guesswork. Its visible content is unchanged (the only
  board delta is the sub-0.1 mm pour edge).
- Thermal estimate assumes 25 °C ambient; enclosure ambient was not modelled.
