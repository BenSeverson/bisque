# GPIO Pin Assignments

Status: **reference** — companion to
[`application-roadmap-and-pcb-provisions.md`](application-roadmap-and-pcb-provisions.md),
which proposes the expansion this doc allocates pins for, and to
[`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md`](superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md),
the design record for the rev B respin this doc now describes as-built.

This is the one place the *whole* pin map is written down. It exists because the
assignment is spread across three files that must agree and have already drifted
apart once:

| File | Owns |
|---|---|
| `main/Kconfig.projbuild` | **Source of truth.** Defaults for every configurable pin |
| `components/app_config/include/app_config.h` | Exposes them as `APP_PIN_*` macros |
| `hardware/kicad/generator/design.py` | The PCB net list; mirrors the Kconfig defaults |

Change a pin in Kconfig and you must update `design.py`, both SVGs in this
directory, the pin table in `hardware/kicad/README.md`, and this doc.
`hardware/kicad/generator/check_pinmap.py` (run via `make pcb-check`) asserts
`design.py`'s net-to-module-pin table matches the Kconfig defaults, so a
drift between those two specific files fails loudly; the SVGs and this doc
are not machine-checked and rely on being kept in sync by hand.

## 1. Current assignment (as-built, rev B)

Board: ESP32-S3-**WROOM-1U-N16R2** (16 MB flash, **quad** PSRAM, U.FL external
antenna). ADC1 = GPIO 1–10, ADC2 = GPIO 11–20 (ADC2 is unreliable while Wi-Fi
is active). "Module pin" is U1's pin number in `design.py`.

| GPIO | Module pin | ADC | Net | Function | Kconfig | State |
|---|---|---|---|---|---|---|
| 0 | 27 | — | `IO0` | BOOT button (SW2) | — | strapping |
| 1 | 39 | ADC1_0 | `IN3` | Protected input 3 (spare) | `KILN_PIN_IN_SPARE` | routed, default `-1`, **no driver** |
| 2 | 38 | ADC1_1 | `IN2` | Protected input 2 (gas flow) | `KILN_PIN_IN_GASFLOW` | routed, default `-1`, **no driver** |
| 3 | 15 | ADC1_2 | `LCD_BL` | Display backlight | `KILN_PIN_LCD_BL` | active, strapping |
| 4 | 4 | ADC1_3 | `IN1` | Protected input 1 (lid) | `KILN_PIN_LID_SWITCH` | **active** (default `4`, matches the PCB) — [needs a switch or a jumper](#if-you-do-not-fit-a-lid-switch) |
| 5 | 5 | ADC1_4 | `T_CS` | Touch controller CS | `KILN_PIN_TOUCH_CS` | routed, default `5`, **no driver** |
| 6 | 6 | ADC1_5 | `T_IRQ` | Touch pen-down interrupt | `KILN_PIN_TOUCH_IRQ` | routed, default `6`, **no driver** |
| 7 | 7 | ADC1_6 | `ALARM` | Buzzer BZ1 | `KILN_PIN_ALARM` | active |
| 8 | 12 | ADC1_7 | `LCD_CS` | Display CS | `KILN_PIN_LCD_CS` | active |
| 9 | 17 | ADC1_8 | `LCD_DC` | Display D/C | `KILN_PIN_LCD_DC` | active |
| 10 | 18 | ADC1_9 | `TC1_CS` | Thermocouple 1 (MAX31856) CS | `KILN_PIN_TC1_CS` | active |
| 11 | 19 | ADC2_0 | `SPI_MOSI` | SPI2 shared bus | `KILN_PIN_SPI_MOSI` | active |
| 12 | 20 | ADC2_1 | `SPI_SCLK` | SPI2 shared bus | `KILN_PIN_SPI_SCLK` | active |
| 13 | 21 | ADC2_2 | `SPI_MISO` | SPI2 shared bus | `KILN_PIN_SPI_MISO` | active |
| 14 | 22 | ADC2_3 | `AUX1` | Vent relay, via ULN2003 (U6) → J10.2 | `KILN_PIN_VENT` | **active** (default `14`, matches the PCB) |
| 15 | 8 | ADC2_4 | `AUX2` | Aux channel 2, via U6 → J10.3 | `KILN_PIN_AUX2` | routed, default `-1`, **no driver** |
| 16 | 9 | ADC2_5 | `AUX3` | Aux channel 3, via U6 → J10.4 | `KILN_PIN_AUX3` | routed, default `-1`, **no driver** |
| 17 | 10 | ADC2_6 | `SSR1_CTRL` | SSR zone 1 MOSFET gate (Q5) | `KILN_PIN_SSR1` | active |
| 18 | 11 | ADC2_7 | `I2C_SDA` | I2C data | `KILN_PIN_I2C_SDA` | routed, default `18`, **no driver** |
| 19 | 13 | ADC2_8 | `USB_DN` | USB-C D− | — | fixed function |
| 20 | 14 | ADC2_9 | `USB_DP` | USB-C D+ | — | fixed function |
| 21 | 23 | — | `SSR2_CTRL` | SSR zone 2 MOSFET gate (Q6) | `KILN_PIN_SSR2` | routed, default `21`, **no driver** |
| 35 | 28 | — | `TC2_CS` | Thermocouple 2 (MAX31856) CS | `KILN_PIN_TC2_CS` | routed, default `35`, **no driver** |
| 36 | 29 | — | `WDT_KICK` | Hardware watchdog kick | `KILN_PIN_WDT_KICK` | firmware kicks at 5 Hz; **hardware not yet resized — see [WDT DEFEAT](#the-watchdog-jumper)** |
| 37 | 30 | — | — | **spare** | — | free (freed by the quad-PSRAM module) |
| 38 | 31 | — | `BTN_UP` | Nav Up | `KILN_PIN_BTN_UP` | active |
| 39 | 32 | — | `BTN_DOWN` | Nav Down | `KILN_PIN_BTN_DOWN` | active |
| 40 | 33 | — | `BTN_LEFT` | Nav Left | `KILN_PIN_BTN_LEFT` | active |
| 41 | 34 | — | `BTN_RIGHT` | Nav Right | `KILN_PIN_BTN_RIGHT` | active |
| 42 | 35 | — | `BTN_SEL` | Nav Select | `KILN_PIN_BTN_SELECT` | active |
| 43 | 37 | — | `TXD0` | Console → J7.3 | — | UART0 |
| 44 | 36 | — | `RXD0` | Console → J7.4 | — | UART0 |
| 45 | 26 | — | — | not connected | — | strapping |
| 46 | 16 | — | `LCD_RST` | Display reset | `KILN_PIN_LCD_RST` | active, strapping |
| 47 | 24 | — | `I2C_SCL` | I2C clock | `KILN_PIN_I2C_SCL` | routed, default `47`, **no driver** |
| 48 | 25 | — | `LED_DATA` | WS2812B status LED | `KILN_PIN_STATUS_LED` | active |

**29 of 30 usable GPIOs assigned; GPIO 37 is the only spare.** (Quad PSRAM
frees GPIO 35/36/37 versus the octal-PSRAM module rev A's original plan
assumed — see §2 below.)

### Defaults now match the board

`VENT` (14) and `LID_SWITCH` (4) both default to their PCB GPIOs, so a board
build works without hand-configuration. `AUX2`, `AUX3`, `SSR2`, `TC2_CS`,
`I2C_SDA/SCL`, `TOUCH_CS/IRQ` and `WDT_KICK` are all routed and default to a
real GPIO (not `-1`, unlike rev A's `AUX_A`/`AUX_B`), but **nothing in
firmware drives or reads any of them yet** — each is declared so the board
and the firmware agree on what is routed, per the individual Kconfig help
text. `IN2` (gas flow) and `IN3` (spare) default to `-1` because the wiring
convention for an unused *protected input* is different from an unused
*output*: leaving an input enabled with nothing connected is harmless (it
just reads its idle level), but there is no firmware consumer for either yet,
so they default off to avoid implying a feature that isn't there.

The three pins that fail differently when unpopulated are worth separating.

**`VENT` is cosmetic.** With no relay wired, GPIO 14 drives the ULN2003 input
for a channel with nothing on the far side of the terminal — harmless. The
only effect is that the device reports `ventActive` and shows a VENT marker
on the LCD during firing below 700 °C whether or not a relay exists. Set
`KILN_PIN_VENT=-1` on a build with no vent to avoid claiming hardware you
don't have.

<a id="if-you-do-not-fit-a-lid-switch"></a>
**`LID_SWITCH` will stop the kiln heating.** This one is not cosmetic:

> **If you do not fit a lid switch, either fit a jumper between J11 pin 1 and
> J11's GND pin, or set `KILN_PIN_LID_SWITCH=-1`.** Do neither and the kiln
> will not heat.

The reason is the pull-up. `IN1` is held high by R13 (10 kΩ to +3V3) plus the
ESP32's internal pull-up, which `safety_init_io()` enables. A shut lid closes
a dry contact from J11.1 to GND, and the R12/R13 divider puts the pin at
~0.30 V — inside the ESP32's 0.83 V V_IL, so **closed contact = LOW = lid
shut**. Nothing connected means HIGH, which is **lid open**. A jumper to GND
is electrically identical to a permanently shut lid.

On a board with the J11 terminal left empty, the pull-ups alone produce the
same HIGH, so a build with no lid switch must set `-1` or fit the jumper.

With the lid reading open, and the default `lid_mode` of `pause`,
`lid_blocks_output()` holds the SSR low in `ssr_window_apply()` and
`firing_tick` refuses to start or immediately pauses the program. The open
reading is believed with **no debounce** (`safety_lid_debounce_step()` — only
*closing* is debounced), so it takes effect on the first sample.

That is deliberate fail-safe design **for open-circuit faults**: a broken wire,
a pulled connector or a switch that fails open all read open, so none of them
can defeat the interlock. Its cost is that an un-jumpered board presents as a
kiln that won't fire.

It is **not** immune to every fault. A short from the input conductor to GND, or
a switch welded or jammed closed, both hold the pin LOW — read as *lid shut* —
so the interlock stays armed but never cuts the element when the lid actually
opens. A jumper fitted in place of a switch is by definition indistinguishable
from that failure. The firmware cannot detect either case.

Polarity is inverted by `KILN_LID_SWITCH_OPEN_IS_LOW` if your switch pulls low
on opening — but read that option's help first, because it makes a broken wire
read "closed" and silently stops protecting you.

**None of this is a safety device.** It is a firmware interlock and does nothing
if the firmware crashes or the controller loses power. The real protection is a
mechanical microswitch in series with the element contactor.

<a id="the-watchdog-jumper"></a>
**`WDT_KICK` (36): firmware kicks a retriggerable one-shot.**
GPIO 36 drives the B input of `U10`, an SN74LVC1G123 retriggerable monostable
([#307](https://github.com/BenSeverson/bisque/issues/307),
`hardware/kicad/README.md` §"Hardware watchdog") gating the +5 V rail
(`SSR_EN`) that feeds both SSR channels.

Firmware toggles the pin at **5 Hz** — a rising edge every 200 ms — gated on
`safety_task`'s heartbeat (`components/safety/wdt_kick.h`), against a
worst-case one-shot window of 1.65–2.71 s (R46 100 kΩ × C38 22 µF): 8.3×
margin at the minimum window. Every rising edge restarts the window, and a
pin wedged high or low delivers no edge, so it fails exactly like a pin that
stopped. When the kick stops — firmware death, a wedged core, supervision
lost — the window expires and both SSR outputs de-energize within 2.71 s,
regardless of what the firmware's outputs command.

The one-shot replaced rev B's BAT54S diode charge pump, which could not hold
the rail at any survivable kick rate: 0.63 V of gate drive at 5 Hz against
Q3's 1.45 V threshold, needing ≥ 250 Hz even at room temperature, with
Schottky reverse leakage in the timing path roughly doubling per 10 °C — see
the README for the full arithmetic. **On a current board, leave the `WDT
DEFEAT` jumper (`SJ2`) open**: fitting it shorts the one-shot out and removes
the only interlock on this board that survives firmware death. Fit `SJ2` only
on a board assembled from a pre-one-shot package (charge pump where `U10` now
sits), where the SSRs cannot energize without it. Either way, a "kiln won't
heat" report on a fresh board means check the kick (scope GPIO 36, or `TP12`
for the timing node) before blaming the SSRs or the lid interlock.

## 2. Constraints that shape the map

1. **GPIO 1–10 (ADC1) carry mostly digital functions on rev B**, same as rev A —
   buttons moved off this range in the re-map (see §3.1 below), but three
   protected inputs, touch CS/IRQ, LCD BL/CS/DC and TC1 CS now occupy it
   instead. The board's one current-sense input (the ADE7953 CT front-end,
   §3.6 of the roadmap) is a **digital I2C part**, not an ADC1 consumer, so
   this row of GPIO 1–10 no longer doubles as an analog-input rescue plan the
   way the pre-rev-B roadmap draft assumed.
2. **Strapping pins**: 0, 3, 45, 46. GPIO 3 and 46 are already spent on LCD
   backlight and reset. Do not add new functions to 0 or 45.
3. **USB**: 19/20 are the native USB peripheral — leave them alone.
4. **PSRAM**: the WROOM-1U-N16R2 uses **quad** PSRAM, which frees GPIO 35, 36
   and 37 for TC2 CS, the watchdog kick, and one spare pin respectively. The
   octal-PSRAM WROOM-1-N16R8 module rev A's original roadmap draft assumed
   would have consumed all three internally instead.
5. **GPIO 33 and 34 are not broken out on ESP32-S3-WROOM-1/1U at all.** The
   module's 36 signal pins are fully enumerated in `design.py`'s `U1` table
   and neither appears.

## 3. Aux header J7 (as built)

8-pin Molex KK-254. Pins 1–4 are unchanged from rev A; pins 5–8 were
re-pointed from the retired `AUX_A`/`AUX_B` nets to the I2C bus during this
respin, since nothing on the board ever sourced `AUX_A`/`AUX_B` on J7 — the
real aux outputs are `AUX1`/`AUX2`/`AUX3` on the ULN2003 bank's own terminal,
J10 (§5).

| J7 pin | Net | GPIO | Notes |
|---|---|---|---|
| 1 | `+3V3` | — | |
| 2 | `GND` | — | |
| 3 | `TXD0` | 43 | UART0 console |
| 4 | `RXD0` | 44 | UART0 console |
| 5 | `I2C_SDA` | 18 | 0.1" I2C header, alongside Qwiic/STEMMA-QT connector J14 |
| 6 | `I2C_SCL` | 47 | |
| 7 | `+3V3` | — | |
| 8 | `GND` | — | |

The lid switch that used to occupy J7.6 in earlier drafts of this plan now
has its own terminal — J11 — along with the other two protected inputs;
see §5.4 of the hardware-design spec and the table below.

### J11 — protected inputs

| J11 pin | Net | GPIO | Role |
|---|---|---|---|
| 1 | `IN1` | 4 | Lid/door switch |
| 2 | `IN2` | 2 | Gas-flow interlock |
| 3 | `IN3` | 1 | Spare |
| 4 | `GND` | — | |

## 4. (deleted — the re-map has happened)

This section used to lay out a "planned" pin re-map. That plan is now the
as-built map in §1: rev B shipped it, with `check_pinmap.py` (`make
pcb-check`) asserting `design.py` and `main/Kconfig.projbuild` agree on every
GPIO. There is nothing left to plan here — see §1 for the current map, and
`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md` §3 for the
design record of how it was chosen, including §3.1's explanation of *why*
the re-map still happened even though its original ADC1-rescue rationale
(§2 above) turned out not to apply once the CT sense input went digital: the
five nav buttons moved to contiguous module pads to simplify routing, and
the three protected inputs stayed on ADC1-capable pins to leave a future
resistance-monitored interlock possible without another respin.

## 5. Aux output roles

The three aux channels (`AUX1`/`AUX2`/`AUX3`) are driven through a shared
ULN2003ADR Darlington array (U6) onto screw terminal J10, whose common return
is the externally-supplied `AUX_VP` rail (solder jumper `SJ1` ties it to
board +5V for plain 5V relays; leave it open for a 12V/24V solenoid supply).
Electrically the three channels are identical, so which one is "the vent" is
firmware policy, not wiring:

| Role | Predicate | Cadence |
|---|---|---|
| Vent (`AUX1`) | `is_firing && temp < VENT_MAX_TEMP_C` | 1 Hz firing tick |
| Purge solenoid (`AUX2`, planned default) | designated segment / process type | 1 Hz firing tick |
| Forced cool / beacon (`AUX3`) | negative PID error during designated segments | 1 Hz firing tick |
| Zone-2 SSR (`SSR2_CTRL`, its own gate — not an aux channel) | time-proportional duty | **100 ms SSR window** |

Only the vent is implemented today, in `safety.c` (`safety_update_vent()` /
`vent_write()`), and its pin and policy both live there. `AUX2` and `AUX3`
are routed and declared in Kconfig but undriven; the purge role is expected
to land on `AUX2` once firmware gains a driver for it (see
`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md` §5.2), but
this doc's job is to record the channel and terminal, not the firmware
policy.

`SSR2_CTRL` is listed here for cadence contrast only — it is the second SSR
zone's own low-side MOSFET gate (§1), not a member of the aux bank, and unlike
the aux channels it modulates on the 100 ms window rather than the 1 Hz tick
because it tracks the main SSR's duty cycle simultaneously by definition.

Reporting is a contract change whenever a role beyond vent lands: `ventActive`
is currently a hardcoded field in `build_status_json()`, omitted when no vent
is fitted. Role-configurable channels should report by role rather than
growing a `purgeActive` sibling — that touches `api_json.c`, both zod schemas
in `web_ui/src/app/schemas/`, both Swift models, and `make fixtures`.

## 6. Variant: I2C thermocouple front-end

Recorded here as an alternative that was considered and **not** taken for rev
B (rev B kept SPI, moving to 2× MAX31856 rather than an I2C part). If the
thermocouple front-end ever moves from SPI to an I2C part (e.g. MCP9601),
channels are addressed rather than chip-selected:

| Change | Effect |
|---|---|
| TC1 CS (GPIO 10) released | +1 pin |
| TC2 CS (GPIO 35) never needed | +1 pin |
| Both channels on the shared I2C bus | 0 pins per channel, scales to 8 devices |

Against that: I2C puts the primary safety sensor on a bus with a stuck-low
failure mode, and there is no I2C driver in the firmware today (the on-board
ADE7953 and the Qwiic/STEMMA-QT header are both wired but undriven as of this
respin). The existing 5-second stale-reading trip in `safety_task()` degrades
a wedged bus to a safe emergency stop rather than a stale reading, which is
the main mitigation were this ever taken.
