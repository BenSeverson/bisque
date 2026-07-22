# Bisque Kiln Controller — KiCad PCB

A single-board replacement for the perfboard build documented in
`docs/perfboard-layout.svg` / `docs/wiring-diagram.svg`. 2-layer,
100 × 80 mm, **hand-solderable throughout**: the smallest parts are 0805
passives, SOIC-8, SOT-23 and the ESP32-S3-WROOM-1 module's castellated
pads. No BGA, no QFN, no bare chips.

Built and validated with **real KiCad** (10.0.4, pcbnew Python API +
kicad-cli): footprints come from KiCad's installed libraries, ground pours
are filled and checked by `kicad-cli pcb drc --refill-zones` — **zero
errors, zero unconnected** (`bisque-controller-drc.rpt`) — and the
schematic passes a netlist round-trip check (KiCad's exported netlist
diffed against the design's connectivity table — 42 nets, 0 mismatches).
The 3D renders in `3d/` are raytraced by `kicad-cli pcb render` with the
official component models.

| File | What it is |
|---|---|
| `bisque-controller.kicad_pro` | Project (net classes: 0.3 mm signal / 0.7 mm power, 0.2 mm clearance) |
| `bisque-controller.kicad_sch` | Schematic (A3, netlist-style: functional groups + global labels) |
| `bisque-controller.kicad_pcb` | Board: placed, fully routed, GND pours on both layers |
| `preview-board.svg` | Quick visual of placement + routing |
| `3d/board-3d-*.png` | Raytraced renders, kicad-cli (iso / front / top / underside) |
| `bisque-controller-drc.rpt` | KiCad DRC report (0 errors; warnings are silk/lib-path noise) |
| `gerbers/` | Fabrication outputs (kicad-cli: gerbers + Excellon drill + job file) |
| `pdf/` | Schematic and board PDFs (kicad-cli) |
| `jlcpcb/` | Assembly BOM + CPL for JLCPCB |
| `generator/` | Scripts that build everything from one connectivity table |

## Opening it

Open `bisque-controller.kicad_pro` in KiCad 7 or newer. Zones ship
**filled** (KiCad's own filler) and the board already passes KiCad DRC;
re-run it after any edit. The schematic embeds its symbols; the board
references the standard KiCad footprint libraries (and was generated from
them).

## What's on the board

- **U1 — ESP32-S3-WROOM-1-N16R8** module (16 MB flash / 8 MB octal
  PSRAM — matches `sdkconfig.defaults` + the 16 MB OTA partition table) at
  the top edge, antenna keep-out
  strip kept copper-free (the official footprint's rule area).
- **Power**: 5 V DC in on screw terminal **J2** (top-left) *or* USB-C; each
  source feeds the +5 V rail through an SS34 Schottky (D1/D2 — also reverse
  polarity protection), then an **AMS1117-3.3** (U2, SOT-223) makes 3V3.
  Power LED (green) on 3V3.
- **Thermocouple**: **MAX31855KASA+** (U3, SOIC-8) bottom-right, K-type on
  screw terminal **J3** (`K+` / `K-`, K− grounded at the chip per datasheet),
  10 nF filter across the inputs, shares the SPI bus (MISO + its own CS).
- **SSR drive**: screw terminal **J4** supplies a +5 V / SSR− loop switched
  low-side by an AO3400A (Q1) with 100 Ω gate series and 10 kΩ pull-down so
  the kiln stays **off during boot/reset**. Amber LED shows drive state.
  (The SSR itself and all mains wiring stay outside this board.)
- **Display**: 8-pin Molex KK-254 friction-lock header **J5** for the 3.5"
  ST7796S SPI module (`3V3 GND CS RST DC SDI SCK BL` — silkscreened per pin).
- **Nav switch**: 6-pin KK-254 friction-lock header **J6** for the
  panel-mounted 5-way switch (`UP DN LT RT OK GND`, active-low, ESP32
  internal pull-ups).
- **Aux header J7** (8-pin KK-254): `3V3 GND TX RX VNT LID A15 A16` — UART0
  plus the optional VENT (IO14) / LID_SWITCH (IO21) firmware GPIOs and two
  spares.

  All three headers are polarized: the mating friction-lock housing only
  latches one way, so the display/nav/aux looms can't be plugged in
  reversed. Solder the headers with the latch ramp on the board-interior
  side (as in the 3D renders) so all housings face the same way; pin 1 is
  the square pad / silk arrow.
- **USB-C (J1)** for native-USB flashing: 5.1 kΩ CC resistors, USBLC6-2SC6
  ESD protection, VBUS ORed into +5 V. RESET (SW1) and BOOT (SW2) buttons.
- **Status LED**: WS2812B on IO48; its VDD comes through an SS14 drop diode
  (≈4.6 V) so the 3.3 V data level stays inside the WS2812B's V_IH spec.
- **Alarm**: 12 mm active 5 V buzzer (BZ1) on IO7, AO3400A low-side driver
  with flyback diode.
- 4× M3 grounded mounting holes, one per corner, centers on a **90 × 70 mm
  rectangle** (5 mm in from the top/bottom edges) for easy enclosure
  drilling; GND pour both sides with stitching vias.

### GPIO map (mirrors `main/Kconfig.projbuild` defaults)

| GPIO | Function | | GPIO | Function |
|---|---|---|---|---|
| 11/13/12 | SPI MOSI/MISO/SCLK | | 4/5/6/2/1 | NAV up/down/left/right/select |
| 10 | MAX31855 CS | | 48 | WS2812B data |
| 8/9/46/3 | LCD CS/DC/RST/BL | | 7 | Alarm buzzer |
| 17 | SSR drive | | 14 / 21 | VENT / LID_SW (aux header) |
| 19/20 | USB D−/D+ | | 43/44 | UART0 TX/RX (aux header) |

## Bill of materials

| Ref | Value / Part | Package |
|---|---|---|
| U1 | ESP32-S3-WROOM-1-N16R8 | castellated module |
| U2 | AMS1117-3.3 | SOT-223 |
| U3 | MAX31855KASA+ | SOIC-8 |
| U4 | USBLC6-2SC6 | SOT-23-6 |
| Q1, Q2 | AO3400A N-MOSFET | SOT-23 |
| D1, D2 | SS34 Schottky 3 A | SMA (DO-214AC) |
| D3 | SS14 Schottky 1 A | SMA |
| D4 | 1N4148W | SOD-123 |
| LED1 | WS2812B | PLCC-4 5050 |
| LED2 / LED3 | green / amber LED | 0805 |
| R1, R2, R7, R8 | 10 kΩ | 0805 |
| R3 | 330 Ω | 0805 |
| R4, R5 | 5.1 kΩ | 0805 |
| R6, R11 | 100 Ω | 0805 |
| R9 | 1 kΩ | 0805 |
| R10 | 680 Ω | 0805 |
| C1 | 22 µF 25 V X5R | 1206 |
| C3 | 22 µF 10 V X5R | 1206 |
| C2, C4, C6, C8, C10 | 100 nF | 0805 |
| C5 | 1 µF | 0805 |
| C7, C12 | 10 µF | 0805 |
| C9 | 10 nF | 0805 |
| BZ1 | active buzzer 5 V | 12 mm THT, 7.6 mm pitch |
| J1 | USB-C 16-pin receptacle | HRO TYPE-C-31-M-12 |
| J2, J3, J4 | Phoenix MKDS 1,5/2 (or clone) | 5.08 mm screw terminal |
| J5, J7 | Molex KK-254 friction-lock header 1×8 (AE-6410-08A / 22-27-2081) | 2.54 mm THT |
| J6 | Molex KK-254 friction-lock header 1×6 (AE-6410-06A / 22-27-2061) | 2.54 mm THT |
| — mates | KK-254 housing 1×8 (22-01-3087) ×2, 1×6 (22-01-3067), crimps 08-50-0114 | — |
| SW1, SW2 | tactile switch | 6 mm THT |
| H1–H4 | M3 mounting hole, grounded, 90 × 70 mm grid | — |

## Fabrication & assembly at JLCPCB

The board was checked against JLCPCB's standard 2-layer capabilities and
sits comfortably inside the cheapest tier — there is nothing on it that
triggers an upcharge:

| Parameter | This board | JLCPCB 2-layer limit |
|---|---|---|
| Size | 100 × 80 mm | ≤ 100 × 100 mm for the promo price |
| Min track width | 0.25 mm (USB) | 0.127 mm |
| Min clearance | 0.20 mm | 0.127 mm |
| Via | 0.6 mm / 0.3 mm drill | 0.4 mm / 0.3 mm |
| Min PTH drill | 0.3 mm (vias) | 0.3 mm |
| Copper-to-edge | ≥ 0.4 mm | 0.2 mm |
| Layers / finish | 2, HASL, 1.6 mm, green | standard |

Bare boards: **~$2–4 for 5 pcs** (their locked 2-layer ≤100×100 mm price)
plus shipping. Ready-to-upload gerbers + drill files are in `gerbers/`.

**Assembly**: `generator/gen_jlc.py` writes `jlcpcb/BOM.csv` +
`jlcpcb/CPL.csv` for the PCBA upload. Every part is orderable from the
LCSC/JLCPCB catalog: the passives, AO3400A, SS34/SS14, 1N4148W and
AMS1117 are cheap **Basic** parts (no feeder-loading fee); the module
(ESP32-S3-WROOM-1-N16R8, C2913202 — matches the firmware's 16 MB flash +
octal PSRAM config), MAX31855KASA+T (C52028), USB-C (C165948) and WS2812B
are stocked **Extended** parts (~$3 loading fee each on standard assembly).
Generic commodity parts (screw terminals, KK-254 wafers, buzzer, tact
switches) have many in-stock equivalents — confirm the flagged part
numbers in JLC's BOM matcher at order time, and verify part rotations in
their placement preview.

Cheapest sensible configurations:
1. **SMT-only assembly** (recommended): let JLC place all SMD parts and
   hand-solder the 6 through-hole parts yourself (terminals, wafers,
   buzzer, switches — the easy ones). Roughly **$50–70 for 5 boards, 2
   assembled**, dominated by setup + loading fees + the ~$6–8/board BOM.
2. Full assembly incl. THT hand-soldering: add roughly $15–25.
3. Bare boards only: ~$2–4 + parts from LCSC (~$8/board) and a Saturday
   with an iron — everything was chosen to be hand-solderable.

## Regenerating the files

Everything derives from `generator/design.py` — a single table of
components, pin→net connectivity and placements — so schematic and board
can never disagree. Requires KiCad installed (pcbnew Python module +
kicad-cli + standard libraries; v7 and v10 are both supported — the build
script adapts). On macOS run the board build with KiCad's bundled Python:
`KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3`

```bash
cd hardware/kicad
python3 generator/gen_sch.py bisque-controller.kicad_sch        # schematic
python3 generator/check_netlist.py bisque-controller.kicad_sch  # KiCad netlist round-trip: must PASS
"$KPY" generator/kicad_build.py bisque-controller.kicad_pcb     # board via pcbnew API:
                                                                #   system-library footprints, octilinear
                                                                #   45-degree autoroute, GND stubs, zone fill,
                                                                #   pour-island healing, KiCad DRC report
python3 generator/check_pcb.py bisque-controller.kicad_pcb      # independent checker: ALL CHECKS PASS
python3 generator/render_pcb.py bisque-controller.kicad_pcb preview-board.svg
kicad-cli pcb export gerbers -o gerbers/ bisque-controller.kicad_pcb
kicad-cli sch export pdf -o pdf/bisque-controller-schematic.pdf bisque-controller.kicad_sch
```

(`gen_pcb.py` remains as a KiCad-free fallback generator that writes the
board file textually; `kicad_build.py` is the authoritative path.)

3D renders: `./generator/render-3d.sh` drives `kicad-cli pcb render`
(raytraced, official component models). `render_3d.py` remains as a
KiCad-free fallback (stylized three.js renders via headless chromium).

If pin assignments change in `main/Kconfig.projbuild`, update
`generator/design.py` to match and regenerate. (`generator/fp/` keeps a
snapshot of the KiCad 9 library footprints for the fallback generator;
`kicad_build.py` uses the installed system libraries instead.)

## Safety

This board switches an external SSR's **control input** only. All mains
wiring — SSR load side, kiln elements, breakers, enclosure grounding — is
external and must follow local electrical code. Fire kilns with appropriate
supervision and hardware over-temperature protection.
