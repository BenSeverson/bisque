# PCB Rev B — Hardware Design

Date: 2026-08-10
Status: **approved design / not yet implemented**

Companion to [`application-roadmap-and-pcb-provisions.md`](../../application-roadmap-and-pcb-provisions.md)
(the provisions this revision realizes) and [`pin-assignments.md`](../../pin-assignments.md)
(the pin map this revision replaces).

Rev A (`hardware/kicad/`, 2-layer 100 × 80 mm, 52 footprints) is a prototype and
may be broken freely. Rev B is a **respin, not a variant**: it replaces the
thermocouple front-end with an incompatible part, moves most GPIOs, and changes
the module variant. No attempt is made to keep rev A boards working with rev B
firmware defaults.

## 1. Goals

Seven requested changes, plus the roadmap provisions each one drags in:

| # | Change | Roadmap § |
|---|---|---|
| 1 | Touch interface on the LCD | 3.7 |
| 2 | Re-map GPIO assignments | 3.1 |
| 3 | Atmosphere purge relay | 3.3 |
| 4 | Second SSR output (zone 2) | 3.3 |
| 5 | CT current sensing via a digital-interface chip on I2C/SPI | 3.6 (revised) |
| 6 | Second thermocouple input | 3.2 |
| 7 | MAX31856 replacing MAX31855 | 3.2 |

Pulled in because the above cannot work without them: three protected digital
inputs (§3.4 — the purge relay needs its gas-flow interlock), an I2C bus (§3.5 —
the CT chip lives on it), and a re-sized auxiliary output bank (§3.3).

Added on top, by explicit decision during design review: opto-isolated SSR
triggers, a hardware watchdog gating both SSR channels, TVS protection on the
externally exposed dry-contact and CT nets, and test points.

## 2. Decisions taken, and why

### 2.1 Module: ESP32-S3-WROOM-1-N16R8 → **WROOM-1U-N16R2**

`C2913202` → `C3013945`. $5.15 → $4.84, so **−$0.31/board**, 3.5k stock. Two
independent changes to the same component.

**Quad PSRAM, for the pin budget.** Octal PSRAM is the sole reason GPIO 35/36/37
are unusable on the current module; quad PSRAM shares the flash data lines and
releases all three. The module breaks out 36 signal pads — subtract USB (19/20),
strapping (0/45) and the UART0 console (43/44) and 30 remain, less another three
on an octal part:

| | N16R8 | N16R2 |
|---|---|---|
| Usable GPIOs | 27 | **30** |
| Demanded by this design | 29 | 29 |
| Slack | **−2** | **+1** (GPIO 37) |

PSRAM drops 8 MB → 2 MB. The only consumer is
`CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC` (`sdkconfig.defaults:60`), which routes OTA
TLS allocations off internal RAM; that needs tens of KB across GitHub's redirect
chain, not megabytes. Quad at 80 MHz halves PSRAM bandwidth versus octal, which
nothing here is sensitive to — LVGL's pool is 24 KB of internal RAM and the
display buffers are 30-row DMA slices.

**U.FL antenna connector, for RF in a metal enclosure.** A kiln controller mounts
on or near a large grounded steel shell, and a steel enclosure makes a PCB
antenna close to non-functional. The 1U carries a U.FL connector for an external
antenna on a pigtail, which can be placed where it actually works.

This also relieves §6.3. The WROOM-1 footprint carries a 48 × 21.7 mm antenna
keep-out rule area, of which roughly **330 mm²** lands on-board at rev A's
placement — a 48 × 7 mm copper-free band along the top edge, about 3.4 % of a
100 × 100 board. The 1U has no such zone, and this design **reclaims the band**
for parts and ground pour.

Two consequences to hold on to:

- **The land pattern is variant-specific in the CPL, not in copper.** The two
  KiCad footprints carry geometrically identical pad arrays — every pad differs
  by the same 3.15 mm Y offset, because the 1U body is 6.3 mm shorter and the
  origin is the body centre. A WROOM-1 will therefore *solder* onto 1U pads, but
  `gen_jlc.py` emits a CPL centre 3.15 mm wrong for it. Machine assembly picks
  one variant; the other is a hand-rework option only. Reclaiming the keep-out
  band forecloses even that, which is the accepted cost of the decision.
- **Antenna choice is a certification question.** Espressif's modular approval
  for the 1U is granted against specified antenna types and gains; a high-gain
  antenna steps outside it. Rev A's EMC note ("the ESP32-S3-WROOM-1 carries
  modular certification") must gain this caveat.

The pigtail (U.FL → SMA bulkhead) and the 2.4 GHz antenna are **accessories, not
BOM lines** — they go on the hand-solder/shopping list, and the enclosure needs a
bulkhead hole. U.FL is rated for ~30 mating cycles, so treat it as
assemble-once.

The firmware change for the swap itself is one line:
`CONFIG_SPIRAM_MODE_OCT` → `CONFIG_SPIRAM_MODE_QUAD`.

### 2.2 CT front-end: ADE7953 on I2C, current-only

`ADE7953ACPZ-RL`, `C515890`, LFCSP-28 (5 × 5 mm), $3.41, 4.8k stock, with a
3.579545 MHz crystal (`C7471632`, $0.11).

- **Two current channels**, which maps one-to-one onto the two SSR zones this
  revision adds, so each element bank gets an independent health reading.
- **I2C, not SPI** — costs zero GPIOs because the bus exists for §3.5 anyway,
  and 1 Hz register reads have no need of SPI.
- A dedicated 24-bit sigma-delta front-end keeps ESP32 ADC noise out of the
  measurement entirely. This is what retires roadmap §3.1's original
  justification: with the CT digital, **there is no analog demand left on the
  board at all.**

**No mains anywhere on the PCB.** The voltage channel is unused; power and
energy are derived as `Irms × configured nominal mains voltage`, which is a
±3–5 % estimate — adequate for element-health diagnosis and cost estimation,
which is all §3.6 and §4 ask for.

The voltage-channel pins are routed to a **DNP 2-pin SELV header** so that a
future off-board isolated AC accessory (a 9 V AC adapter or a ZMPT101B module)
upgrades the board to true power, power factor and line-frequency zero-crossing
as a firmware-only change. Nothing is populated there on this run.

Rejected: **ATM90E26** (429 in stock, no I2C, and its metering DSP takes line
sync from the voltage channel — the worst possible fit for a current-only
build); **ADS1115** (860 SPS is ~14 samples per 60 Hz cycle, so RMS becomes a
firmware burst-sampling problem at roughly ±5 %, and it offers one channel where
this design wants two).

### 2.3 Aux output bank: ULN2003ADR, not discrete drivers

`C7512`, SOIC-16, $0.158, 420k stock, and a JLCPCB **Basic** part — so seven
Darlington channels with integrated freewheel diodes arrive at **zero feeder
fee**, replacing roughly nineteen discrete parts. On a board that is
density-constrained (§6) this is the single largest area saving available.

### 2.4 Opto-isolated SSR triggers: LTV-817S-TA1-C

`C109227`, SMD-4P, $0.075, 598k stock, JLCPCB **Basic** — also no feeder fee.

Roadmap §3.3 specifies "opto-isolated" for the main SSR trigger; rev A never
implemented it and used a bare AO3400A low-side switch.

**What this buys is ground-loop and surge immunity, not mains safety.** The SSR
control loop is low-voltage on both sides of the barrier. The gain is that a
surge on SSR wiring — which runs beside mains and out to the kiln — no longer
has a conductive path back into the MCU, and the controller stops sharing a
ground reference with that wiring.

### 2.5 RTC: deleted from the board, provided by the I2C header

Roadmap §3.5 wanted a DNP DS3231 + coin-cell holder on-board. A DS3231 Qwiic
breakout is a ~$2 accessory on the bus this revision adds anyway, so the on-board
footprints would consume area on a board that cannot spare it while buying
nothing. **The I2C header is the RTC provision.** No RTC firmware in this scope.

### 2.6 Retired by this design

- **PCA9554/PCA9555 DNP GPIO expander** (§3.5). It existed as the escape valve
  for a pin budget with zero slack. The N16R2 swap leaves a real spare pin and
  the digital CT removes a demand; the expander is no longer earning its place.
- **On-board zero-cross detector** (§3.8). It needs a mains reference, which
  §2.2's isolation decision forbids. If it is ever wanted, it hangs off the same
  DNP SELV AC accessory header as the voltage channel and uses GPIO 37.

## 3. Pin map

ESP32-S3-**WROOM-1U-N16R2**. ADC1 = GPIO 1–10, ADC2 = GPIO 11–20 (unreliable
with Wi-Fi active). "Module pin" is U1's pin number in `design.py`; pad numbering
and function are identical across WROOM-1 and WROOM-1U, so the map below is
unaffected by the antenna decision.

| GPIO | Module pin | Net | Function | Kconfig | vs. rev A |
|---|---|---|---|---|---|
| 0 | 27 | `IO0` | BOOT (SW2) | — | unchanged, strapping |
| 1 | 39 | `IN3` | Protected input 3 (spare) | `KILN_PIN_IN_SPARE` | **new** |
| 2 | 38 | `IN2` | Protected input 2 (gas flow) | `KILN_PIN_IN_GASFLOW` | **new** |
| 3 | 15 | `LCD_BL` | Display backlight | `KILN_PIN_LCD_BL` | unchanged, strapping |
| 4 | 4 | `IN1` | Protected input 1 (lid) | `KILN_PIN_LID_SWITCH` | **moved** from 21 |
| 5 | 5 | `T_CS` | Touch chip select | `KILN_PIN_TOUCH_CS` | **new** |
| 6 | 6 | `T_IRQ` | Touch pen-down interrupt | `KILN_PIN_TOUCH_IRQ` | **new** |
| 7 | 7 | `ALARM` | Buzzer BZ1 | `KILN_PIN_ALARM` | unchanged |
| 8 | 12 | `LCD_CS` | Display CS | `KILN_PIN_LCD_CS` | unchanged |
| 9 | 17 | `LCD_DC` | Display D/C | `KILN_PIN_LCD_DC` | unchanged |
| 10 | 18 | `TC1_CS` | Thermocouple 1 CS | `KILN_PIN_TC1_CS` | **renamed** from `TC_CS` |
| 11 | 19 | `SPI_MOSI` | SPI2 shared bus | `KILN_PIN_SPI_MOSI` | unchanged |
| 12 | 20 | `SPI_SCLK` | SPI2 shared bus | `KILN_PIN_SPI_SCLK` | unchanged |
| 13 | 21 | `SPI_MISO` | SPI2 shared bus | `KILN_PIN_SPI_MISO` | unchanged |
| 14 | 22 | `AUX1` | Aux ch1 — vent relay | `KILN_PIN_VENT` | net kept, now via U6 |
| 15 | 8 | `AUX2` | Aux ch2 — purge solenoid | `KILN_PIN_AUX2` | was `AUX_A` |
| 16 | 9 | `AUX3` | Aux ch3 — spare (cool/beacon) | `KILN_PIN_AUX3` | was `AUX_B` |
| 17 | 10 | `SSR1_CTRL` | SSR zone 1 trigger | `KILN_PIN_SSR1` | **renamed** from `SSR` |
| 18 | 11 | `I2C_SDA` | I2C data | `KILN_PIN_I2C_SDA` | **new** |
| 19 | 13 | `USB_DN` | USB-C D− | — | fixed function |
| 20 | 14 | `USB_DP` | USB-C D+ | — | fixed function |
| 21 | 23 | `SSR2_CTRL` | SSR zone 2 trigger | `KILN_PIN_SSR2` | **displaces** `LID_SW` |
| 35 | 28 | `TC2_CS` | Thermocouple 2 CS | `KILN_PIN_TC2_CS` | **new** (freed by N16R2) |
| 36 | 29 | `WDT_KICK` | Hardware watchdog kick | `KILN_PIN_WDT_KICK` | **new** (freed by N16R2) |
| 37 | 30 | — | **spare** | — | freed by N16R2 |
| 38 | 31 | `BTN_UP` | Nav Up | `KILN_PIN_BTN_UP` | **moved** from 4 |
| 39 | 32 | `BTN_DOWN` | Nav Down | `KILN_PIN_BTN_DOWN` | **moved** from 5 |
| 40 | 33 | `BTN_LEFT` | Nav Left | `KILN_PIN_BTN_LEFT` | **moved** from 6 |
| 41 | 34 | `BTN_RIGHT` | Nav Right | `KILN_PIN_BTN_RIGHT` | **moved** from 2 |
| 42 | 35 | `BTN_SEL` | Nav Select | `KILN_PIN_BTN_SELECT` | **moved** from 1 |
| 43 | 37 | `TXD0` | UART0 console | — | unchanged |
| 44 | 36 | `RXD0` | UART0 console | — | unchanged |
| 45 | 26 | — | not connected | — | strapping |
| 46 | 16 | `LCD_RST` | Display reset | `KILN_PIN_LCD_RST` | unchanged, strapping |
| 47 | 24 | `I2C_SCL` | I2C clock | `KILN_PIN_I2C_SCL` | **new** |
| 48 | 25 | `LED_DATA` | WS2812B status LED | `KILN_PIN_STATUS_LED` | unchanged |

**29 of 30 usable GPIOs assigned; GPIO 37 is the only spare.**

### 3.1 Why the re-map still happens

Roadmap §3.1's stated purpose — freeing ADC1 for CT current sensing — is void
once the CT is digital. The re-map is kept for two different reasons:

1. The five nav buttons currently sit on GPIO 4/5/6/2/1, which are module pads
   4, 5, 6, 38 and 39 — split across opposite sides of the module. Moving them
   to GPIO 38–42 puts them on **contiguous pads 31–35**, which materially
   simplifies routing to J6 on a board that has a routing problem (§6).
2. The three dry-contact inputs land on ADC1 pins 1/2/4. They are digital today,
   but staying ADC-capable leaves a resistance-monitored interlock loop — where
   a cut cable and a closed switch read differently — possible without a respin.
   This is the one genuine remaining use for ADC1.

### 3.2 Boot-state requirements

Every output that can energize a heater, solenoid or relay must be inactive
from power-on through reset and through a firmware crash:

- `SSR1_CTRL`, `SSR2_CTRL` (17, 21): 10 kΩ pulldown at the opto input LED.
  Additionally gated by the §5.3 watchdog, which is un-kicked at boot.
- `AUX1`–`AUX3` (14, 15, 16): 10 kΩ pulldowns at the ULN2003 inputs. A
  high-impedance ESP32 pin at boot must not float the Darlington on.
- `ALARM` (7): rev A's existing pulldown.
- No new function is placed on GPIO 0 or 45.

## 4. Sensing subsystem

### 4.1 Thermocouples — 2 × MAX31856

`MAX31856MUD+T`, `C2653162`, TSSOP-14, $4.35 each, 7.7k stock. Replaces the
MAX31855KASA+ (SOIC-8, $2.37) entirely; the parts are not pin-compatible and no
attempt is made to support both on one board.

- Shared SPI2, one CS each (GPIO 10, 35). **SPI mode 1** (CPOL=0, CPHA=1) at
  ≤ 5 MHz, alongside the LCD's mode-0 40 MHz device — ESP-IDF configures mode
  and clock per device, so this is a driver detail, not a bus conflict.
- **`DRDY` and `FAULT` left unconnected on both chips.** Conversion status and
  fault detail are readable from registers, so polling saves four GPIOs. This is
  what makes the budget close with a spare.
- Each channel gets the datasheet-specified differential + common-mode input
  filter and its own screw terminal.
- **No TVS across thermocouple inputs.** A TVS array's leakage into a source
  producing ~40 µV/°C is an accuracy error, not protection. These two nets keep
  the RC plus the chip's own input clamps — the same reasoning rev A applied.
- **Ungrounded-junction probes are required.** Both chips reference T− to board
  ground, so two grounded-junction probes in one chamber form a ground loop
  through the kiln body. This is a documentation obligation, not a board change.

Firmware consequence, already analysed in
[`heat-treating-extension-plan.md`](../../heat-treating-extension-plan.md) §5.3
and **not implemented by this spec**: OTA reaches rev A hardware carrying a
MAX31855, so the shipped image must keep both backends and select at runtime by
probing the MAX31856's writable config registers.

### 4.2 CT current sensing — ADE7953

- Both current channels used, one per SSR zone; burden resistor, anti-alias RC
  and rail clamp diodes per channel.
- 3.579545 MHz crystal with load caps. I2C interface selected by pin strapping
  at reset.
- CT lead pair gets a TVS channel (§5.4) and a screw terminal.
- Voltage-channel pins routed to a DNP 2-pin SELV header (§2.2). Unpopulated.
- Placement sits in the quiet analog region with the thermocouple front-ends,
  away from the ULN2003 and the SSR/opto region (§6.2).

**Measurement caveat for the firmware plan:** with time-proportional control the
element current is a burst, not a continuous waveform, so `Irms` is only
meaningful when sampled inside the SSR on-window. This is true of any metering
part and is a firmware scheduling constraint, not a hardware one.

### 4.3 Touch

The XPT2046 is **on the LCDWIKI MSP4021 display module** — no touch controller is
placed on this PCB.

- `J5` grows from an 8-pin to a **14-pin** KK-254 header, carrying the module's
  full pin set: rev A's eight, plus the panel's `SDO` (which rev A left unwired
  because the firmware never reads from the display) and the five touch lines.
  (Footprint availability is a verification item — see §7.1.)
- `T_CLK` / `T_DIN` / `T_DO` are electrically SPI SCLK / MOSI / MISO and tie to
  the existing bus nets. Only `T_CS` (GPIO 5) and `T_IRQ` (GPIO 6) are new pins.
  `T_IRQ` gets a real dedicated pin here, which roadmap §3.7 could not afford.
- Five series resistors on the touch lines for damping — SPI2 now multi-drops
  four devices (LCD, TC1, TC2, touch) and stub discipline matters at 40 MHz.

### 4.4 I2C

`SDA` GPIO 18, `SCL` GPIO 47, pull-ups on board. Brought out on a Qwiic /
STEMMA-QT connector **and** a 0.1" header. Carries the ADE7953 on-board, and
supports the roadmap's SHT4x (wood kiln), an RTC breakout (§2.5), or an external
ADC without board changes.

## 5. Output, interlock and safety subsystem

### 5.1 SSR channels ×2 (opto-isolated)

Per channel: GPIO → series resistor → LTV-817S input LED → GND, with a **parallel**
indicator-LED branch off the same GPIO and a 10 kΩ pulldown. Five parts per
channel — the same count as rev A's discrete AO3400A driver.

The indicator cannot sit in series with the opto's input LED: ~2.0 V (indicator)
+ ~1.2 V (opto) leaves nothing to drop across a resistor from a 3.3 V GPIO. The
parallel branch costs one extra resistor and imposes no constraint on the user's
SSR control voltage. (An indicator placed in the isolated output loop would show
true end-to-end drive current for one fewer part, but would require a ≥ 5 V SSR
control supply; rejected as an unnecessary constraint.)

Output side floats on a 2-pin screw terminal per channel. A per-channel **solder
jumper** ties the opto collector to board +5 V for anyone who wants rev A's
convenience; default open = isolated, silkscreened as such.

**Cadence:** SSR2 is driven from the 100 ms `ssr_window_apply()` window, not the
1 Hz firing tick, exactly as `pin-assignments.md` §5 argues. Zone 2 modulates
simultaneously with zone 1 by definition.

### 5.2 Aux output bank — ULN2003ADR

| Channel | Role | GPIO |
|---|---|---|
| 1 | Vent relay | 14 |
| 2 | Purge solenoid | 15 |
| 3 | Spare — forced-cool damper / beacon | 16 |
| 4–7 | unused, brought to pads | — |

Integrated freewheel diodes return to **COM**, which lands on a dedicated
`AUX_V+` screw terminal rather than the board's +5 V rail. A gas purge solenoid
is realistically 12 V or 24 V DC; the ULN2003 is rated 50 V and 500 mA per
channel, so an externally supplied coil rail is both necessary and free. A
solder link ties `AUX_V+` to +5 V for plain 5 V relays.

The buzzer keeps its rev-A discrete driver (Q2/D4/R8/R11) rather than joining the
bank, so that a 5 V buzzer and a 24 V solenoid do not share a COM rail.

Roles are firmware policy, not wiring — the three channels are electrically
identical, which is why the Kconfig symbols for channels 2 and 3 are
role-neutral (`KILN_PIN_AUX2`, `KILN_PIN_AUX3`). `KILN_PIN_VENT` keeps its name
on channel 1 because `components/safety/` already drives it. **The purge role
lands on channel 2 by default when the firmware gains a driver for it; this spec
delivers the channel, the terminal and the gas-flow interlock input, not the
policy** (§9).

### 5.3 Hardware watchdog

GPIO 36 emits a square wave from firmware into a diode charge pump (BAT54S dual
Schottky, coupling cap, hold cap, bleed resistor) whose hold node drives a
MOSFET gating the **return path of both SSR opto input LEDs**. ~7 parts.

- **Gates only the heat outputs.** Vent, purge and the spare aux channel are
  untouched — a stalled controller should still be able to have its vent open.
- **A charge pump requires transitions.** A wedged firmware that leaves GPIO 36
  stuck high fails identically to one that stops toggling. A plain RC hold driven
  by a level would be defeated by a stuck-high pin; this is the whole reason for
  the pump topology.
- Decay to SSR-off in ~0.5–1 s.
- Un-kicked at power-on, so the SSRs are off through boot regardless of GPIO
  state.
- A silkscreened `WDT DEFEAT` solder jumper shorts the gate MOSFET for bring-up.

This is the first element on the board that still protects the user when the
firmware is gone. Every existing interlock — lid, over-temp, stale-thermocouple —
is firmware and dies with it. It remains supplementary: a mechanical
over-temperature cutout in series with the element contactor is still the real
protection, and the documentation must keep saying so.

### 5.4 Protected inputs ×3

Lid (GPIO 4), gas flow (GPIO 2), spare (GPIO 1). Each reuses rev A's proven
conditioning: 1 kΩ series, 10 kΩ pull-up to +3V3, 100 nF to ground, dry-contact
to GND. Screw terminals.

Polarity and fail-safe behaviour are unchanged from rev A: open contact reads
HIGH = "open/inactive", so a broken wire, pulled connector or failed-open switch
all fail safe. The lid input's existing `KILN_LID_SWITCH_OPEN_IS_LOW` option and
all of its documented caveats carry over verbatim.

### 5.5 TVS protection

Two `SRV05-4` arrays (`C558418`, SOT-23-6, $0.022, 377k stock) covering the three
dry-contact inputs and the CT pair, with spare channels.

Rev A deliberately skipped a TVS because no Basic-part TVS exists at LCSC and one
feeder fee for a single input was not worth it. That calculus inverts here: this
revision takes the count of externally exposed signal nets from two to roughly
ten, so one feeder fee covers the whole board.

**Explicitly not protected by TVS:** thermocouple inputs (§4.1, leakage) and the
SSR outputs (isolated — a clamp to board ground would bridge the barrier).

### 5.6 Test points

1 mm pads on `+3V3`, `+5V`, `GND`, `SPI_MOSI`, `SPI_SCLK`, `SPI_MISO`,
`I2C_SDA`, `I2C_SCL`, both SSR gate nets, the CT burden node, and the watchdog
hold node.

`FAB-READINESS-REVIEW.md` flags rev A's absence of test points across all 39 nets
as "awkward for bring-up". At ~114 footprints and eleven new subsystems, they
stop being optional.

## 6. Board

### 6.1 Form factor

**4-layer, 100 × 100 mm**, HASL, 1.6 mm. Signals on F.Cu/B.Cu, a GND plane on
In1.Cu and the +3V3 plane on In2.Cu. Mounting-hole grid grows from 90 × 70 mm to
90 × 90 mm, still 5 mm in from each edge. **Built and verified** — see the rung 3
outcome in §6.3.

> **Revised 2026-08-11, from measurement.** This originally specified **2-layer,
> 100 × 100 mm** — chosen deliberately over a 4-layer option, with the density
> risk stated up front. Implementation ran §6.3's escalation ladder and 2-layer
> did not close; the stack-up decision was escalated and 4-layer approved. The
> board targets a return to 100 × 100 mm with 0805 passives and rev A's net
> classes, since moving GND and the power rails onto inner planes should free
> more than the rung-1 and rung-2 concessions bought. It did: every concession
> was given back and the board reaches 0 DRC errors / 0 unconnected at
> 100 × 100 mm with 0805 passives and rev A's net classes. §6.3 records the
> measured outcome.

### 6.2 Placement partition

| Region | Contents |
|---|---|
| Quiet analog | TC1, TC2 and their cold-junction copper; ADE7953, crystal, CT front-end |
| Switching | ULN2003, SSR optos, aux and SSR terminals, buzzer |
| Digital | ESP32-S3 module, USB-C, LCD / nav / aux headers |
| Isolation barrier | Pour keepout band across the opto row; floating `SSR*_RTN` islands |
| Reclaimed antenna band | 48 × 7 mm at the top edge, freed by the 1U (§2.1) — available for parts and pour |

Cold-junction copper stays away from the regulator and the driver region, per
roadmap §3.2 and §3.9.

### 6.3 Density risk and escape hatch

This is the principal engineering risk in the revision, and it is accepted
deliberately rather than designed away.

| | Rev A | Rev B |
|---|---|---|
| Footprints | 52 | ~114 |
| Board area | 8,000 mm² | 10,000 mm² |
| Antenna keep-out lost to the PCB antenna | −330 mm² | 0 (§2.1) |
| Usable area | 7,670 mm² | 10,000 mm² |
| Density | 6.8 / 1000 mm² | ~11.4 / 1000 mm² |

`generator/router.py` is a 2-layer octilinear grid autorouter with GND pours on
both layers. Rev B roughly doubles its workload while *removing* pour area (the
isolation keepout) and adding an analog region that wants a quiet reference.

**Trigger and fallback, to be decided by evidence rather than optimism.** If,
after the placement partition in §6.2 is honoured, `kicad_build.py` cannot
produce a board with **0 DRC errors and 0 unconnected**, escalate in this order:

1. Move the new passives from 0805 to 0603 (both Basic parts, no feeder change).
2. Grow the board to ~125 × 100 mm — leaves the ≤ 100 × 100 fab tier, taking
   bare boards from ~$2–4 to ~$10–15 for 5 pcs. No generator work.
3. Go 4-layer at 100 × 100 mm — inner GND plane and inner power plane. Best
   electrical outcome by a wide margin, but requires teaching `router.py` and
   `kicad_build.py` about inner layers, plane fills and via-to-plane stitching.

Escalation is not a failure of this design; it is the pre-agreed response to a
measurement.

#### Measured outcome (2026-08-11)

The ladder ran in order and **2-layer did not close at any rung**:

| Rung | Configuration | Unroutable nets | DRC violations | Unconnected |
|---|---|---|---|---|
| 0 | 100 × 100, 0805 | 34 | 149 | 38 |
| 1 | 100 × 100, 0603 | 23 | 84 | 32 |
| 2 | 125 × 100, 0603 | 9 | 78 | 27 |

The nine survivors are short local nets **boxed in by neighbours' copper** in the
SSR driver cluster and the ADE7953 block. Growing the board bought only 23 → 9,
which is the signature of a **layer** shortage rather than an area shortage —
more space does not help a net that cannot escape its own neighbourhood. Rung 3
was approved rather than started by an agent, because it changes stack-up and
fabrication cost.

Two findings from the attempt stood regardless of stack-up, and both were
acted on below.

#### Rung 3 outcome (2026-08-11)

4-layer closed it, and then gave back **every one** of the concessions the
2-layer attempt had made:

| Step | Configuration | Unrouted nets | Unconnected pads | DRC errors |
|---|---|---|---|---|
| Layer conversion only | 125 × 100, 0603, 0.25 mm | 0 | 0 | 0 |
| Walk back rung 2 | **100 × 100**, 0603, 0.25 mm | 0 | 0 | 0 |
| Walk back rung 1 | 100 × 100, **0805**, 0.25 mm | 0 | 0 | 0 |
| Walk back net classes | 100 × 100, 0805, **0.3 / 0.7 mm** | 0 | 0 | 0 |

Final board: **100 × 100 mm, 4-layer, 0805 passives, rev A's net classes.**
The only violations left are silkscreen warnings (102), as in rev A.

Stack-up: signals on F.Cu and B.Cu, an unbroken GND plane on In1.Cu, the +3V3
plane on In2.Cu. In2 carries +3V3 **alone** rather than being split with +5V —
a split needs the two nets' consumers to fall in separable regions and +5V's do
not (regulator at the top-left corner, LCD header at the bottom edge, buzzer
mid-board, LED supply at the right), so a partition following them would leave
+3V3, the net that actually needs the plane, in slivers. +5V routes comfortably
as 0.7 mm track. Neither signal layer is poured: on rev B's density the GND
pour was the largest single consumer of routing space on exactly the two layers
the boxed-in signals needed.

The isolation barrier's pour keepout is `AllCuMask(4)`, inner planes included —
a GND plane under the optocouplers would defeat the barrier completely.
`check_pcb.py` confirms it independently by sampling the band against each
plane's filled polygons, because a zone fill is not a track and no item-based
check can see one.

Track widths came all the way back because the router no longer touches a
fine-pitch pad: each is represented to it by the far end of a pre-drawn escape
stub, so 0.25 mm is confined to the ~2 mm that geometrically requires it.

Two more unchecked code paths turned up alongside the `EN` one, both in the
same class and both fixed: `miter_corners()` chamfered corners that had a via
on them, orphaning the via; and A* took a via on `via_ok()` alone, so the first
segment after a via was never clearance-checked at its start point (invisible
at 0.25 mm, 0.172 mm from a pad at 0.7 mm).

### 6.4 Cost

| | Rev A | Rev B |
|---|---|---|
| BOM, machine-placed | ~$8.34/board | ~$18.5/board |
| Unique Extended parts | 4 ($12 feeder) | 6 ($18 feeder) |

The ~$10/board increase is almost entirely three chips: the second thermocouple
front-end and the upgrade of the first (+$6.33 net over the MAX31855) and the
ADE7953 (+$3.41).

Extended set changes: MAX31855 leaves; MAX31856, ADE7953 and the crystal join.
ULN2003ADR, LTV-817S and SRV05-4 are all **Basic** — three new subsystems at zero
feeder cost. The module swap returns $0.31/board.

Accessories, off-BOM and per unit: a U.FL → SMA bulkhead pigtail and a 2.4 GHz
antenna, ~$3–5 (§2.1).

Assembly stays **Economic** (SMD, top-side): the hand-solder split from rev A's
cost-reduction pass is preserved, with the new screw terminals and headers added
to `HAND_SOLDER` in `gen_jlc.py`.

## 7. Verification gates

Every one of these passes on rev A today and must pass on rev B before the design
is considered done:

| Gate | Command |
|---|---|
| Schematic netlist round-trip | `generator/check_netlist.py` — 0 mismatches |
| KiCad DRC | 0 errors, 0 unconnected |
| Independent connectivity check | `generator/check_pcb.py` — ALL CHECKS PASS |
| No via inside an SMD pad | `generator/check_via_in_pad.py` — PASS |
| Reproducibility | `generator/check_canonical.py` — PASS; rebuild byte-identical |
| BOM/CPL parity | equal designator sets, no line without an LCSC part |
| Firmware builds | `make firmware` with the new Kconfig defaults |

Additional rev-B-specific checks:

- **Isolation barrier**: assert no GND copper, on either layer, inside the opto
  keepout band; assert `SSR*_RTN` nets connect to nothing but their opto and
  terminal.
- **Pin-map agreement**: assert `design.py`'s net-to-module-pin table matches
  `main/Kconfig.projbuild` defaults. This has drifted before and is now checked
  rather than remembered.

### 7.1 Risks to retire before layout

1. **Does the ADE7953 report valid `IRMS` with its voltage channel unused?** Its
   metering DSP takes line synchronisation from the voltage channel. Current-channel
   RMS is believed independent, but this is unconfirmed against the datasheet and
   the entire CT feature rests on it. Extract with the `datasheets` skill and
   confirm before committing the analog section.
2. **MAX31856 pinout, supply arrangement and recommended input filter** must come
   from the datasheet, not from package convention. Rev A's fab review already
   records that the MAX31855 pinout was verified only by convention because the
   datasheet could not be downloaded; do not repeat that on a part being placed
   twice.
3. **KK-254 1×14 footprint availability** in the KiCad 10 library. If
   `Molex_KK-254_AE-6410-14A_1x14_P2.54mm_Vertical` does not exist, fall back to a
   generic 1×14 2.54 mm header and update the mating-connector list.
4. **ULN2003 input behaviour with a high-impedance ESP32 pin at boot** — confirm
   the 10 kΩ pulldowns in §3.2 are sufficient to guarantee all channels off.
5. **WROOM-1U CPL rotation and origin.** `JLC_ROTATION` in `gen_jlc.py` has no
   entry for the module today because the WROOM-1 needed none. The 1U's origin
   sits 3.15 mm from the WROOM-1's relative to the same pads (§2.1), so the CPL
   must be re-checked in JLCPCB's placement preview rather than assumed to carry
   over. A module placed 3.15 mm off is a dead board.
6. **U.FL connector clearance.** The connector stands proud of the module and the
   pigtail exits laterally; confirm the reclaimed antenna band's new parts do not
   foul either, and that the pigtail has a routing path to an enclosure wall.

## 8. Files this touches

| File | Change |
|---|---|
| `hardware/kicad/generator/design.py` | Components, nets, placement — the source of truth for both schematic and board |
| `main/Kconfig.projbuild` | All pin defaults per §3; renames (`TC_CS`→`TC1_CS`, `SSR`→`SSR1`, `AUX_A/B`→`AUX2/3`); new symbols for TC2, SSR2, touch CS/IRQ, I2C SDA/SCL, watchdog kick, and the two new protected inputs |
| `components/app_config/include/app_config.h` | Matching `APP_PIN_*` macros |
| `sdkconfig.defaults` | `CONFIG_SPIRAM_MODE_OCT` → `QUAD`, comment updated for N16R2 |
| `hardware/kicad/README.md` | GPIO map, BOM, assembly split, cost table; module variant, the antenna accessory list, the enclosure bulkhead hole, and the modular-certification caveat (§2.1) |
| `docs/pin-assignments.md` | §1 as-built table, §3 aux header, §4 (planned re-map becomes the as-built map), §5 aux roles, §6 |
| `docs/application-roadmap-and-pcb-provisions.md` | §2 and §3 — see below |
| `docs/perfboard-layout.svg`, `docs/wiring-diagram.svg` | Regenerate for the new pin map |
| `hardware/kicad/generator/gen_jlc.py` | `HAND_SOLDER` set, `JLC_ROTATION` entries for the new packages |
| `hardware/kicad/gerbers/`, `jlcpcb/`, `pdf/`, `3d/`, `preview-board.svg` | Regenerated artifacts |
| `hardware/kicad/FAB-READINESS-REVIEW.md` | **New review for rev B.** The existing file documents rev A and stays as history; it must not be edited into a claim about a board it never described. Its `CERT-001` modular-certification note is the one item that carries forward, with the §2.1 antenna caveat attached |

### 8.1 Roadmap claims this design falsifies

`application-roadmap-and-pcb-provisions.md` needs surgery, not a touch-up. These
statements become wrong and must be rewritten rather than annotated:

1. §2.1 / §3.1 — "ADC1 is fully occupied … there is effectively no usable analog
   input" and the framing of the re-map as an ADC1 rescue. The re-map happens, for
   the reasons in §3.1 above, but not for that reason.
2. §2.2 / §3.8 — "GPIO 35, 36, 37 … consumed by octal PSRAM on the **N16R8** this
   project actually targets". The project no longer targets N16R8.
3. §3.1 — "That consumes the pool exactly … there is no slack left." There is one
   spare pin.
4. §3.7 — "`T_IRQ` gets no dedicated pin … the chip is polled by default." It has
   a dedicated pin.
5. §3.5 / §3.8 — the DNP PCA9554 expander as "the designated escape valve" and
   "the real spare-capacity story for run 1". Retired (§2.6).
6. §3.6 — the CT input as an analog ADC1 channel. It is a digital I2C part.

## 9. Out of scope

Deliberately excluded, and each is a separate piece of work:

- **All firmware beyond pin definitions.** The multi-channel thermocouple driver,
  the MAX31856 backend and its runtime probe, the XPT2046 LVGL pointer indev and
  its calibration flow, the ADE7953 driver, the second PID/SSR zone, the aux-role
  policy engine, the watchdog kick task, and the gas-flow interlock are all
  follow-on plans. This spec fixes only the pin symbols and defaults the board
  requires.
- **API/schema contract changes.** `ventActive` growing into role-based reporting
  touches `api_json.c`, both zod schemas, both Swift models and `make fixtures`
  (`pin-assignments.md` §5). Not started here.
- **RTC and offline audit timestamps** (§2.5).
- **Mains voltage sensing, true power, and zero-cross control** — provisioned as a
  DNP SELV header only (§2.2, §2.6).
- **Rev A compatibility.** Rev A is a prototype; rev B firmware defaults will not
  drive it. The one exception is the OTA obligation in §4.1, which is a firmware
  concern.
