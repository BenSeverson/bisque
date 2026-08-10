# GPIO Pin Assignments

Status: **reference** — companion to
[`application-roadmap-and-pcb-provisions.md`](application-roadmap-and-pcb-provisions.md),
which proposes the expansion this doc allocates pins for.

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

## 1. Current assignment (as-built)

Board: ESP32-S3-WROOM-1-**N16R8** (16 MB flash, **octal** PSRAM).
ADC1 = GPIO 1–10, ADC2 = GPIO 11–20 (ADC2 is unreliable while Wi-Fi is active).
"Module pin" is U1's pin number in `design.py`.

| GPIO | Module pin | ADC | Net | Function | Kconfig | State |
|---|---|---|---|---|---|---|
| 0 | 27 | — | `IO0` | BOOT button (SW2) | — | strapping |
| 1 | 39 | ADC1_0 | `BTN_SEL` | Nav Select | `KILN_PIN_BTN_SELECT` | active |
| 2 | 38 | ADC1_1 | `BTN_RIGHT` | Nav Right | `KILN_PIN_BTN_RIGHT` | active |
| 3 | 15 | ADC1_2 | `LCD_BL` | Display backlight | `KILN_PIN_LCD_BL` | active, strapping |
| 4 | 4 | ADC1_3 | `BTN_UP` | Nav Up | `KILN_PIN_BTN_UP` | active |
| 5 | 5 | ADC1_4 | `BTN_DOWN` | Nav Down | `KILN_PIN_BTN_DOWN` | active |
| 6 | 6 | ADC1_5 | `BTN_LEFT` | Nav Left | `KILN_PIN_BTN_LEFT` | active |
| 7 | 7 | ADC1_6 | `ALARM` | Buzzer BZ1 | `KILN_PIN_ALARM` | active |
| 8 | 12 | ADC1_7 | `LCD_CS` | Display CS | `KILN_PIN_LCD_CS` | active |
| 9 | 17 | ADC1_8 | `LCD_DC` | Display D/C | `KILN_PIN_LCD_DC` | active |
| 10 | 18 | ADC1_9 | `TC_CS` | MAX31855 CS | `KILN_PIN_TC_CS` | active |
| 11 | 19 | ADC2_0 | `SPI_MOSI` | SPI2 shared bus | `KILN_PIN_SPI_MOSI` | active |
| 12 | 20 | ADC2_1 | `SPI_SCLK` | SPI2 shared bus | `KILN_PIN_SPI_SCLK` | active |
| 13 | 21 | ADC2_2 | `SPI_MISO` | SPI2 shared bus | `KILN_PIN_SPI_MISO` | active |
| 14 | 22 | ADC2_3 | `VENT` | Vent relay → J7.5 | `KILN_PIN_VENT` | **active** (default `14`, matches the PCB) |
| 15 | 8 | ADC2_4 | `AUX_A` | Aux output → J7.7 | `KILN_PIN_AUX_A` | routed, default `-1`, **no driver** |
| 16 | 9 | ADC2_5 | `AUX_B` | Aux output → J7.8 | `KILN_PIN_AUX_B` | routed, default `-1`, **no driver** |
| 17 | 10 | ADC2_6 | `SSR_CTRL` | Main SSR gate (Q1) | `KILN_PIN_SSR` | active |
| 18 | 11 | ADC2_7 | — | not connected | — | **free** |
| 19 | 13 | ADC2_8 | `USB_DN` | USB-C D− | — | fixed function |
| 20 | 14 | ADC2_9 | `USB_DP` | USB-C D+ | — | fixed function |
| 21 | 23 | — | `LID_SW` | Lid input ← J7.6 via R12/R13/C12 | `KILN_PIN_LID_SWITCH` | **active** (default `21`, matches the PCB) — [needs a switch or a jumper](#if-you-do-not-fit-a-lid-switch) |
| 35–37 | 28–30 | — | — | consumed by octal PSRAM | — | unusable on N16R8 |
| 38–42 | 31–35 | — | — | not connected | — | **free** |
| 43 | 37 | — | `TXD0` | Console → J7.3 | — | UART0 |
| 44 | 36 | — | `RXD0` | Console → J7.4 | — | UART0 |
| 45 | 26 | — | — | not connected | — | strapping |
| 46 | 16 | — | `LCD_RST` | Display reset | `KILN_PIN_LCD_RST` | active, strapping |
| 47 | 24 | — | — | not connected | — | **free** |
| 48 | 25 | — | `LED_DATA` | WS2812B status LED | `KILN_PIN_STATUS_LED` | active |

**Free today: 18, 38, 39, 40, 41, 42, 47 — seven pins.**

Three further pins are nominally free but should not be spent: 0 and 45 are
strapping pins, and 19/20 are the USB peripheral.

### Defaults now match the board

`VENT` (14) and `LID_SW` (21) both default to their PCB GPIOs, so a board build
works without hand-configuration. `AUX_A` (15) and `AUX_B` (16) are declared but
default to `-1` and **nothing reads them yet** — they are reserved for the
roadmap's §3.3 aux output bank; see §5.

The two enabled-by-default pins fail very differently when the hardware isn't
fitted, so they are worth separating.

**`VENT` is cosmetic.** With no relay wired, GPIO 14 drives an unconnected
header pin — harmless. The only effect is that the device reports `ventActive`
and shows a VENT marker on the LCD during firing below 700 °C whether or not a
relay exists. Set `KILN_PIN_VENT=-1` on a build with no vent to avoid claiming
hardware you don't have.

<a id="if-you-do-not-fit-a-lid-switch"></a>
**`LID_SW` will stop the kiln heating.** This one is not cosmetic:

> **If you do not fit a lid switch, either fit a jumper between J7 pin 6 and
> J7 pin 2 (GND), or set `KILN_PIN_LID_SWITCH=-1`.** Do neither and the kiln
> will not heat.

The reason is the pull-up. `LID_SW` is held high by R13 (10 kΩ to +3V3) plus the
ESP32's internal pull-up, which `safety_init_io()` enables. A shut lid closes a
dry contact from J7.6 to GND, and the R12/R13 divider puts the pin at ~0.30 V —
inside the ESP32's 0.83 V V_IL, so **closed contact = LOW = lid shut**. Nothing
connected means HIGH, which is **lid open**. A jumper to GND is electrically
identical to a permanently shut lid.

On a perfboard build with nothing wired to GPIO 21, the internal pull-up alone
produces the same HIGH, so a perfboard build must set `-1`.

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

## 2. Constraints that shape the map

1. **ADC1 (GPIO 1–10) is fully consumed by digital functions.** Since ADC2 is
   unusable with Wi-Fi active, the board as wired has *no usable analog input*.
   Fixing this is the roadmap's §3.1 and it is layout-time-only.
2. **Strapping pins**: 0, 3, 45, 46. GPIO 3 and 46 are already spent on LCD
   backlight and reset. Do not add new functions to 0 or 45.
3. **USB**: 19/20 are the native USB peripheral — leave them alone.
4. **Octal PSRAM**: on the N16R8 module, GPIO 35–37 are internally committed.
   They are free on quad-PSRAM/flash-only module variants, which is what makes
   the roadmap's §3.8 spare header module-dependent.
5. **GPIO 33 and 34 are not broken out on ESP32-S3-WROOM-1 at all.** The module's
   36 signal pins are fully enumerated in `design.py`'s `U1` table and neither
   appears. The roadmap's §3.8 refers to "GPIO 33–37"; on this module the spare
   header is **three** pins (35/36/37), not five. Worth confirming against the
   module datasheet before laying out that header.

## 3. Aux header J7 (as built)

8-pin Molex KK-254, silkscreened `3V3 GND TX RX VNT LID A15 A16`.

| J7 pin | Net | GPIO | Notes |
|---|---|---|---|
| 1 | `+3V3` | — | |
| 2 | `GND` | — | |
| 3 | `TXD0` | 43 | UART0 console |
| 4 | `RXD0` | 44 | UART0 console |
| 5 | `VENT` | 14 | Vent relay trigger |
| 6 | `LID_IN` | 21 | **Raw** input — reaches GPIO 21 through R12 (1k series) / R13 (10k pull-up) / C12. Wire a dry contact between J7.6 and J7.2 (GND); closed = lid shut |
| 7 | `AUX_A` | 15 | Reserved |
| 8 | `AUX_B` | 16 | Reserved |

## 4. Planned re-map (roadmap §3.1)

**Not yet implemented.** This is a concrete allocation consistent with §3.1's
budget; the roadmap gives the totals and a few examples but not a full mapping.
The re-map moves the five nav buttons and the alarm off ADC1 and is
**impossible to do after the first PCB run**.

| GPIO | ADC | Function | Provision | Change |
|---|---|---|---|---|
| 1 | ADC1_0 | CT current sense | §3.6 | **new** — must be ADC1; DNP on run 1 |
| 2 | ADC1_1 | TC channel 2 CS | §3.2 | **new** — DNP on run 1 |
| 3 | ADC1_2 | LCD backlight | — | unchanged (not recovered) |
| 4 | ADC1_3 | Touch `T_CS` | §3.7 | **new** |
| 5 | ADC1_4 | Protected input 1 — lid | §3.4 | **moved** from GPIO 21 |
| 6 | ADC1_5 | Protected input 2 — gas flow | §3.4 | **new** |
| 7 | ADC1_6 | Protected input 3 — spare | §3.4 | **new** |
| 8 | ADC1_7 | LCD CS | — | unchanged (not recovered) |
| 9 | ADC1_8 | LCD D/C | — | unchanged (not recovered) |
| 10 | ADC1_9 | TC channel 1 CS | §3.2 | unchanged (not recovered) |
| 11/12/13 | ADC2 | SPI MOSI / SCLK / MISO | §3.7 | unchanged; XPT2046 multi-drops here |
| 14 | ADC2_3 | Aux output 1 | §3.3 | = existing `VENT` |
| 15 | ADC2_4 | Aux output 2 | §3.3 | = existing `AUX_A` |
| 16 | ADC2_5 | Aux output 3 | §3.3 | = existing `AUX_B` |
| 17 | ADC2_6 | Main SSR | — | unchanged |
| 18 | ADC2_7 | I2C SDA | §3.5 | **new** |
| 19/20 | ADC2 | USB | — | unchanged |
| 21 | — | Alarm / buzzer | §3.1 | **moved** from GPIO 7; displaces `LID_SW` |
| 35–37 | — | Spare header | §3.8 | quad-PSRAM variants only; `T_IRQ` jumper lands here |
| 38–42 | — | Nav buttons ×5 | §3.1 | **moved** from GPIO 1/2/4/5/6 |
| 43/44 | — | UART0 console | — | unchanged |
| 46 | — | LCD reset | — | unchanged |
| 47 | — | I2C SCL | §3.5 | **new** |
| 48 | — | WS2812B | — | unchanged |

**Budget: 8 pins available (1, 2, 4, 5, 6, 7, 18, 47) against 8 demanded. Zero
slack**, exactly as §3.1 warns.

Two mappings above are load-bearing and are *not* stated in the roadmap:

- **§3.3's three aux outputs are the existing `VENT`/`AUX_A`/`AUX_B`** (14/15/16),
  not new pins. §3.1's list of "clean digital pins remaining" counts 14, 15, 16
  and 21 as free, but all four are routed on the board — and 14 and 21 are now
  driven by default as well. Read literally, §3.1 double-books the aux header.
- **The lid switch must vacate GPIO 21**, because §3.1 gives that pin to the
  alarm. It becomes one of §3.4's protected inputs.

Note that §3.1 frees six ADC1 pins and only one analog demand (§3.6) exists, so
five of them are re-spent on digital functions. They stay ADC-capable for later,
but the "frees ADC1" headline overstates the immediate win.

## 5. Aux output roles

The three aux channels in §3.3 are electrically identical (low-side driver,
flyback diode, LED, screw terminal), so which one is "the vent" is firmware
policy, not wiring. Candidate roles and what drives each:

| Role | Predicate | Cadence |
|---|---|---|
| Vent | `is_firing && temp < VENT_MAX_TEMP_C` | 1 Hz firing tick |
| Purge solenoid | designated segment / process type | 1 Hz firing tick |
| Forced cool | negative PID error during designated segments | 1 Hz firing tick |
| Zone-2 SSR | time-proportional duty | **100 ms SSR window** |

Only the vent is implemented today, in `safety.c` (`safety_update_vent()` /
`vent_write()`), and its pin and policy both live there.

Vent, purge and forced-cool are mutually exclusive in practice — a downdraft
vent exhausts the chamber while a purge floods it with inert gas, so running
both defeats the purge — which means one channel with a configurable role covers
all three. Zone-2 does **not** collapse with them: it modulates simultaneously
with the main SSR by definition, and a two-zone kiln with a downdraft vent is an
ordinary setup. It also belongs on the 100 ms window in `ssr_window_apply()`
rather than the 1 Hz tick, so it is an aux channel electrically but not
architecturally.

Reporting is a contract change whenever this lands: `ventActive` is currently a
hardcoded field in `build_status_json()`, omitted when no vent is fitted. Role
-configurable channels should report by role rather than growing a `purgeActive`
sibling — that touches `api_json.c`, both zod schemas in `web_ui/src/app/schemas/`,
both Swift models, and `make fixtures`.

## 6. Variant: I2C thermocouple front-end

If the thermocouple moves from SPI (MAX31855/MAX31856) to an I2C part
(e.g. MCP9601), channels are addressed rather than chip-selected:

| Change | Effect |
|---|---|
| TC1 CS (GPIO 10) released | +1 pin, ADC1-capable |
| TC2 CS (GPIO 2) never needed | +1 pin, ADC1-capable |
| Both channels on the §3.5 bus | 0 pins per channel, scales to 8 devices |

The §4 budget becomes **9 available against 7 demanded — 2 spare**, with seven
ADC1 pins free for a single analog demand. That retires the DNP PCA9554 GPIO
expander in §3.5 as a hedge against overrun.

Against that: I2C puts the primary safety sensor on a bus with a stuck-low
failure mode, and there is no I2C anywhere in the firmware today. The existing
5-second stale-reading trip in `safety_task()` degrades a wedged bus to a safe
emergency stop rather than a stale reading, which is the main mitigation.
