# Bisque Kiln Controller — KiCad PCB

A single-board replacement for the perfboard build documented in
`docs/perfboard-layout.svg` / `docs/wiring-diagram.svg`. Designed for
**KiCad 9**, 2-layer, 100 × 80 mm, and **hand-solderable throughout**: the
smallest parts are 0805 passives, SOIC-8, SOT-23 and the ESP32-S3-WROOM-1
module's castellated pads. No BGA, no QFN, no bare chips.

| File | What it is |
|---|---|
| `bisque-controller.kicad_pro` | Project (net classes: 0.3 mm signal / 0.7 mm power, 0.2 mm clearance) |
| `bisque-controller.kicad_sch` | Schematic (A3, netlist-style: functional groups + global labels) |
| `bisque-controller.kicad_pcb` | Board: placed, fully routed, GND pours on both layers |
| `preview-board.svg` | Quick visual of placement + routing (generator output, not KiCad-rendered) |
| `3d/board-3d-*.png` | 3D renders (iso / front / top / underside) |
| `generator/` | Python scripts that generate both files from one connectivity table |

## Opening it

1. Open `bisque-controller.kicad_pro` in KiCad 9 (9.0.8 or newer).
2. In pcbnew press **B** to fill the GND zones (they ship unfilled).
3. Run DRC. The zones, thermal reliefs and the module's built-in antenna
   keep-out are all standard KiCad objects, so DRC is the authority.

Footprints and symbols are **embedded** in the files (taken from the official
KiCad 9.0.9.1 libraries), so nothing needs to be installed to open or
fabricate the board.

## What's on the board

- **U1 — ESP32-S3-WROOM-1-N8R2** module at the top edge, antenna keep-out
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
- 4× M3 grounded mounting holes; GND pour both sides with stitching vias.

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
| U1 | ESP32-S3-WROOM-1-N8R2 | castellated module |
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
| H1–H4 | M3 mounting hole, grounded | — |

## Regenerating the files

The schematic and board are both generated from
`generator/design.py` — a single table of components, pin→net connectivity
and placements — so they can never disagree with each other. The board is
routed by a small octilinear grid autorouter (`router.py` — 45-degree
routing with graded bend costs, plus a validated miter pass that chamfers
any remaining right-angle corners) and verified by an
independent geometry checker (`check_pcb.py`: clearance ≥ 0.2 mm,
per-net connectivity, antenna keep-out, board-edge margin, courtyards).

```bash
cd hardware/kicad
./generator/fetch-symbols.sh          # once: downloads KiCad symbol libs (~30 MB)
python3 generator/gen_sch.py bisque-controller.kicad_sch
python3 generator/gen_pcb.py bisque-controller.kicad_pcb
python3 generator/check_pcb.py bisque-controller.kicad_pcb   # must say ALL CHECKS PASS
python3 generator/render_pcb.py bisque-controller.kicad_pcb preview-board.svg
```

For 3D renders (`3d/`): `render_3d.py` parses the board file into a scene —
board slab with real drilled holes, copper, and stylized per-package bodies —
and renders it via three.js in headless chromium (software WebGL):

```bash
./generator/fetch-three.sh            # once: three.min.js from the npm registry
python3 generator/render_3d.py bisque-controller.kicad_pcb 3d
```

(For photorealistic renders, KiCad's own 3D viewer with the official
component models is still the reference — these are quick previews.)

Footprints (`generator/fp/*.kicad_mod`, from kicad-footprints 9.0.9.1) are
committed; symbol libraries are fetched on demand. Generation is
deterministic (UUIDv5), so regenerating without changes produces identical
files. If pin assignments change in `main/Kconfig.projbuild`, update
`generator/design.py` to match and regenerate.

## Safety

This board switches an external SSR's **control input** only. All mains
wiring — SSR load side, kiln elements, breakers, enclosure grounding — is
external and must follow local electrical code. Fire kilns with appropriate
supervision and hardware over-temperature protection.
