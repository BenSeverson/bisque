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

**This section originally described a proposed re-map for the first PCB run.**
That run shipped as the rev B respin
(`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md`), and several
of the assumptions below turned out wrong once the design was actually laid
out — most importantly, the module variant changed and the CT current-sense
input that motivated freeing ADC1 turned out to want a digital I2C chip, not
an analog pin. This section is rewritten to the as-built state rather than
left as a stale proposal; see §3.1 and §3.6 below for the two provisions this
affects most.

Full as-built map (every GPIO, its net, its Kconfig symbol and the J7/J10/J11
headers): [`pin-assignments.md`](pin-assignments.md).

Assigned today (Kconfig defaults, `main/Kconfig.projbuild`, rev B):

- GPIO 1–10: three protected inputs (1, 2, 4), touch CS/IRQ (5, 6), LCD BL (3),
  alarm (7), LCD CS/DC (8, 9), TC1 CS (10) — the five nav buttons that used to
  sit here moved to 38–42 in the re-map (§3.1)
- SPI bus: MOSI 11, SCLK 12, MISO 13; SSR1 17; I2C SDA 18; LCD RST 46; WS2812B 48
- SSR2 21; TC2 CS 35; watchdog kick 36; GPIO 37 spare; I2C SCL 47
- Aux terminal J10 (via the ULN2003 bank, U6): vent relay `AUX1` 14 (driven by
  default, matching the PCB), `AUX2` 15 and `AUX3` 16 (routed, declared, not
  yet driven)

**Module: ESP32-S3-WROOM-1U-N16R2**, not the WROOM-1-N16R8 earlier drafts of
this roadmap assumed. Two changes bundled into one part swap:

- **U.FL external antenna, not a PCB antenna module.** A kiln controller
  mounts on or near a large grounded steel enclosure, which makes an
  on-package PCB antenna close to non-functional; the "1U" variant carries a
  U.FL connector for an antenna on a pigtail placed somewhere that actually
  radiates. This also reclaims the ~330 mm² antenna keep-out band the
  standard WROOM-1's footprint requires, freeing it for parts and ground
  pour on a board that is already area-constrained. The trade is a
  certification one: Espressif's modular approval for the 1U is granted
  against specific antenna types and gains, so a non-approved
  high-gain antenna steps outside that approval (see the `CERT-001` note in
  `hardware/kicad/FAB-READINESS-REVIEW-REVB.md`).
- **Quad PSRAM, not octal.** This is what changes the pin budget below: octal
  PSRAM commits GPIO 35/36/37 internally, quad PSRAM releases all three.

Consequences on an ESP32-S3:

1. **ADC1 (GPIO 1–10) is mostly digital, same as before the re-map** — the
   re-map that moved the nav buttons off it (§3.1) happened for routing and
   future-interlock reasons, not to free analog input, because the CT
   current-sense provision (§3.6) turned out to want a digital I2C part with
   no analog demand at all. ADC1 is not "reclaimed" by this design; it just
   never needed reclaiming for the reason originally assumed.
2. The clean digital pins available for the re-map were **14, 15, 16, 18, 21,
   38–42, 47**, plus **GPIO 35, 36, 37**, freed by the module's **quad** PSRAM
   (not consumed the way they would be on the octal-PSRAM N16R8 this roadmap
   originally assumed) — see `pin-assignments.md` §2 for the constraint list
   as shipped.
3. All pins are Kconfig-configurable, so a PCB reshuffle is a defaults change, not a
   firmware change.

## 3. First-run PCB provisions

Goal: one board that ships as today's ceramics controller, where every Tier A/B
application (and the practical parts of Tier C) is reachable by **populating DNP parts
and flipping Kconfig defaults** — no respin. Roughly in priority order:

### 3.1 Re-map the pin assignments (shipped, rev B)

**Done, as part of the rev B respin.** This section originally proposed
moving the five nav buttons and the alarm output off GPIO 1–10 to free ADC1
for analog sensing. The re-map happened — buttons moved to 38–42 — but not
for that reason: the CT current-sense provision (§3.6) turned out to be a
digital I2C part, so there was no analog demand left to free ADC1 *for*. The
re-map survived on two different grounds instead:

1. The five nav buttons originally sat on module pads split across opposite
   sides of the ESP32-S3 module. Moving them to GPIO 38–42 puts them on
   contiguous module pads, which materially simplified routing on a board
   that turned out to have a real routing problem (`hardware/kicad/
   FAB-READINESS-REVIEW-REVB.md` records the escalation ladder that
   resulted).
2. The protected inputs (lid, gas flow, spare) landed on ADC1 pins (1, 2, 4)
   even though they're digital today, on purpose: staying ADC-capable keeps a
   resistance-monitored interlock loop — where a cut cable and a closed
   switch read differently — possible without another respin. This is the one
   genuine remaining use for ADC1 on this board.

**Full pin budget, as shipped:** `pin-assignments.md` §1 has the complete
GPIO table. Of the 30 usable GPIOs on the WROOM-1U-N16R2 (quad PSRAM frees
GPIO 35/36/37 versus an octal-PSRAM module — §2 above), **29 are assigned and
one is spare (GPIO 37)**. There is no elaborate budget-balancing exercise to
show here the way an earlier draft of this section did: the design is built,
not proposed, and `check_pinmap.py` (run via `make pcb-check`) now asserts
`design.py` and the Kconfig defaults agree on every GPIO rather than relying
on this doc staying accurate by hand.

Two decisions worth calling out because they moved from constrained to
comfortable during the design:

- **`T_IRQ` has a dedicated pin (GPIO 6).** An earlier draft of this roadmap
  assumed the touch controller would have to be polled because the pin
  budget had no room for its pen-down interrupt. Once the CT went digital
  and the module went quad-PSRAM, the budget had enough slack (one full
  spare pin, GPIO 37, plus the ADC1 pins the re-map no longer needed for
  analog sensing) to give `T_IRQ` its own line. See §3.7.
- **The DNP PCA9554 I2C GPIO expander from §3.5/§3.8 was retired.** It
  existed as the escape valve for a pin budget with zero slack; once the
  module swap left a real spare pin and the digital CT removed a demand, the
  expander stopped earning its board area. See §3.5 and §3.8.

### 3.2 Thermocouple: two channels, upgraded front-end (shipped, rev B)

- **Two TC input channels** on the shared SPI bus, each with its own CS. Rev B
  populates both channels — this was originally planned as channel 1
  populated / channel 2 DNP, but the board shipped with both MAX31856s fitted.
- **Prefer MAX31856 over MAX31855** for the PCB run: configurable TC type (K/J/N/T…),
  better cold-junction accuracy, 50/60 Hz filtering, and fault detail — directly
  serves the tighter tolerances heat treating wants. It is *not* pin-compatible with
  the MAX31855 (different package/registers), so the choice must be made at design
  time; the driver change is small and isolated to `components/thermocouple/`.
- Panel-mount miniature TC connectors; keep the cold-junction area away from board
  heat sources (SSR driver, regulators) and copper-pour it for thermal uniformity.

### 3.3 Output bank: 2 SSR zones + 3 auxiliary channels (shipped, rev B)

- **Two SSR triggers** (`SSR1_CTRL`/GPIO 17, `SSR2_CTRL`/GPIO 21), each a
  direct low-side AO3400A with an LED indicator. Roadmap §3.3 asked for
  opto-isolation and rev B built it, then reverted it: an optocoupler only
  isolates if the SSR control loop is powered off-board, and this board
  powers the loop (hardware-design spec §2.4). This grew from the single main-SSR trigger
  originally planned here to a full second zone, gated together by the
  hardware watchdog (§5.3 of the hardware-design spec).
- **Three aux channels** through a shared ULN2003ADR Darlington array (not the
  discrete MOSFET/relay-per-channel scheme originally sketched here) — flyback
  diodes integrated in the chip, LED indicators, one shared screw terminal
  (J10) fed from an externally-supplied coil rail. Firmware roles are
  soft-assigned: vent relay (implemented), purge solenoid, cooling
  fan/damper/beacon. This one bank covers the vent (already in firmware) and
  the atmosphere purge and forced-cool options without any board change; the
  second SSR zone is its own dedicated pin, not a member of this bank.
- On-board buzzer on the alarm GPIO (still present even if an aux channel drives an
  external beacon).

### 3.4 Protected digital inputs: three channels

Screw-terminal inputs with pull-ups, RC debounce, and TVS/series protection:
lid/door switch (the interlock is implemented in firmware as of PR #286 —
`components/safety/` debounces it, reports `lid_state_t`, and gates the SSR when
armed), gas-flow interlock for the purge line, one spare. Dry-contact friendly.

### 3.5 I2C expansion header (Qwiic/STEMMA-QT footprint + 0.1" header) (shipped, rev B)

One connector with on-board pull-ups unlocks a whole class of Tier B/C features with
zero board changes: SHT4x RH sensor (wood kiln), an RTC breakout for offline audit
timestamps, ADS1115 external ADC. The bus also now carries the on-board ADE7953
CT front-end (§3.6). **The DNP I2C GPIO expander footprint (e.g. PCA9554) that
this section originally specified as the escape valve for a zero-slack pin
budget was retired** — the module swap to quad PSRAM left a real spare pin
(GPIO 37) and the CT going digital removed a demand that would otherwise have
eaten into the budget, so the expander stopped earning its board area before
layout. See §3.1.

### 3.6 CT current sensing: digital I2C front-end (shipped, rev B)

**Not an analog ADC1 channel.** This section originally specified a
current-transformer input as a burden resistor + divider feeding a freed
ADC1 pin. The design that shipped instead puts both current channels on a
dedicated ADE7953 metering IC (LFCSP-28, current-only — the mains voltage
channel is unused and routed to a DNP SELV header for a possible future
off-board isolated-AC accessory) on the I2C bus from §3.5. This costs zero
GPIOs beyond the bus that already exists, keeps ESP32 ADC noise out of the
measurement entirely, and gives one channel per SSR zone instead of one
channel total. `Irms × configured nominal mains voltage` estimates power to
within roughly ±3–5%, adequate for element-health diagnosis and cost
estimation. Both channels are populated on rev B, not DNP.

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
  SCLK/MOSI/MISO and tie to the existing shared SPI2 nets — the bus now
  multi-drops the LCD at 40 MHz plus two MAX31856s and the XPT2046 at lower
  clocks, each configured per-device. `T_CS` (GPIO 5) and **`T_IRQ` (GPIO 6)
  both get dedicated pins on rev B** — an earlier draft of this section
  assumed the pin budget had no room for `T_IRQ` and left the XPT2046 polled
  by default, routing the interrupt line to the spare header instead. Once
  the CT went digital and the module went quad-PSRAM (§2), the budget had
  enough slack for a dedicated interrupt pin, so `T_IRQ` did not need the
  spare-header/solder-jumper workaround after all.
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
stored in NVS (small settings + one-time calibration modal). Kconfig:
`KILN_PIN_TOUCH_CS`/`KILN_PIN_TOUCH_IRQ` default to their rev B GPIOs (5/6) so
a board build routes them without hand-configuration, same as `KILN_PIN_AUX2`/
`KILN_PIN_AUX3` — declared and routed, but with no driver reading them yet.

### 3.8 Spare pin (shipped, rev B)

The **WROOM-1U-N16R2's quad PSRAM** frees GPIO 35, 36 and 37 versus the
octal-PSRAM WROOM-1-N16R8 an earlier draft of this roadmap assumed (GPIO
33/34 are not module pads at all on either variant; see §2). Rev B spends two
of the three — TC2 CS (35) and the hardware watchdog kick (36) — leaving
**one true spare pin, GPIO 37**, broken out but unclaimed. There is no
separate solder-jumper-isolated "spare header" concept here as originally
planned; GPIO 37 is simply the one line in the full pin map
(`pin-assignments.md` §1) with nothing on it.

**The DNP PCA9554 I2C GPIO expander this section originally described as "the
real spare-capacity story for run 1" was retired before layout** (§3.1, §3.5)
— the quad-PSRAM spare pin and the digital CT together removed the pin
pressure the expander existed to relieve. Any future slow, non-timing-critical
signal (relay coils, dry-contact interlocks, indicator LEDs) can still ride
the I2C bus via an off-board expander breakout on the Qwiic/STEMMA-QT header
(§3.5) — that option didn't disappear, only the on-board DNP footprint for it.

A mains **zero-cross detector** remains out of scope for the same reason it
always was: it needs a real interrupt-capable MCU pin, not a polled I2C
expander channel, because the signal is a narrow pulse at 100/120 Hz whose
*edge timing* is the entire payload. GPIO 37 is available for exactly this if
it's ever wanted, at the cost of the one pin of slack this board has.

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
| Touch-screen UI | 3.7 (all 14 LCD header pins routed; `T_CS`+`T_IRQ`, both dedicated GPIOs) | No |
| Wood kiln (temp+RH) | 3.5 sensor + 3.3 vent ch (+ big firmware work) | No |
| Solder reflow | none (engine timing rework only) | No |
| Below-ambient control | 3.3 can trigger a chiller relay, but bidirectional PID is out of scope | Likely yes (dedicated design) |

Bottom line: with the pin re-map (§3.1), a second TC channel (§3.2), a 3-channel aux
output bank (§3.3), three protected inputs (§3.4), an I2C header (§3.5), and the full
14-pin LCD header routed for touch (§3.7) — most of it DNP on the first run — every
application in Tiers A and B, the touch UI, and the tractable parts of Tier C fit on
the first PCB revision.
