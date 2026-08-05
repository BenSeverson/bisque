# Application Roadmap & First-Run PCB Provisions

Status: **proposal / design doc** — companion to
[`heat-treating-extension-plan.md`](heat-treating-extension-plan.md), which details the
first of these extensions (metal heat treating). This doc records the wider set of
applications the controller could serve, what hardware each one needs, and which
provisions the **first PCB run** should include so that most of them can be enabled
later with firmware + DNP'd parts instead of a board respin.

The premise: the firmware is a generic programmable thermal-process controller —
ramp/soak/cool profile executor, PID → SSR, alerts/webhooks, history/audit log —
currently packaged for ceramics. Each new application is mostly a recipe library
(the `cone_table` pattern), a `process_type` tag, and occasionally one new I/O channel.

## 1. Application catalog

### Tier A — firmware presets only, current hardware is sufficient

| Application | Typical cycle | Notes / firmware needs |
|---|---|---|
| **Metal heat treating** (anneal, temper, harden, normalize, stress-relieve) | 150–1100 °C ramp/soak/controlled-cool | Full plan in `heat-treating-extension-plan.md` (guaranteed soak, natural-cool + alert segments, gain scheduling, mode-aware vent) |
| **Glass** — annealing, fusing, slumping, casting | 480–850 °C, precise anneal soaks, very controlled cools | Same engine features as heat treat; `PROCESS_GLASS`; guaranteed soak is even more valuable here |
| **Lost-wax investment burnout** | Multi-hold ladder ~150/370/730 °C, drop to casting temp | Vent relay genuinely useful (wax fumes); alert-on-segment = "flask ready, cast now" |
| **Precious metal clay (PMC) sintering** | 650–900 °C ramp + hold | Presets only |
| **Vitreous enameling** | 750–850 °C short holds | Presets only |
| **Composite / epoxy post-cure** | 60–180 °C soak ladders per resin datasheet | Low-temp gain scheduling (already planned) |
| **3D-print part annealing & filament drying** | 60–120 °C long holds | Presets only |
| **Powder coat curing** | 180–200 °C, 10–20 min *from part at temp* | Much better with load thermocouple (Tier B) but usable without |
| **Crucible melting** (Al, bronze) for casting | Hold at melt temp indefinitely, alarm when ready | `FIRING_HOLD_INDEFINITE` + alert; already expressible |
| **Wax melting / mold & core drying** | Low-temp holds | Presets only |
| **Lab drying / dry-heat sterilization** | 160–180 °C fixed soaks | History component already provides the audit trail; add a "simple setpoint mode" UI (one-segment profile under the hood) |
| **Acrylic / thermoplastic slumping & forming** | ~120–180 °C holds | Presets only |

### Tier B — firmware + one added I/O channel

| Application | Extra hardware | Firmware work |
|---|---|---|
| **Load-temperature-gated processes** (thick-section heat treat, powder coat cure) | 2nd thermocouple input (own CS on shared SPI) | Multi-channel `thermocouple` driver; per-profile control source (air TC drives PID, load TC gates soak) |
| **Controlled-atmosphere heat treat** (reduce scale/decarb) | Purge solenoid on an aux output; optional gas-flow switch input | Aux-output policy per process type; interlock input |
| **Two-zone kilns / larger chambers** | 2nd SSR channel + 2nd TC | Second PID instance or master/slave offset control |
| **Forced-cool / crash-cool assist** (glass fuse-to-anneal transitions, chamber turnaround) | Aux output driving a cooling fan or damper | "Cool output" active on negative-error during designated segments |
| **Element / heater health monitoring** | Current transformer (CT clamp) sense input | Compare expected vs. actual current at known duty; distinguishes failed element from thermal stall (`FIRING_ERR_NOT_RISING` becomes diagnosable); verifies `element_watts` for cost estimates |
| **Offline-accurate audit timestamps** | I2C RTC (DS3231) + coin cell | History timestamps valid without NTP; useful for lab/sterilization use |

### Tier C — real scope changes (record for completeness, not near-term)

| Application | Why it's harder |
|---|---|
| **Wood-drying kiln** | Needs relative-humidity sensing (I2C SHT4x — covered by the expansion header below) and *two-dimensional* schedules (temp + RH targets, vent as a controlled output). Week-long runs are fine (time accumulators are 64-bit µs). |
| **Solder reflow** | Data-model mismatch: holds are stored in minutes, profiles need seconds resolution and a faster control cadence than the 1 Hz tick. No new hardware, but touches the engine's core timing. |
| **Below-ambient control** (environmental chambers, incubators below room temp) | Requires an active cooling stage and bidirectional PID — a genuinely different controller. An aux output can drive a fan/compressor relay, but this is out of scope beyond that. |
| **Pressure processes** (autoclave) | Out of scope entirely. |

## 2. Current pin budget (why the PCB provisions look the way they do)

Assigned today (Kconfig defaults, `main/Kconfig.projbuild`):

- **GPIO 1–10 all consumed**: buttons (1, 2, 4, 5, 6), LCD BL (3), alarm (7), LCD CS/DC (8, 9), TC CS (10)
- SPI bus: MOSI 11, SCLK 12, MISO 13; SSR 17; LCD RST 46; WS2812B 48
- Firmware-supported but unassigned (`-1`): vent relay, lid switch

Consequences on an ESP32-S3:

1. **ADC1 (GPIO 1–10) is fully occupied** by digital functions, and ADC2 (GPIO 11–20)
   is unreliable while Wi-Fi is active. As wired today, there is effectively **no
   usable analog input** — this is the single most important thing to fix in the PCB
   pin map (see §3.1) if CT current sensing or any analog sensor is ever wanted.
2. Plenty of clean digital pins remain: **14, 15, 16, 18, 21, 38–42, 47** — enough for
   the button re-map (§3.1), touch `T_CS`/`T_IRQ` (§3.7), and spares (avoid
   strapping pins 0/45, and keep 19/20 for USB; 46 is a strapping pin already spent on
   LCD RST). GPIO 33–37 depend on the module variant — reserved by octal PSRAM on
   R8 modules, free on quad-PSRAM/flash-only variants; treat them as
   module-dependent spares.
3. All pins are Kconfig-configurable, so a PCB reshuffle is a defaults change, not a
   firmware change.

## 3. First-run PCB provisions

Goal: one board that ships as today's ceramics controller, where every Tier A/B
application (and the practical parts of Tier C) is reachable by **populating DNP parts
and flipping Kconfig defaults** — no respin. Roughly in priority order:

### 3.1 Re-map the pin assignments to free ADC1 (zero cost, must happen at layout time)

Move the five nav buttons and the alarm output off GPIO 1–10 onto the free digital
pins (e.g. buttons → 38–42, alarm → 21), keeping GPIO 1–10 available as ADC1
channels for analog sensing. This costs nothing on the first run and is impossible to
fix later without a respin. Update the Kconfig defaults to match the board.

### 3.2 Thermocouple: two channels, upgraded front-end

- **Two TC input channels** on the shared SPI bus, each with its own CS. Populate
  channel 1; channel 2 is DNP.
- **Prefer MAX31856 over MAX31855** for the PCB run: configurable TC type (K/J/N/T…),
  better cold-junction accuracy, 50/60 Hz filtering, and fault detail — directly
  serves the tighter tolerances heat treating wants. It is *not* pin-compatible with
  the MAX31855 (different package/registers), so the choice must be made at design
  time; the driver change is small and isolated to `components/thermocouple/`.
- Panel-mount miniature TC connectors; keep the cold-junction area away from board
  heat sources (SSR driver, regulators) and copper-pour it for thermal uniformity.

### 3.3 Output bank: 1 main + 3 auxiliary channels

- **Main SSR trigger** (existing GPIO 17 function): opto-isolated, LED indicator.
- **Three aux low-side driver channels** (MOSFET or small relay, flyback diodes,
  LED indicators, screw terminals). Firmware roles are soft-assigned: vent relay,
  purge solenoid, cooling fan/damper, zone-2 SSR trigger, external alarm/beacon.
  This one bank covers the vent (already in firmware), the atmosphere purge,
  forced-cool, and two-zone options without any board change.
- On-board buzzer on the alarm GPIO (still present even if an aux channel drives an
  external beacon).

### 3.4 Protected digital inputs: three channels

Screw-terminal inputs with pull-ups, RC debounce, and TVS/series protection:
lid/door switch (`APP_PIN_LID_SWITCH` already in firmware), gas-flow interlock for
the purge line, one spare. Dry-contact friendly.

### 3.5 I2C expansion header (Qwiic/STEMMA-QT footprint + 0.1" header)

One connector with on-board pull-ups unlocks a whole class of Tier B/C features with
zero board changes: SHT4x RH sensor (wood kiln), DS3231 RTC + coin-cell footprint
(offline audit timestamps — put the RTC + battery holder on-board as DNP),
ADS1115 external ADC (fallback analog path), GPIO expanders if channels ever run out.

### 3.6 Analog sense: CT-clamp input (DNP)

One current-transformer input (burden resistor + divider + clamp diodes) into a freed
ADC1 pin, footprints only on run 1. Enables element-health monitoring and real power
measurement. If §3.1's re-map is somehow not possible, this moves to the I2C ADC.

### 3.7 Touch-screen enablement on the LCD header

The 3.5" ST7796S module family uses the standard LCDWIKI-style **14-pin header**, of
which today's wiring only uses the 9 display pins. The remaining **5 pins are the touch
panel**: `T_CLK`, `T_CS`, `T_DIN`, `T_DO`, `T_IRQ` — the on-module resistive touch
controller (XPT2046) with its own SPI interface plus a pen-down interrupt
(confirmed against the MSP3520 user manual pin table; touch pins may be left
unconnected when unused, which is exactly today's situation).

Provision for run 1:

- **Route all 14 header pins.** The five touch lines cost only **two new ESP32
  GPIOs**, not five: `T_CLK`/`T_DIN`/`T_DO` are electrically just SPI
  SCLK/MOSI/MISO and tie to the existing shared SPI2 nets (GPIO 12/11/13 — the bus
  already multi-drops the LCD at 40 MHz and the MAX31855 at 1 MHz with per-device
  clocks; the XPT2046 joins as a third device at ≤2.5 MHz). Only `T_CS` and
  `T_IRQ` need fresh GPIOs from the free pool (e.g. 14, 15). `T_IRQ` is technically
  optional (the chip can be polled) but is nearly free and lets firmware skip
  touch reads until a press occurs — wire it.
- **Series resistor / solder-jumper on the touch lines** so an untouched build (or a
  touchless module variant) is unaffected.
- **Capacitive variant escape hatch:** some ST7796S modules ship with capacitive
  touch (FT6336U/GT911) on **I2C + INT** instead of the XPT2046. That variant is
  already covered by the §3.5 I2C header plus one spare input — no extra layout work.

Firmware (when enabled): an XPT2046 driver on the shared bus, registered as an LVGL
**pointer indev** alongside the existing encoder/group input — LVGL v9 supports both
simultaneously, and the whole UI is already built from clickable widgets
(buttons, list rows, button matrices), so modals become directly tappable with the
5-way switch untouched as a fallback. Resistive touch needs a 4-point calibration
stored in NVS (small settings + one-time calibration modal). Kconfig: two new pin
options defaulting to `-1` (disabled), same pattern as vent/lid-switch.

### 3.8 Spare-pin header & strategy

Route every remaining safe GPIO (from §2's free list) to a labeled 0.1" header with
solder-jumper isolation. Do not spend strapping pins (0, 45) or USB pins (19, 20) on
new functions. Optional DNP footprint: a mains **zero-cross detector** into one spare
input — only relevant if finer-than-time-proportional SSR control is ever wanted for
very low-temperature stability; cheap insurance.

### 3.9 Power & safety envelope

- Size the 5 V rail (or provide separate supply terminals) for solenoid/relay coil
  loads on the aux bank; flyback protection on every inductive channel.
- Keep all mains switching off-board (external SSRs); the board carries only
  isolated trigger signals. Maintain creepage/isolation for the TC inputs (they may
  contact grounded sheaths).
- Separate quiet analog region (TC front-ends, CT input) from the switching/driver
  region.

## 4. What run-1 provisioning buys, by application

| Application | Needs from §3 | Board change needed later? |
|---|---|---|
| All Tier A (glass, burnout, PMC, enamel, cure, drying, melting…) | nothing (firmware only) | No |
| Load-TC gating (heat treat, powder coat) | 3.2 ch-2 populated | No |
| Atmosphere purge | 3.3 aux ch + 3.4 flow input | No |
| Two-zone | 3.2 ch-2 + 3.3 aux ch as SSR-2 | No |
| Forced-cool assist | 3.3 aux ch | No |
| Element health / power metering | 3.1 + 3.6 populated | No |
| Audit-grade timestamps | 3.5 RTC populated | No |
| Touch-screen UI | 3.7 (all 14 LCD header pins routed; 2 GPIOs) | No |
| Wood kiln (temp+RH) | 3.5 sensor + 3.3 vent ch (+ big firmware work) | No |
| Solder reflow | none (engine timing rework only) | No |
| Below-ambient control | 3.3 can trigger a chiller relay, but bidirectional PID is out of scope | Likely yes (dedicated design) |

Bottom line: with the pin re-map (§3.1), a second TC channel (§3.2), a 3-channel aux
output bank (§3.3), three protected inputs (§3.4), an I2C header (§3.5), and the full
14-pin LCD header routed for touch (§3.7) — most of it DNP on the first run — every
application in Tiers A and B, the touch UI, and the tractable parts of Tier C fit on
the first PCB revision.
