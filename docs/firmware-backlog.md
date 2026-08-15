# Firmware Backlog — Rev B Parity and Roadmap

Status: **task inventory**, built 2026-08-15 from `main/Kconfig.projbuild`,
[`pin-assignments.md`](pin-assignments.md) §5,
[`application-roadmap-and-pcb-provisions.md`](application-roadmap-and-pcb-provisions.md)
and [`heat-treating-extension-plan.md`](heat-treating-extension-plan.md).

Two parts:

- **Part 1 — Rev B parity.** The board exists and the firmware does not use it.
  Every item here is hardware that is *routed, populated and declared in
  Kconfig*, with nothing driving it.
- **Part 2 — Roadmap.** Application features. Most Tier B items are gated on a
  Part 1 task, and the dependency column says which.

Nothing here is scheduled. Ordering within Part 1 is by what blocks bring-up.

---

## Part 1 — Bring firmware in line with rev B hardware

### Blocking: the board does not work without these

| ID | Task | GPIO | Why it blocks |
|---|---|---|---|
| **RB-1** | **MAX31856 driver**, replacing the MAX31855 one | TC1_CS 10 | The board reads **no temperature at all**. The MAX31855 driver does one read-only 32-bit frame; the MAX31856 needs config-register writes on init and a fault-register decode. |
| **RB-2** | **Watchdog kick task** | WDT_KICK 36 | A charge pump gates **both** SSR channels. Until something toggles it, every board needs the SJ2 "WDT DEFEAT" jumper fitted or **it will not heat**. |

**RB-1 notes.** A straight replacement, not a second backend — the runtime-probe
requirement died with the rev A freeze. Host tests stub the driver
(`tests/host/stubs/thermocouple_host.c`) and the simulator mocks ESP-IDF, so the
swap doesn't reach either suite. Revisit `APP_PID_KD_DEFAULT` on the bench while
here: its value was chosen against the MAX31855's 0.25 °C quantization, and the
MAX31856 is ~32× finer.

**RB-2 notes.** The pump needs *transitions* — a pin stuck high fails exactly
like a pin that stopped, which is the whole design. The kick must **stop** on a
safety fault; a kicker that runs from a timer regardless of system health is
worse than no watchdog, because it silently defeats the hardware interlock.
Decide explicitly where the kick lives relative to `safety_task`.

### Second channel and second zone

| ID | Task | GPIO | Depends on |
|---|---|---|---|
| **RB-3** | **Multi-channel thermocouple API** — indexed accessor or (better) an atomic multi-channel snapshot, keeping a single-channel wrapper so existing call sites and the host harness are unchanged | — | RB-1 |
| **RB-4** | **Second thermocouple** wired through RB-3 | TC2_CS 35 | RB-3 |
| **RB-5** | **SSR zone 2** — second PID instance or master/slave offset | SSR2 21 | RB-1 |

**RB-3 is the API break.** Today the component is single-sensor top to bottom:
`thermocouple_init(host, cs_pin)` takes one CS and `thermocouple_get_latest()`
returns one cached reading behind one spinlock. Keeping that signature leaves the
firing engine and safety task able to see only the primary probe, which defeats
control-source selection and load-gating *by construction*. Prefer the atomic
snapshot so a tick cannot mix a fresh air reading with a stale load reading.

**RB-5 cadence.** Zone 2 modulates on the **100 ms SSR window**, not the 1 Hz
firing tick, because it tracks the main SSR's duty simultaneously by definition.

### Outputs and inputs

| ID | Task | GPIO | Notes |
|---|---|---|---|
| **RB-6** | **Aux output bank** — AUX2/AUX3 through the ULN2003 (U6), driven by *role* rather than hardcoded | 15, 16 | Vent (AUX1) is the only one implemented, in `safety.c`. Electrically the three channels are identical, so role assignment is firmware policy. |
| **RB-7** | **Gas-flow interlock input** | IN2 2 | Same conditioning and fail-safe polarity as the lid switch: open contact reads HIGH, so a broken wire reads "no flow". Prerequisite for the purge relay (RM-B2). |
| **RB-8** | **Spare protected input** | IN3 1 | Unassigned. Do last, or drop it — there is no consumer. |

**RB-6 is a contract change, not just a driver.** `ventActive` is currently a
hardcoded field in `build_status_json()`, omitted when no vent is fitted. Report
by **role** rather than growing a `purgeActive` sibling; that touches
`api_json.c`, both zod schemas in `web_ui/src/app/schemas/`, both Swift models,
and `make fixtures`.

### I2C and touch

| ID | Task | GPIO | Notes |
|---|---|---|---|
| **RB-9** | **I2C bus driver** | SDA 18, SCL 47 | Nothing exists yet. Carries the on-board ADE7953 *and* the Qwiic/STEMMA-QT expansion header, so this unlocks RB-10, RM-B5 and RM-B6 together. |
| **RB-10** | **ADE7953 current metering** | (I2C) | RB-9. Unlocks element-health monitoring and verifies `element_watts` for cost estimates. |
| **RB-11** | **XPT2046 touch driver** + LVGL input device | T_CS 5, T_IRQ 6 | The controller is on the LCD module, not the Bisque PCB; clock/data are the shared SPI bus. IRQ lets you skip polling. **Interaction risk:** the display UI is built entirely around the 5-way encoder model (focus/activate, Cancel buttons rather than a back gesture). Touch is not a drop-in — decide whether it supplements or replaces that model before writing the driver. |

### Housekeeping

| ID | Task | Notes |
|---|---|---|
| **RB-12** | Update the LCD SPI frequency rationale, or re-measure it | `APP_LCD_SPI_FREQ_HZ` is 40 MHz against a 66 MHz datasheet limit; the margin was sized for hand-soldered perfboard wiring and has never been measured on the routed board with a keyed loom. |
| **RB-13** | Wire the third `.gbrjob`/stack-up consumer checks into `make pcb-check`'s CI subset if KiCad ever lands in CI | Today CI runs 7 of 12 checkers. Netlist round-trip, CPL placement, silk, via-in-pad and courtyard overlap are local-only. |

---

## Part 2 — Roadmap

### Phase 1 — Domain packaging (low risk, append-only)

| ID | Task | Depends on |
|---|---|---|
| **RM-1** | `process_type` + `schema_version` on `firing_profile_t`, end-to-end, with load-path zero-fill | — |
| **RM-2** | `heat_treat_table` component + presets | RM-1 |
| **RM-3** | Mode-aware vent — `PROCESS_HEAT_TREAT` keeps the vent closed by default instead of the ceramic 700 °C rule | RM-1 |
| **RM-4** | Web UI: process-type badge, filter, wizard | RM-1 |

### Phase 2 — Engine precision (medium risk; touches `firing_tick`, fully host-testable)

| ID | Task | Notes |
|---|---|---|
| **RM-5** | Segment-padding migration | Data-model change; do before the rest of Phase 2 |
| **RM-6** | **Guaranteed soak** | The key metallurgy feature — soak clock freezes when out of band |
| **RM-7** | Natural-cool segments | Completes on threshold rather than on a ramp |
| **RM-8** | Operator-action alerts + `FIRING_EVENT_SEGMENT_ALERT` | "Flask ready, cast now" |
| **RM-9** | Gain scheduling + banded autotune | Control quality at tempering temperatures |
| **RM-10** | Segment-relative not-rising check | Current check is absolute |
| **RM-11** | ProfileBuilder fields for all of the above | Web UI |
| **RM-12** | Simulator lag model | Makes the host firing scenarios represent thermal mass honestly |

### Phase 3 — Hardware-dependent applications (Tier B)

Each of these is a real application unlocked by a Part 1 task.

| ID | Application | Needs | Firmware work |
|---|---|---|---|
| **RM-B1** | **Load-temperature-gated processes** (thick-section heat treat, powder coat cure) | RB-3, RB-4 | Per-profile `control_source`: air TC drives PID, load TC gates soak. Plus gating-sensor fault routing. |
| **RM-B2** | **Controlled-atmosphere heat treat** (reduce scale/decarb) | RB-6, RB-7 | Purge solenoid on AUX2, gas-flow interlock, aux policy per process type |
| **RM-B3** | **Two-zone kilns / larger chambers** | RB-4, RB-5 | Second PID instance or master/slave offset control |
| **RM-B4** | **Forced-cool / crash-cool assist** (glass fuse-to-anneal) | RB-6 | "Cool output" active on negative error during designated segments |
| **RM-B5** | **Element health monitoring** | RB-9, RB-10 | Compare expected vs. actual current at known duty. Makes `FIRING_ERR_NOT_RISING` *diagnosable* — distinguishes a failed element from a thermal stall. |
| **RM-B6** | **Offline-accurate audit timestamps** | RB-9 | I2C RTC (DS3231) + coin cell on the Qwiic header; history timestamps valid without NTP |
| **RM-B7** | **Quench transfer-window policy** | RM-6 | Gate stays armed across the transfer |
| **RM-B8** | **Two-point TC calibration** | RB-1 | Current calibration is a single offset |

### Tier A — presets only, no new hardware or engine work

Glass (anneal/fuse/slump/cast), lost-wax burnout, PMC sintering, vitreous
enameling, composite post-cure, print annealing and filament drying, powder coat,
crucible melting, wax/mold drying, lab drying and dry-heat sterilization,
thermoplastic forming. These are **profile presets plus a process-type label** —
they fall out of RM-1 and RM-2 rather than needing their own tasks. Lab drying
additionally wants a "simple setpoint mode" UI (a one-segment profile
underneath).

### Tier C — recorded, not near-term

| Application | Why it's harder |
|---|---|
| Wood-drying kiln | Needs RH sensing (I2C SHT4x — RB-9 covers the bus) and *two-dimensional* schedules: temp + RH targets with the vent as a controlled output |
| Solder reflow | Data-model mismatch — holds are stored in minutes, this needs seconds and a faster cadence than the 1 Hz tick. No new hardware, but it touches the engine's core timing. |
| Below-ambient control | Needs an active cooling stage and bidirectional PID: a genuinely different controller |
| Pressure processes (autoclave) | Out of scope entirely |

---

## Suggested order

1. **RB-1, RB-2** — nothing else can be tested on real hardware until the board
   reads temperature and is allowed to heat. Both are written blind until
   bring-up; budget bench time.
2. **RM-1 → RM-4** — Phase 1 is low-risk, append-only, and needs no hardware, so
   it can proceed in parallel with the wait for boards.
3. **RB-3** — the API break. Doing it before more callers accumulate is cheaper
   than after.
4. **RM-5 → RM-12** — Phase 2 is fully covered by host tests and `plant.c`, so it
   also does not need hardware.
5. Everything else by which application you want first; the dependency columns
   above say what each one costs.
