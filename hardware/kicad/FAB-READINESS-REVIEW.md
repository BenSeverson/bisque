# JLCPCB Fabrication Readiness Review

Board: `bisque-controller` — 2-layer, 100 × 80 mm, 1.6 mm, 49 footprints (36 SMD / 9 THT + 4 mounting holes)
Reviewed: 2026-07-29 against KiCad 10.0.5, analyzer run `analysis/2026-07-29_1621/`
Status: **blockers resolved 2026-07-29** — see "What was fixed" below.

## Verdict

**Ready to order, bare or assembled**, with two things to eyeball in JLCPCB's
order preview (polarized two-terminal part orientation, and through-hole
assembly availability). Everything that was a hard blocker has been fixed.

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

Still worth a glance at the placement preview for D1–D4 and LED1–LED3: the cost of
looking is zero and the cost of a flip is a dead board.

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

## Still worth fixing (quality, not blockers)

- **Six untented vias in SMD pads** — `R9:2, R10:2, D4:2, U1:8, U3:7, U4:1, U4:6`
  (0.3 mm drill, same net). Solder wicks down an open via during reflow, reducing joint
  volume. Either move the via off the pad or tent it with mask. This needs a board
  change, so it was left alone.
- **0.15 mm dangling VBUS track** at (98.45, 89.60) — KiCad flags it as `track_dangling`,
  locally downgraded to a warning. The net is electrically complete (the 0.4 mm-wide
  tracks overlap across a 0.05 mm centreline offset), so this is a leftover fragment, but
  it is the one DRC item that is not silkscreen noise.
- **No fiducials** (36 SMD parts). JLCPCB works from board edges and does not require
  them, so this is optional — but the analyzer rates it an error against IPC-7351.
- **U2 (AMS1117-3.3) dissipates 0.72 W with no thermal vias.** Tj ≈ 68 °C at 25 °C
  ambient (57 °C margin), but this is a kiln controller: at 50 °C enclosure ambient it
  lands near 93 °C. Vias under the SOT-223 tab are cheap insurance.
- **No test points** on any of 39 nets. Fine for a hobby board, awkward for bring-up.
- **No ESD/TVS on J4 (SSR drive)**, which runs off-board toward mains wiring. There is a
  100 Ω gate series and 10 kΩ pulldown, and an SSR input is resistive so no flyback is
  needed — but a surge path back into the MOSFET gate is a real robustness gap.
- **Through-hole assembly availability.** Nine THT parts mean JLCPCB **Standard**
  assembly (Economic is SMD, top-side only), and JLC's through-hole coverage is narrower
  than its SMD coverage. All nine now have in-stock LCSC parts, but confirm at order time
  that JLC will actually place them. The BOM flags each THT line for this.

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

  DFM tier: standard, 0 violations. Vias are uniform 0.6/0.3 mm through-hole (197 of
  them). `kicad_build.py` deliberately upsizes the library's 0.2 mm module thermal-via
  drills to 0.3 mm to stay inside the standard drill range — confirmed in the drill file,
  whose smallest tool is 0.300 mm.
- **CPL is faithful to the built board** — all 45 positions match the raw `.kicad_pcb`
  exactly, with rotations differing only by the five intended corrections above. All
  parts top-side, so single-sided assembly. The 4 mounting holes are correctly absent
  from both BOM and CPL.
- **All 28 LCSC part numbers resolve to the intended part and are in stock** (verified
  live against LCSC and jlcsearch on 2026-07-29). 18 Basic, 10 unique Extended. Lowest
  stock is U3 MAX31855 at 2,145. No BOM line carries a `CONFIRM` or blank marker any more.
- **Paste layer is correct** — 149 apertures for exactly 149 paste-enabled SMD pads. The
  analyzer's GR-004 "149 paste vs 428 copper" is a false positive: the copper count
  includes 90 through-hole pads and 197 vias. (U1 pad 41, the module's centre ground pad,
  has mask but no paste — upstream KiCad footprint behaviour, and 13 thermal vias carry
  the ground/thermal path.)
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
  AMS1117-3.3, AO3400A, WS2812B); the AO3400A and AMS1117 files failed the sync's own
  keyword verification, so treat them as unconfirmed. **MAX31855 and USBLC6-2SC6
  datasheets could not be downloaded** (ADI and LCSC both refused). Their pinouts above
  were checked against package conventions and symbol pin names, not the manufacturer PDF
  — a consistency-plus-domain-knowledge check, not a datasheet-verified one. The
  analyzer's `DS-001` finding reflects this.
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
