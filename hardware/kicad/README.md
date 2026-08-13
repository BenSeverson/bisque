# Bisque Kiln Controller — KiCad PCB

A single-board replacement for the perfboard build documented in
`docs/perfboard-layout.svg` / `docs/wiring-diagram.svg`. This is **rev B**, a
respin of the original prototype rather than a variant — it replaces the
thermocouple front-end with an incompatible part, adds a second SSR zone and
a digital current-sense chip, moves most GPIOs, and swaps the module variant.
4-layer, 100 × 100 mm, built for **JLCPCB assembly**: 0805 passives,
QFN/TSSOP/SOIC/SOT ICs, SMD tact switches and the ESP32-S3-WROOM-1U module's
castellated pads all go down the SMT line, plus thirteen through-hole parts
(terminals, wafers, buzzer) fitted by hand — see "Fabrication & assembly"
below for why that split is much cheaper than it looks. The design record for
this respin, including the routing escalation that forced the layer count,
is `docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md`; the
fab-readiness sign-off is `FAB-READINESS-REVIEW-REVB.md` (rev A's review,
`FAB-READINESS-REVIEW.md`, documents a board that no longer exists and is
kept only as history — do not read it as current).

Built and validated with **real KiCad** (10.0.5, pcbnew Python API +
kicad-cli): footprints come from KiCad's installed libraries, ground/power
plane pours are filled and checked by `kicad-cli pcb drc --refill-zones` —
**zero errors, zero unconnected, zero warnings**
(`bisque-controller-drc.rpt`) — and the schematic passes a netlist round-trip
check (KiCad's exported netlist diffed against the design's connectivity
table — 93 nets, 0 mismatches). The 3D renders in `3d/` are raytraced by
`kicad-cli pcb render` with the official component models.

| File | What it is |
|---|---|
| `bisque-controller.kicad_pro` | Project (net classes: 0.3 mm signal / 0.7–0.8 mm power, 0.25 mm only on the short fine-pitch escape stubs off the QFN/TSSOP pads) |
| `bisque-controller.kicad_sch` | Schematic (A1, netlist-style: functional groups, global labels for signals, real power ports for rails). Laid out programmatically by `generator/gen_sch.py` — a `GROUPS` taxonomy plus a deterministic column packer, with a reserved right-hand column for the notes block. A1, not A3: an A3 declaration silently clipped ~40% of the circuit out of the exported PDF while every connectivity checker stayed green (`generator/check_sch_bounds.py` now fails on any off-sheet item), and containment is not readability, so `generator/check_sch_layout.py` additionally fails on any symbol/symbol, text/symbol or text/text overlap |
| `bisque-controller.kicad_pcb` | Board: placed, fully routed, 4 layers (F.Cu/B.Cu signals, In1.Cu GND plane, In2.Cu +3V3 plane) |
| `preview-board.svg` | Quick visual of placement + routing |
| `3d/board-3d-*.png` | Raytraced renders, kicad-cli (iso / front / top / underside) |
| `bisque-controller-drc.rpt` | KiCad DRC report (0 errors, 0 unconnected, 0 warnings — the 109 silkscreen warnings went with the silk packer, see "Regenerating the files") |
| `gerbers/` | Fabrication outputs (kicad-cli: F.Cu, B.Cu, **In1.Cu, In2.Cu**, paste/silk/mask, Edge.Cuts, Excellon drill + job file) |
| `pdf/` | Schematic and board PDFs (kicad-cli) |
| `jlcpcb/` | Assembly BOM + CPL for JLCPCB, plus the hand-solder shopping list |
| `generator/` | Scripts that build everything from one connectivity table |

## Opening it

Open `bisque-controller.kicad_pro` in KiCad 10 or newer (the board file
format and pcbnew API this generator uses require it — see "Regenerating the
files"). Zones ship **filled** (KiCad's own filler) and the board already
passes KiCad DRC; re-run it after any edit. The schematic embeds its
symbols; the board references the standard KiCad footprint libraries (and
was generated from them).

## What's on the board

- **U1 — ESP32-S3-WROOM-1U-N16R2** module (16 MB flash / 2 MB **quad**
  PSRAM — matches `sdkconfig.defaults`' `CONFIG_SPIRAM_MODE_QUAD` + the
  16 MB OTA partition table), at the top edge. The **1U** variant carries a
  **U.FL connector for an external antenna** rather than the standard
  WROOM-1's on-package PCB antenna: a kiln controller mounts on or near a
  large grounded steel enclosure, which makes a PCB antenna close to
  non-functional, and the 1U's antenna can be placed on a pigtail somewhere
  that actually radiates. It also reclaims the ~330 mm² antenna keep-out
  band the WROOM-1 footprint would require — freed for parts and ground
  pour on a board that turned out to need every square millimeter (see
  "Density and the 4-layer stack-up" below). **The U.FL pigtail (U.FL → SMA
  bulkhead) and the 2.4 GHz antenna are accessories, not BOM lines** — buy
  them separately (see the hand-solder/shopping-list note below) and drill
  an SMA bulkhead hole in the enclosure. U.FL is rated for ~30 mating
  cycles, so treat the connection as assemble-once, not a field-serviceable
  connector.

  **Certification caveat.** Espressif's modular certification for the
  WROOM-1U is granted against specific antenna types and gains. Fitting a
  non-approved (e.g. high-gain) antenna steps outside that approval — see
  `CERT-001` in `FAB-READINESS-REVIEW-REVB.md`. Use an antenna within the
  certified list unless you're prepared to re-certify.

- **Power**: 5 V DC in on screw terminal **J2** (top-left) *or* USB-C; each
  source feeds the +5 V rail through an SS34 Schottky (D1/D2 — also reverse
  polarity protection), then an **AMS1117-3.3** (U2, SOT-223) makes 3V3.
  Power LED (green) on 3V3. The display (below) draws from +5V directly, not
  through U2 — its backlight and panel logic were the dominant unmodeled load
  on the LDO, and moving them off keeps U2's junction temperature comfortably
  under its 125°C limit even at a hot enclosure ambient. The +3V3 rail also
  now lives on its own **inner plane** (In2.Cu) rather than a surface pour —
  see the stack-up note below.
- **Thermocouples ×2**: **MAX31856MUD+** (U3 channel 1 / U5 channel 2,
  TSSOP-14), K-type on screw terminals **J3** (channel 1) / **J8** (channel
  2), each with its datasheet-specified differential + common-mode input
  filter, sharing the SPI bus (MISO + its own CS: GPIO 10 / GPIO 35). This
  replaces rev A's single MAX31855KASA+ entirely — the two parts are not
  pin-compatible, and no attempt was made to support both on one board.

  **Ungrounded-junction thermocouple probes are required.** Both MAX31856s
  reference their T− input to board ground. Two grounded-junction probes
  sharing one kiln chamber would form a ground loop through the kiln body
  itself; use ungrounded-junction (isolated-tip) K-type probes on both
  channels. This is a documentation obligation, not something the board
  enforces electrically.
- **SSR drive ×2, direct low-side MOSFET**: screw terminals **J4** (zone 1) /
  **J9** (zone 2), each **pin 1 = `SSR_EN`** (board +5 V, gated by the
  hardware watchdog — see below) and **pin 2 = the switched low side**
  (`SSR1_OUT` / `SSR2_OUT`). Per channel: GPIO → 100 Ω series resistor → gate
  of an AO3400A (**Q5** zone 1, **Q6** zone 2), source to GND, drain on the
  terminal, with a **10 kΩ gate pulldown** (R7/R20) holding the FET off
  through boot and reset and an amber indicator LED + 680 Ω across the
  terminal pair, so the LED shows real drive state. The board supplies the
  SSR control loop. (The SSRs themselves and all mains wiring stay outside
  this board.)

  **This is rev A's topology, restored.** Rev B opto-isolated both channels
  with an LTV-817S each (`U8`/`U9`), floating `J4`/`J9` as dry contacts,
  carving a four-layer pour keepout across the opto row, adding `SJ3`/`SJ4`
  to optionally tie each opto collector to board +5 V, and checking the
  barrier with `check_isolation.py`. That was **reversed** before fab: an
  optocoupler only isolates if the SSR control loop is powered from a supply
  that is *not this board*, and this board's is. Close the loop through board
  `+5V` and board `GND` — exactly what `SJ3`/`SJ4` existed to permit — and
  both sides of the "barrier" are one SELV domain, leaving a sacrificial part
  in series with the SSR input. The as-built terminals could not have closed
  an isolated loop anyway: neither carried a `GND` pin. So the optos, the
  jumpers, the pour and router keepouts and `check_isolation.py` are all gone,
  and the freed area went back to pour and routing. Do not re-add
  opto-isolation without also specifying an off-board control supply and a
  terminal that carries it.

  **Hardware watchdog (`SJ2`, "WDT DEFEAT").** `SSR_EN` — the +5 V rail
  feeding *both* SSR terminals and both indicator LEDs — is supplied by Q4, a
  P-channel high-side MOSFET (AO3401A) whose gate node `SSR_PG` is held down
  by Q3, itself held on by a diode charge pump (BAT54S, C38/C39, R46) driven
  from GPIO 36 (`WDT_KICK`); R47 (100 kΩ) pulls `SSR_PG` up as the fail-safe.
  The watchdog moved to the supply side when the optocouplers were reverted:
  the two-parts-cheaper stacked-low-side alternative would have left the
  channel MOSFET only 140 mV of Vgs margin to the AO3400A's lowest guaranteed
  `R_DS(on)` point before subtracting Q3's own (datasheet-unbounded) drop.
  Going high-side cuts Q3's load from ~30 mA to 50 µA and puts both switching
  FETs past a guaranteed spec point — see the arithmetic in
  `generator/design.py`'s watchdog block. **Nothing in firmware toggles this pin yet.** A
  charge pump needs transitions to stay charged — a stuck-high pin decays
  exactly like a stopped one — so on power-up, and on any board where
  nothing kicks GPIO 36, `SSR_EN` collapses and **both SSR channels stay off
  regardless of what the firmware commands them to do.** The silkscreened
  `SJ2` solder jumper shorts `SSR_PG` to GND, holding Q4 on and restoring
  un-gated behaviour
  for bring-up and for any build without the firmware kick task. **A board
  with neither `SJ2` fitted nor a firmware kick task will not heat** — this
  is the single most likely rev B bring-up surprise, more likely to be
  mistaken for a bad SSR or a lid-interlock problem than correctly
  diagnosed as "nobody is kicking the dog yet." The watchdog gates only the
  two SSR channels; vent, purge, the spare aux channel and the buzzer are
  unaffected, so a stalled controller can still open its vent.
- **Display**: 14-pin Molex KK-254 friction-lock header **J5** for a 4.0"
  ST7796S SPI module (LCDWIKI MSP4021, 480×320, resistive touch) — grown
  from rev A's 8-pin display-only header to carry the panel's full pin set:
  the original 8 signal pins, the panel's `SDO` (pin 9, left unwired in rev
  A because the firmware never read from the display), and the five touch
  lines (pins 10–14). `T_CLK`/`T_DIN`/`T_DO` are electrically the shared
  SPI2 bus through 33 Ω series damping resistors (R39/R41/R42 — the bus now
  multi-drops the LCD at 40 MHz plus two MAX31856s and the touch controller
  at lower clocks); only `T_CS` (GPIO 5) and `T_IRQ` (GPIO 6) cost new
  dedicated GPIOs. The XPT2046 touch controller itself lives on the display
  module, not this PCB. VCC runs from +5V rather than +3V3, per the
  module's own manual and reference wiring diagrams, with no level shifter
  needed on CS/RESET/DC/MOSI/SCK.
- **Nav switch**: 6-pin KK-254 friction-lock header **J6** for the
  panel-mounted 5-way switch (`UP DN LT RT OK GND`, active-low, ESP32
  internal pull-ups) — now on GPIO 38–42, contiguous module pads, moved
  from the split GPIO 1/2/4/5/6 rev A used (routing simplification, see the
  hardware-design spec §3.1).
- **Aux header J7** (8-pin KK-254): `3V3 GND TX RX SDA SCL 3V3 GND` — UART0
  plus a 0.1" I2C tap (pins 5–8), alongside the Qwiic/STEMMA-QT connector
  **J14**. Rev A's `VENT`/`LID_SW`/`AUX_A`/`AUX_B` nets are gone from this
  header entirely: nothing on the board ever sourced `AUX_A`/`AUX_B` here
  (the real aux outputs are on J10, below), and the lid switch has its own
  terminal (J11).
- **Aux output bank — J10** (4-pin terminal): **AUX_VP** (external coil
  rail) plus three switched low sides (`AUX1_OUT` = vent, `AUX2_OUT`,
  `AUX3_OUT`), driven by a shared **ULN2003ADR** Darlington array (U6) with
  integrated freewheel diodes returning to `AUX_VP` — not the board's own
  +5V rail. A gas purge solenoid is realistically 12 V or 24 V DC; the
  ULN2003 is rated 50 V / 500 mA per channel, so `AUX_VP` is meant to be fed
  from an external coil supply. Solder jumper **`SJ1`** (open by default)
  ties `AUX_VP` to board +5V for anyone who only has plain 5V relays. Only
  channel 1 (vent) is driven by firmware today (`safety_update_vent()`);
  channels 2/3 are routed and declared in Kconfig (`KILN_PIN_AUX2`/`AUX3`)
  but undriven.
- **Protected inputs — J11** (4-pin terminal): `IN1`/`IN2`/`IN3` (lid, gas
  flow, spare) plus GND, each with the same conditioning rev A used for its
  single lid input — 1 kΩ series, 10 kΩ pull-up to 3V3, 100 nF to ground,
  dry-contact to GND — generalized to three channels. `IN1` (GPIO 4) is the
  lid switch and defaults to enabled, matching this board; see
  `docs/pin-assignments.md` §1 for the fail-safe wiring requirement if no
  switch is fitted. `IN2` (gas flow) and `IN3` (spare) are routed but have
  no firmware consumer yet.
- **CT current sensing — J12** (4-pin terminal, `CTA_P`/`CTA_N`/`CTB_P`/
  `CTB_N`): two current-transformer inputs into an **ADE7953** energy
  metering IC (U7, LFCSP-28, current-only — the voltage channel is unused),
  on the I2C bus with its own 3.579545 MHz crystal (Y1). Burden resistors
  (R31/R34, 6.8 Ω), anti-alias RC and an SRV05-4 TVS array (D5/D6) per
  channel protect the externally-exposed CT leads. One channel per SSR
  zone, so each element bank gets an independent current reading; with no
  mains voltage sensing on this board, power is estimated as
  `Irms × configured nominal mains voltage` (±3–5%), adequate for
  element-health diagnosis and cost estimation. The voltage-channel pins
  are routed to a **DNP** 2-pin SELV header (**J13**) for a possible future
  off-board isolated-AC accessory — not fitted, no mains anywhere on this
  PCB.
- **I2C expansion — J7 pins 5–8 and J14 (Qwiic/STEMMA-QT)**: `I2C_SDA`
  (GPIO 18) / `I2C_SCL` (GPIO 47), on-board pull-ups (R44/R45, 4.7 kΩ).
  Carries the on-board ADE7953 today; open for an RTC breakout, an SHT4x RH
  sensor, or an external ADC without board changes. No I2C driver exists in
  firmware yet.
- **USB-C (J1)** for native-USB flashing: 5.1 kΩ CC resistors, USBLC6-2SC6
  (U4) ESD protection, VBUS ORed into +5 V. RESET (SW1) and BOOT (SW2)
  buttons.
- **Status LED**: WS2812B on IO48; its VDD comes through an SS14 drop diode
  (≈4.6 V) so the 3.3 V data level stays inside the WS2812B's V_IH spec.
- **Alarm**: 12 mm active 5 V buzzer (BZ1) on IO7, its own discrete AO3400A
  (Q2) low-side driver with flyback diode — kept separate from the ULN2003
  aux bank on purpose, so a 5 V buzzer and a 24 V solenoid never share a
  COM rail.
- **Test points**: twelve 1 mm bring-up pads (TP1–TP12, no BOM/assembly
  cost) on +3V3, +5V, GND, the SPI bus, I2C SDA/SCL, both SSR gate nets,
  the CT burden node, and the watchdog hold node. Rev A shipped with none,
  which its fab review flagged as awkward for bring-up; at ~141 components
  and eleven subsystems, they stopped being optional.
- 4× M3 grounded mounting holes, one per corner, centers on a **90 × 90 mm
  rectangle** (5 mm in from each edge, grown from rev A's 90 × 70 mm as the
  board grew from 100 × 80 mm to 100 × 100 mm) for easy enclosure drilling.

### Density and the 4-layer stack-up

Rev B roughly triples rev A's component count (52 → 141) on the same
100 × 100 mm footprint rev A used at 80 mm tall. `generator/router.py`'s
2-layer octilinear grid autorouter could not close the board: a rung-by-rung
escalation (0805 → 0603 passives, then a 125 × 100 mm board) knocked
unroutable nets down from 34 to 23 to 9, but the survivors were short local
nets boxed in by neighbours' copper in the SSR driver cluster and the
ADE7953 block — the signature of a **layer** shortage, not an area shortage.
Going 4-layer (an unbroken GND plane on In1.Cu, a +3V3 plane on In2.Cu — In2
carries +3V3 alone rather than splitting with +5V, since +5V's own consumers
don't fall into a separable region) closed the board at 0 unrouted nets and
0 DRC errors, and then gave back **every** concession the 2-layer attempts
had made: the board walked back to 100 × 100 mm, 0805 passives, and rev A's
0.3 mm signal / 0.7 mm power net classes. Neither outer layer is poured —
on this density, the GND pour was the largest single consumer of routing
space on exactly the two layers the boxed-in nets needed to escape through.
Track widths came back too, because the router no longer touches fine-pitch
pads directly: each is represented by the far end of a pre-drawn escape
stub, so 0.25 mm tracks are confined to the ~2 mm around the QFN-28/TSSOP
pads that actually need them. See `FAB-READINESS-REVIEW-REVB.md` and
`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md` §6.3 for
the full measured escalation ladder.

Both planes run whole: there are **no rule areas** on this board. Rev B
carved a four-layer pour keepout across the SSR optocoupler row and had
`generator/check_isolation.py` confirm nothing landed in it; both went with
the optocouplers (see "SSR drive ×2" above), returning ~21 × 24 mm of pour
and routing area on every layer.

### GPIO map (mirrors `main/Kconfig.projbuild` defaults)

| GPIO | Function | | GPIO | Function |
|---|---|---|---|---|
| 11/13/12 | SPI MOSI/MISO/SCLK | | 38/39/40/41/42 | NAV up/down/left/right/select |
| 10 / 35 | TC1 / TC2 CS (MAX31856) | | 48 | WS2812B data |
| 8/9/46/3 | LCD CS/DC/RST/BL | | 7 | Alarm buzzer |
| 17 / 21 | SSR1 / SSR2 MOSFET gate | | 14/15/16 | AUX1 (vent) / AUX2 / AUX3 (ULN2003, J10) |
| 19/20 | USB D−/D+ | | 43/44 | UART0 TX/RX (J7) |
| 4/2/1 | Protected inputs IN1 (lid) / IN2 (gas flow) / IN3 (spare), J11 | | 18/47 | I2C SDA/SCL |
| 5/6 | Touch T_CS / T_IRQ | | 36 | Watchdog kick (`SJ2` defeats it) |
| 37 | spare | | | |

Full table with module pin numbers, nets and per-pin notes:
[`docs/pin-assignments.md`](../../docs/pin-assignments.md) §1.

## Bill of materials

141 components, 93 nets. Full machine-readable BOM: `jlcpcb/BOM.csv` (40
lines covering 109 machine-placed parts) plus `jlcpcb/hand-solder-parts.csv`
(13 hand-fitted parts). Selected parts worth calling out:

| Ref | Value / Part | Package |
|---|---|---|
| U1 | ESP32-S3-WROOM-1U-N16R2 | castellated module, U.FL |
| U2 | AMS1117-3.3 | SOT-223 |
| U3, U5 | MAX31856MUD+T | TSSOP-14 |
| U4 | USBLC6-2SC6 | SOT-23-6 |
| U6 | ULN2003ADR | SOIC-16 |
| U7 | ADE7953ACPZ-RL | LFCSP-28 (QFN-28, 5×5 mm) |
| Y1 | 3.579545 MHz crystal | HC-49S-SMD |
| D5, D6 | SRV05-4 TVS array | SOT-23-6 |
| D7 | BAT54S dual series Schottky | SOT-23 |
| Q2, Q3, Q5, Q6 | AO3400A N-MOSFET | SOT-23 |
| Q4 | AO3401A P-MOSFET (watchdog high-side switch) | SOT-23 |
| J1 | USB-C 16-pin receptacle | HRO TYPE-C-31-M-12 |
| J2, J3, J4, J8, J9 | Phoenix MKDS 1,5/2 (or clone) | 5.08 mm screw terminal, 2-pos |
| J10, J11, J12 | Phoenix MKDS 1,5/4 (or clone) | 5.08 mm screw terminal, 4-pos |
| J5 | Molex KK-254 friction-lock header 1×14 | 2.54 mm THT |
| J6 | Molex KK-254 friction-lock header 1×6 | 2.54 mm THT |
| J7 | Molex KK-254 friction-lock header 1×8 | 2.54 mm THT |
| J13 | 2-pin header, **DNP** (AC-sense SELV, not fitted) | 2.54 mm THT |
| J14 | JST SH SM04B-SRSS-TB | Qwiic/STEMMA-QT, 1 mm SMD, **side entry** — pinned to the bottom edge so the cavity faces off-board |
| BZ1 | active buzzer 5 V | 12 mm THT, 7.6 mm pitch |
| SW1, SW2 | XKB TS-1187A tactile switch | 5.1 × 5.1 mm SMD |
| H1–H4 | M3 mounting hole, grounded, 90 × 90 mm grid | — |
| SJ1, SJ2 | Open solder jumpers (`AUX_VP←+5V`, `WDT DEFEAT`) | populated with solder, not a part |
| TP1–TP12 | 1 mm bring-up test pads | bare copper, no BOM cost |

**Off-BOM accessories (not in `jlcpcb/`, buy separately):** a U.FL → SMA
bulkhead pigtail and a 2.4 GHz antenna for U1 (~$3–5), plus an enclosure
SMA bulkhead hole. See the certification caveat above before choosing a
non-stock antenna.

## Fabrication & assembly at JLCPCB

The board needs JLCPCB's **4-layer** capability (rev A's 2-layer board did
not; see "Density and the 4-layer stack-up" above) but stays inside the
≤100 × 100 mm promo size tier either way:

| Parameter | This board | JLCPCB 4-layer limit |
|---|---|---|
| Size | 100 × 100 mm | ≤ 100 × 100 mm for the promo price |
| Min track width | 0.25 mm (fine-pitch escape stubs only) | 0.127 mm |
| Min clearance | 0.20 mm | 0.127 mm |
| Via | 0.6 mm / 0.3 mm drill | 0.4 mm / 0.3 mm |
| Min PTH drill | 0.3 mm (vias) | 0.3 mm |
| Copper-to-edge | ≥ 0.3 mm | 0.2 mm |
| Layers / finish | 4 (F.Cu/In1.Cu GND/In2.Cu +3V3/B.Cu), HASL, 1.6 mm, green | standard |

Bare boards: roughly **$10–15 for 5 pcs** at the 4-layer ≤100×100 mm tier
(up from rev A's ~$2–4 2-layer price) plus shipping. Ready-to-upload
gerbers + drill files, including the two inner-layer files, are in
`gerbers/`.

**Assembly**: `generator/gen_jlc.py` writes `jlcpcb/BOM.csv` +
`jlcpcb/CPL.csv` for the PCBA upload, and `jlcpcb/hand-solder-parts.csv` for
the parts you fit yourself. Every part carries an LCSC part number verified
against the catalog (package, value, stock) — there are no blanks and nothing
to guess at in JLC's BOM matcher.

**The board is deliberately split between the SMT line and a soldering
iron**, same strategy as rev A: each unique **Extended** part costs a flat
$3 feeder-loading fee no matter how many boards you build, and a single
through-hole part forces the whole order onto **Standard** assembly
(Economic is SMD, top-side only) with a per-joint charge on top.

`HAND_SOLDER` in `gen_jlc.py` drops thirteen designators from both the BOM
and the CPL — they must leave together, since JLCPCB's upload rejects a CPL
carrying designators the BOM does not have:

| Hand-fitted | Why |
|---|---|
| J2, J3, J4, J8, J9 (2-pos screw terminals), J10, J11, J12 (4-pos screw terminals), J5, J6, J7 (KK-254 wafers), BZ1 (buzzer) | 5.08 mm and 2.54 mm pitch — the easiest joints on the board, but the ones that would force Standard assembly |
| LED1 (WS2812B, PLCC-4 5050) | No addressable RGB LED at LCSC is a Basic part (checked across WS2812/SK6812/XL-xxxx), so its $3 buys nothing an iron can't do to four edge-accessible pads |

What's left goes down the SMT line: **98 Basic parts** (passives, LEDs,
AO3400A, AO3401A, SS34/SS14, 1N4148W, AMS1117, both tact switches, the
ULN2003 and the SRV05-4 TVS arrays are all Basic) at no feeder fee,
and **11 Extended parts** — the module (ESP32-S3-WROOM-1U-N16R2, C3013945),
both MAX31856MUD+T (C2653162, one designator, two placements), the ADE7953
(C515890), its crystal (C7471632), the BAT54S watchdog diode (C7420333),
the SRV05-4 TVS array's specific LCSC line (C558418), the 6.8 Ω CT burden
resistor (C17774), the 30 pF crystal load caps (C107114), USBLC6-2SC6
(C7519), the Qwiic connector (C160404) and the USB-C receptacle (C165948) —
**$33 in feeder fees**, up from rev A's 4 unique Extended parts / $12. Three
new subsystems (ULN2003, SRV05-4, watchdog) landed at **zero** feeder cost
by being Basic parts, so the increase is almost entirely the analog/sensing
front end.

**Sourcing flag:** LCSC `C17774` (the 6.8 Ω CT burden resistor, R31/R34) was
down to roughly 970 units in stock as of the last check, with no Basic-part
alternative at that value/package. Re-check stock immediately before
ordering — see `FAB-READINESS-REVIEW-REVB.md`.

SW1/SW2 are **SMD** tact switches (XKB TS-1187A, C318884), not a
through-hole part — a Basic part, so it costs no feeder fee *and* stays
machine-placed.

`hand-solder-parts.csv` carries a **Mouser second source** where one exists,
so the shopping list works against either supplier:

| Ref | LCSC | Mouser alternate |
|---|---|---|
| J5 | C17701004 | none — KK-254 1×14 friction-lock wafer; source from LCSC |
| J6 | C239381 | Molex **22-27-2061** — genuine KK-254 1×06 (LCSC line is an A2547WV clone) |
| J7 | C240822 | Molex **22-27-2081** — identical, the LCSC line is already genuine Molex |
| J2, J3, J4, J8, J9 | C8465 | Phoenix Contact **1715721** (MKDS 1,5/2-5,08) — the part this footprint is named for |
| J10, J11, J12 | C42377749 | none — WJ500V-5.08-04P 4-pos screw terminal; source from LCSC |
| BZ1 | C96093 | Same Sky **CMI-1295-0585T** — Ø12 × 9.5 mm, 7.6 mm pitch, 5 V THT active |
| LED1 | C2761795 | **none** — no bare Worldsemi 5050 in Mouser's catalog; use LCSC, DigiKey, Adafruit or SparkFun |

Several of these LCSC lines are Chinese generics and the Mouser column is the
genuine part each footprint was drawn from where one exists, so it fits at
least as well — clone dimensional tolerance being the usual source of
trouble. It costs several times more, though: a real Phoenix MKDS is
dollars against cents for the WJ500V clone. The alternates were verified by
MPN and datasheet, not by live API (no Mouser API key, and Mouser blocks
automated page fetches) — confirm stock at order time.

**Assembly stays Economic**: with 0 through-hole parts left in the assembly
BOM (`gen_jlc.py`'s own output confirms this every run), the whole
machine-placed set qualifies for Economic (SMD, top-side only) rather than
Standard, same as rev A.

The CPL applies JLCPCB's per-package rotation corrections (see
`JLC_ROTATION` in `gen_jlc.py`) rather than leaving them to be caught in the
order preview — currently U2, U3, U4, U5, U6, U7, D5, D6, D7, Q2, Q3 (eleven
corrections, up from rev A's five, driven by the new TSSOP/QFN/SOIC parts).
**The WROOM-1U's CPL rotation and origin were re-checked against JLCPCB's
placement preview rather than assumed to carry over from the WROOM-1** — the
two footprints share pad geometry but the 1U's origin sits 3.15 mm off the
WROOM-1's relative to the same pads, since the 1U body is 6.3 mm shorter and
KiCad footprint origins are body-centered. A module placed 3.15 mm off is a
dead board, so this is worth re-verifying in JLCPCB's own preview at order
time regardless of what's committed here. Still worth a glance at the
preview for the polarized two-terminal parts too, since a flip there is
cheap to spot and expensive to miss.

**Detailed per-unit cost breakdown and process-edge clearance analysis are
not reproduced here for rev B.** Rev A's README carried a line-item
Economic-PCBA cost table and a table of exact clearances from J1/board edge
that no longer apply now that the board is 100 × 100 mm at 4 layers with a
different part census and placement. J1 (USB-C) is still at the board edge
by necessity, and J14 (Qwiic) now sits on the bottom edge for the same
reason, so JLCPCB's SMT process-edge requirement likely still applies
in some form — get an exact quote (and re-check whether process rails are
needed) from JLCPCB's own order preview rather than trusting stale numbers
here.

## Regenerating the files

Everything derives from `generator/design.py` — a single table of
components, pin→net connectivity and placements — so schematic and board
can never disagree. Requires **KiCad 10+** (pcbnew Python module +
kicad-cli + standard libraries) — the project's `.devcontainer/` (see
`docs/devcontainer.md`) bakes this in, as an alternative to installing
KiCad natively. The Makefile finds KiCad's Python itself: it tries `python3`
first (which is where the devcontainer has `pcbnew`), then the macOS
`KiCad.app` bundle, and takes the first interpreter that can `import pcbnew`.
Set `KPY=/path/to/python3` to override it; if none is found the error names
every path it tried.

The top-level `Makefile` wraps the common cases — `make pcb` regenerates
everything and re-runs every checker; `make pcb-check` runs just the
checkers against what's already committed, without touching KiCad:

```bash
make pcb          # regenerate schematic + board + fab outputs, then check
make pcb-build    # schematic + board only (no fab outputs) — the full path, ~158 s
make pcb-cosmetic # silk / 3D models / title block only, reusing the routing — ~8 s
make pcb-fab      # gerbers, drill, BOM/CPL, PDFs, preview SVG — after pcb-build
make pcb-check    # check only: pinmap, sheet bounds, netlist, connectivity, silkscreen, reproducibility
make pcb-render   # 3d/board-3d-*.png raytrace — SLOW, deliberately not in `make pcb`
make pcb-cosmetic-verify   # prove pcb-cosmetic == pcb-build, byte for byte — SLOW
```

`make pcb` = `pcb-build` + `pcb-fab` + `pcb-check`, in that order, so a
board change and everything derived from it move together. The 3D raytrace
is the one thing split out: it takes minutes, nothing in a fab order reads
`3d/`, and it is regenerated by hand when the board's appearance changes.
It used to be worse than a split — `make pcb` ran *no* export step at all,
so it could succeed while leaving the committed gerbers, BOM, CPL and PDFs
describing the previous board.

### Which path does your change need?

Routing 93 nets across 141 parts is essentially all of `pcb-build`'s
runtime, and several kinds of change cannot move a single track. Those get
`make pcb-cosmetic`, which is `kicad_build.py --no-route`: it reads the
tracks, vias and filled zones back off the existing board and re-derives
everything else with the same code the full build runs.

| Change | Path | Measured |
|---|---|---|
| Silkscreen placement (`generator/silk.py`, the `SILK` table, reference text size/thickness) | `make pcb-cosmetic` | **8 s** |
| 3D model offsets (`MODEL_OFFSET` in `kicad_build.py`) | `make pcb-cosmetic` | **8 s** |
| Board title block | `make pcb-cosmetic` | **8 s** |
| **Anything else** — placement, connectivity, footprint choice, net classes, `MANUAL_VIAS`, router parameters (`router.py`, `gen_pcb.py`) | `make pcb-build` | **158 s** |

Both numbers used to be far worse — 421 s and 104 s — and the fast one was
not dominated by anything the fast path exists to skip. It was the
silkscreen placer, which is the *only* substantial work `--no-route` still
does, running a linear scan over all 492 pads and every other label for each
of ~200,000 candidate placements, and re-entering SWIG 171 million times to
re-answer `pcbnew.FromMM(0.05)`. Indexing those obstacles into a bucket grid
(the one `router.py` already uses for copper) and hoisting the clearance
constants took the placer from 95.2 s to 3.8 s. The placed silk is
byte-identical, which is the only acceptable outcome for a lookup
optimisation; `make pcb-cosmetic-verify` checks it against a full rebuild.

The full path was 318 s until the same lesson was applied to `router.py`.
Profiling it found the cost in the same place and not where the code
structure suggests: A* node expansion was 20% of the run, and 71% went into
`_clear_of`, which answered "is this cell clear?" by calling the exact
point-to-shape `dist()` on every obstacle within 3 mm — 381 million times.
Three changes, all of them lookup, none of them routing:

- Each `Shape`/`Seg` caches its bounding box, and `_clear_of` rejects on four
  float compares before calling `dist()`. An obstacle further than `need`
  from the box in x or y is further than `need`, full stop, so this cannot
  change an answer. It removes 79% of the `Seg.dist()` calls and 98% of the
  `Shape.dist()` ones.
- `_near()` returns a cached flat list of the 3×3 bucket block rather than
  being a generator over nine dict lookups, which was costing 833 million
  frame resumptions.
- `via_ok()` made three separate passes over the neighbourhood — copper
  clearance, via-in-pad, hole-to-hole — and ANDed them. They are now
  interleaved into one walk. It is asked at nearly every node A* pops
  (4.3 million times a build) and its memo barely hits, because a node is
  popped once.

Routing went 310 s → 144 s and the board is byte-identical, which is again
the only acceptable outcome. **`GRID` was measured, not left alone on
faith**: at 0.4 mm 14 nets fail to route and at 0.3 mm five do, in both
cases on the ADE7953 and the two MAX31856s — the fanout and plane-via stubs
snap their ends to `GRID`, so a coarser grid walks the escape off the pad
centreline exactly as the note beside `GRID` says. 0.3 mm is also *slower*
than 0.25 mm (463 s), because a net that cannot be routed exhausts the whole
grid before it says so, several times per pass.

When in doubt, use the full path. `--no-route` is not a judgement call it
leaves to you: before it reuses anything it compares the loaded board
against `design.py` — every reference, footprint, placement, orientation,
pad→net assignment, the net set, and every `MANUAL_VIAS` entry — and exits
naming the mismatches rather than emitting a plausible-but-wrong board.
What it cannot see is a change to the router's own parameters, since those
leave no trace on the board; that one is on you.

**`--no-route` output is byte-identical to a full rebuild**, and that is
tested rather than asserted. `make pcb-cosmetic-verify`
(`generator/check_fast_path.py`) does a full rebuild in a scratch
directory, then runs `--no-route` twice over copies of it — once as-is, and
once over a copy whose cosmetics have all been deliberately wrecked (every
designator moved and resized, every board text moved, the title block
overwritten, U1's 3D model flung off the board) — and requires all three
files to match to the byte. The vandalised run is the one that matters: it
shows the loaded board's cosmetic state cannot leak into the result, which
is why `--no-route` deletes and re-adds every footprint and board graphic
instead of editing them back to a default. A silk placer re-run over its
own previous output is not solving the problem a fresh build hands it.

Two things that path had to get right, both of which bit during
development and both of which are guarded now:

* **Zones are inherited, not refilled.** `--no-route` runs
  `kicad-cli pcb drc` *without* `--refill-zones`, which is not merely 0.8 s
  cheaper — it is required. KiCad's filler is idempotent once a zone is
  filled, but filling an empty zone and refilling a full one do not agree:
  refilling this board's +3V3 pour rewrites ~180 lines of its
  `filled_polygon`. The full path fills from empty, so the fast path has to
  leave that fill alone or lose byte-identity on the pour.
* **The board is canonicalised on the way in, not just out.** Tracks and
  vias keep the uuids the file gave them, and KiCad's writer breaks
  position ties between items with the uuid — so a board last saved by
  something that does not canonicalise (the KiCad GUI) would serialise its
  copper in an order a full build never produces.

Equivalently, by hand:

```bash
cd hardware/kicad
python3 generator/gen_sch.py bisque-controller.kicad_sch        # schematic
python3 generator/check_netlist.py bisque-controller.kicad_sch  # KiCad netlist round-trip: must PASS
"$KPY" generator/kicad_build.py bisque-controller.kicad_pcb     # board via pcbnew API:
                                                                #   (add --no-route to reuse the routing
                                                                #    already on disk — see "Which path
                                                                #    does your change need?")
                                                                #   system-library footprints, octilinear
                                                                #   45-degree autoroute (2 signal layers),
                                                                #   In1.Cu/In2.Cu plane fills, GND stubs,
                                                                #   pour-island healing, KiCad DRC report
python3 generator/check_pinmap.py                                # design.py <-> Kconfig agreement: PASS
python3 generator/check_sch_bounds.py bisque-controller.kicad_sch  # nothing off the declared sheet: PASS
python3 generator/check_sch_layout.py bisque-controller.kicad_sch  # nothing drawn on top of anything: PASS
                                                                #   (every other checker validates connectivity,
                                                                #    which is complete no matter where a symbol
                                                                #    sits — this is the one that notices the
                                                                #    exported PDF is missing half the circuit)
python3 generator/check_pcb.py bisque-controller.kicad_pcb      # independent checker: ALL CHECKS PASS
"$KPY" generator/check_via_in_pad.py bisque-controller.kicad_pcb  # no via inside an SMD pad: PASS
python3 generator/check_drill_clearance.py bisque-controller.kicad_pcb  # hole-to-hole >= 0.30 mm: OK
                                                                #   (net-independent: a drill bit does not
                                                                #    care that a slot and the via beside it
                                                                #    are both GND, and every net-aware check
                                                                #    we own missed a 0.078 mm web because
                                                                #    of it — see FAB-READINESS-REVIEW-REVB)
"$KPY" generator/check_silk.py bisque-controller.kicad_pcb      # silkscreen printable: PASS
                                                                #   (hard-fails on silk over an exposed pad
                                                                #    or clipped by Edge.Cuts; silk-on-silk
                                                                #    is budgeted, and the budget is 0)
python3 generator/check_canonical.py bisque-controller.kicad_pcb  # reproducibility guard: ALL CHECKS PASS
                                                                #   (KiCad DRC can't see this - a via and
                                                                #    the pad it sits in share a net, and
                                                                #    clearance rules skip same-net copper)
python3 generator/render_pcb.py bisque-controller.kicad_pcb preview-board.svg

# Fab outputs — regenerate these together, after the board file is final.
# The --layers list is what JLCPCB needs; without it kicad-cli also emits
# Fab/Courtyard/User layers that don't belong in a fab package. Note the
# two inner layers, In1.Cu (GND plane) and In2.Cu (+3V3 plane) — new on rev B.
kicad-cli pcb export gerbers -o gerbers/ \
  --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts" \
  bisque-controller.kicad_pcb
kicad-cli pcb export drill -o gerbers/ --format excellon --excellon-units mm \
  --excellon-zeros-format decimal --generate-map --map-format gerberx2 \
  --gerber-precision 5 bisque-controller.kicad_pcb
python3 generator/gen_jlc.py jlcpcb          # BOM.csv + CPL.csv (prints rotation fixes + feeder-fee count)
kicad-cli sch export pdf -o pdf/bisque-controller-schematic.pdf bisque-controller.kicad_sch
kicad-cli pcb export pdf --mode-single -l "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Silkscreen,Edge.Cuts" \
  -o pdf/bisque-controller-board.pdf bisque-controller.kicad_pcb
./generator/render-3d.sh                     # 3d/board-3d-*.png (raytraced)
```

**The board build is reproducible.** Rebuilding an unchanged `design.py`
produces a byte-identical `bisque-controller.kicad_pcb`, so regenerating
and diffing is a real check that the committed board still matches the
design beside it. That does not come for free: pcbnew hands every item it
creates a random uuid and then *orders the saved file by it*, so an
identical design used to serialise differently every run — a huge diff over
tens of thousands of lines, which made any regenerated board unreviewable
(#234). `kicad_build.py` therefore routes every write through
`generator/canonicalize.py`, which replaces each uuid with one derived
from that item's own content and sorts items on the same key. The zone
fill settles too, since KiCad's filler is deterministic once its input
is. `check_canonical.py` guards this by re-shuffling and re-minting a
real board and asserting the canonical form doesn't move; it needs
neither KiCad nor pcbnew.

One other source of run-to-run drift lived in `kicad_build.py` itself
until the fast path flushed it out. `MODEL_OFFSET` rebuilds a footprint's
3D-model entry, because `fp.Models()` hands back copies that cannot be
mutated in place — and it used to carry the old entry's scale and
rotation as `VECTOR3D` *references into those copies*. Once the copy was
collected the reference dangled, so U1's model scale saved as `(1 1 1)`
or `(0 0 0)` depending on when Python happened to run the collector. A
model scaled to zero renders nothing. The values are unpacked to plain
floats now.

**Rails terminate in power ports, signals in global labels.** A boxed
global label reading `GND` and one reading `SPI_MOSI` are the same shape, so
telling ground from a signal meant reading 3 mm of 1.27 mm text — 155 times,
since rails were 38% of every label on the sheet (`GND` alone appeared 86
times). `gen_sch.py` now ends a rail's stub with the real `power:` symbol
instead: a ground triangle and a rail arrow are recognised by silhouette.
140 terminations converted; global labels dropped 406 → 266.

Membership is **derived, never listed**: a net qualifies exactly when KiCad's
power library holds a symbol of that name, which today means `GND`, `+3V3`,
`+5V` and `VBUS` (`VIN`, `VLED`, `AUX_VP` and `SSR_EN` have no such symbol
and keep their labels). That is also what makes it safe — KiCad takes a
`(power global)` symbol's net name from its Value field, so an exact name
match is the guarantee the net name survives, and `check_netlist.py`
round-trips through KiCad to prove it did (93 nets, 0 mismatches, unchanged).
The ports are schematic-only: `design.py` is untouched, so the board, the
gerbers, the BOM and the CPL are bit-for-bit what they were.

Three things this forced, each of which had been wrong and invisible:

* **`check_sch_layout.py` grew every symbol one pin-length in the wrong
  direction.** Its pin handling negated the stem, so a body box reached
  *outward* past each connection point instead of back toward the body —
  straight through the corridor where that pin's own stub and terminator
  live. Harmless while only symbols were compared to symbols; the moment
  rails became ports it reported 75 collisions between parts and the ports on
  their own pins.
* **It compared symbols as one rectangle unioning body and fields**, which
  cost it both directions: it could not see a field printed over its own body
  (44 of them — `3.579545MHz` through Y1's plates, `ESP32-S3-WROOM-1U-N16R2`
  through U1's stub), and it called every port that legitimately sits between
  a body and the field above it a collision. It now compares body and fields
  as separate parts — 708 parts rather than 286 boxes — with a part's own
  Reference/Value pair the one exempt combination, since they are stacked
  1.9 mm apart under a ~2.1 mm estimated line height and always "overlap".
* **`field_pos()` measured the field band from the topmost pin only.** A
  crystal's or a SOIC's outline reaches above its highest pin, so the fields
  landed inside the part; and clearing the pin is not clearing the pin's
  *terminator*, which is what printed nine ICs' values through their own
  power stubs. It now clears the body and the whole upward corridor.

Two ports on adjacent pins would still print into each other — a `GND` port
is 3.05 mm of text under a 2.54 mm triangle, wider than the 2.54 mm pin
pitch, and U7 carries three grounds in a row. `stub_pins()` assigns crowded
neighbours to lanes, pushing every other one 5.08 mm further out along its
own stub. The rule demands 1.27 mm of clear space rather than merely no
overlap: `+3V3` twice over U3's AVDD/DVDD pair passed a collision test and
read as `+3V3+3V3`. One model serves the packer's reserved extent, the field
placement and the emitted geometry, because a reserved box that is not the
drawn box is exactly how two stubs land on one point and silently merge two
nets.

**Silkscreen is placed by a packer, not by a table.** Where every
reference designator and board label lands is derived, the same way
`gen_sch.py`'s column packer replaced the schematic's hand-maintained
`SCH_AT` table. It had the same history: `gen_pcb.SILK` held 51 absolute
coordinates authored when the board had 52 parts, and `kicad_build.py`
carried a list of 18 designators hand-nudged out of collisions. At 141
parts a patch list cannot keep up, and it didn't — KiCad reported **109
silkscreen violations across 49 designators**, including `5V / OUT` and
`AUX OUT` (labels for screw terminals a user hand-wires) printed half off
the board edge, and 24 labels sitting on exposed pads.

`generator/silk.py` now scores candidate placements for each label —
north/south/east/west of its own part at several gaps and lateral slides,
then rings around its anchor — and picks the cheapest, deterministically:

* **hard**: never over an exposed pad (ink on bare copper is a solder
  defect, not a cosmetic one), never crossing `Edge.Cuts`;
* **soft**: minimise silk touching other silk, and stay close to the thing
  being labelled — a designator far from its part is worse than a cramped
  one.

What survives in `SILK` is *intent only*: what a label says and roughly
where it belongs. Those coordinates are anchors that the packer is free to
move — which is also how a stale anchor got caught: `SSR2` was anchored at
y=83.0, inside **J4's** courtyard rather than J9's, so it printed against
the wrong terminal. Each SSR terminal now carries one merged
`SSR1  5V / OUT` / `SSR2  5V / OUT` label in the gap directly above its own
block; the four left-edge blocks leave gaps of only 1.3–2.1 mm, so one
label per gap is what fits, and a merged label cannot drift away from the
pin order it belongs to.

Two things the packer deliberately does **not** do, both tried and reverted
because they made the board worse: charging a label for printing inside a
part's courtyard (it evicted `SSR2` from J9's narrow gap up beside J4, and
pushed J6's reference in between two of J6's own pin names), and rotating
labels 90° to fit. Collision geometry is KiCad's own effective shapes, not bounding
boxes — a rectangle model reported *no* collision for text sitting inside
BZ1's circular outline, which the real glyph strokes do hit. Labels stay
upright; nothing was shrunk (references are 0.8 mm as before).

One scoring term is not obvious and is load-bearing: a board text pays four
times as much for sliding **along** its reading direction as across it. The
28 pin names above J5/J6/J7 identify a pin by sitting over it, so a label
that drifts sideways doesn't just look ragged — it names the wrong pin.

`generator/check_silk.py` (`make pcb-check`) proves the result, net-
independently: it hard-fails on any silk item over an exposed pad or
crossing the board outline, and fails if silk-on-silk exceeds
`SILK_ON_SILK_MAX`, which is committed at the number the board actually
achieves. It was calibrated the right way round — run against the *old*
board it reports exactly the 24 over-copper and 4 edge-clipped items, and
its silk-on-silk rule counts exactly the 81 `silk_overlap` violations
kicad-cli reported. The board now scores 0 / 0 / 0.

**Test points name their net.** `TP1`–`TP12` print what they probe
(`+3V3`, `+5V`, `GND`, `MOSI`, `SCLK`, `MISO`, `SDA`, `SCL`, `SSR1`,
`SSR2`, `CT A+`, `WDT`) so the board documents itself at the bench. The
label is derived from `design.py`'s own net for pin 1 — never a second
hand-typed table — and shortened by rule: rails print verbatim, a bus
prefix is dropped (`SPI_MOSI` → `MOSI`), a function suffix is dropped
(`WDT_HOLD` → `WDT`). `gen_pcb.TP_LABEL_SPECIAL` is the single escape
hatch, next to the rule it excepts.

**Zone fills feed the gerbers.** `kicad_build.py` finishes with a
`kicad-cli pcb drc --refill-zones` pass that rewrites the board file
(filling In1.Cu and In2.Cu along with any surface zones), so export
gerbers *after* that step — exporting first bakes stale pours into
`gerbers/`.

(`gen_pcb.py` remains as a KiCad-free fallback generator that writes the
board file textually; `kicad_build.py` is the authoritative path.)

3D renders: `./generator/render-3d.sh` drives `kicad-cli pcb render`
(raytraced, official component models). `render_3d.py` remains as a
KiCad-free fallback (stylized three.js renders via headless chromium).

**One 3D model must be installed by hand, or U1 renders as bare pads.**
KiCad 10 ships `ESP32-S3-WROOM-1.step` and `-WROOM-2.step` but **not**
`ESP32-S3-WROOM-1U.step`, which is the variant this board uses. The
footprint references it, `kicad-cli` cannot find it, and — this is the part
that wastes an afternoon — **it fails silently**: the render exits 0, prints
"Loading 3D models…", and simply omits the module. Nothing warns you. Fetch
it from Espressif's own library and drop it where the footprint already
points:

```bash
curl -sSL -o "$(dirname "$(which kicad-cli)")/../share/kicad/3dmodels/RF_Module.3dshapes/ESP32-S3-WROOM-1U.step" \
  https://raw.githubusercontent.com/espressif/kicad-libraries/main/3dmodels/espressif.3dshapes/ESP32-S3-WROOM-1U.STEP
# macOS app-bundle install:
#   /Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels/RF_Module.3dshapes/
```

It is 8.4 MB, which is why it is not vendored into this repo — the renders
are cosmetic, are already a manual step, and nothing in the fab package
(gerbers, drill, BOM, CPL, DRC) touches 3D models at all. The consequence to
accept knowingly: the committed renders are **not** reproducible on a clean
machine until that file is fetched, and a KiCad upgrade wipes an app-bundle
install. Do **not** work around it by pointing the footprint at the
`ESP32-S3-WROOM-1` model — the 1U body is 6.3 mm shorter precisely because
it has no PCB antenna, so that substitution draws the module straight
through the reclaimed antenna band where USB-C, the reset switch and three
test points now live, depicting a collision that does not exist.

**The origin mismatch is already handled** — you only need to drop the file
in. Espressif's STEP is authored with its origin at a body *corner* (body
spans X 0…18, Y 0…19.2 mm), while KiCad's footprint origin is the body
*centre*, so the raw model renders the module ~9.6 mm off its own pads and
hanging over the board edge. `MODEL_OFFSET` in `kicad_build.py` corrects it
with `(-9, -9.6, 0)`, cross-checked two ways: the body centre measured
directly off the STEP, and Espressif's own footprint value (`-9, -9.75, 0`)
adjusted by the 0.15 mm difference between their footprint origin and
KiCad's — a difference confirmed across all 40 signal pads (`dX` 0.0,
`dY` −0.15). After the offset, the body clears every castellated pad centre
by a symmetric 0.25 mm on three sides.

**Why KiCad's footprint rather than Espressif's**, since the model is
theirs: the two are the same 41-pad array offset by that 0.15 mm, but
KiCad's pad 41 carries 13 instances including **through-hole thermal vias**
where Espressif's has 9 surface pads only. On this 4-layer board those vias
tie the module's ground pad straight to the In1.Cu GND plane, and the
loader already upsizes their 0.2 mm drills to 0.3 mm for JLCPCB's standard
range. Switching would lose that, force a re-route for 0.15 mm, invalidate
the `generator/fp/` snapshot and the CPL, and add a `${KICAD8_3RD_PARTY}`
path dependency.

If pin assignments change in `main/Kconfig.projbuild`, update
`generator/design.py` to match and regenerate; `make pcb-check`'s
`check_pinmap.py` step fails the build if the two drift apart again.
(`generator/fp/` keeps a snapshot of older KiCad library footprints for the
fallback generator; `kicad_build.py` uses the installed system libraries
instead.)

## Safety

This board switches an external SSR's **control input** only — board +5 V
out, switched low side back, both channels. It is **not** opto-isolated: rev
B built that and reverted it, because an optocoupler only isolates when the
SSR control loop is powered off-board and this board powers it.

**Consequence — use a genuinely isolated SSR.** `J4` and `J9` are now common
with board `GND`, which is common with the USB shield and therefore with
whatever the controller is plugged into. **The SSR's own internal
control-to-load isolation is the only barrier between the kiln's mains and
this board.** Every reputable DC-input SSR provides it — it is what the
"solid state relay" part class means — but it is now load-bearing rather
than a second line of defence, so specify a part with a stated
control/load isolation rating and do not substitute a bare TRIAC or MOSFET
switching module. Check the isolation figure on the datasheet, not the
marketplace listing.

All mains wiring — SSR load side,
kiln elements, breakers, enclosure grounding — is external and must follow
local electrical code. The on-board hardware watchdog (`SJ2`/`WDT_KICK`,
above) is a **supplementary** interlock that de-energizes both SSR channels
if firmware stops toggling its kick pin; it is not a substitute for a
mechanical over-temperature cutout in series with the element contactor.
Fire kilns with appropriate supervision and hardware over-temperature
protection.
