# Lid/door switch interlock — design

Resolves [#83](https://github.com/BenSeverson/bisque/issues/83): `APP_PIN_LID_SWITCH`
is defined but referenced nowhere in the firmware.

## Problem

`CONFIG_KILN_PIN_LID_SWITCH` exists, defaults to `-1`, and is exposed as
`APP_PIN_LID_SWITCH` in `components/app_config/include/app_config.h`. Nothing
reads it. The Kconfig help promises "a warning is triggered", which is not true
of any code path. The board already breaks the net out (`LID_SW`, ESP32 GPIO21 →
aux header J7 pin 6), so owners can fit a switch and get nothing.

The issue offers two ways out: wire it in, or delete it. This spec wires it in.

## Scope decision: two markets, one mechanism

Ceramic kilns and heat-treat / knife ovens want different things from a lid
switch, and the project intends to serve both.

**Heat-treat ovens** (Evenheat KF/LB, Paragon KM, Jen-Ken): opening the door at
full temperature *is* the normal workflow — a blade is pulled at 1500–1900 °F
and quenched. The door switch there is an element cutoff, not a program
interrupt: elements de-energize while the door is open, the controller keeps
running its program, and closing the door restores heat. Anything that aborted
or froze the program would make the oven unusable for its main job.

**Ceramic kilns**: opening the lid mid-firing is abnormal (thermal shock to
ware, glaze defects). The useful response is closer to a pause — cut elements
*and* hold the program clock, so the segment does not run ahead while the kiln
sheds heat.

The mechanism is identical in both cases (debounced read → "lid open" → cut the
SSR). Only the **program-clock policy** differs. That is a single axis, so it
becomes a runtime setting rather than a fork.

### Not a safety device

A GPIO interlock in the controller is a supplementary layer. The real protection
on these ovens is a mechanical microswitch wired in series with the element
contactor, which works with the firmware halted, crashed, or unpowered. This
must be stated in the Kconfig help and in the user-facing docs; the feature must
not imply it replaces that switch.

## Architecture

Responsibility splits along the existing component boundary:

- **`components/safety`** owns the *pin*: configuration, polarity, debounced
  sampling, and a hard SSR gate. It does not know about modes.
- **`components/firing_engine`** owns the *policy*: it reads the mode from
  `kiln_settings_t` and decides what an open lid means for firing status and the
  program clock.

This keeps the fast, authoritative cut next to the other SSR gates
(`safety_is_emergency()`, `!s_supervised`) and keeps a user-facing setting out
of the driver. It mirrors how the vent relay (#184/#281) is layered.

## Components

### 1. Configuration

`main/Kconfig.projbuild`:

- `KILN_PIN_LID_SWITCH` — unchanged, default `-1` (not fitted). Help text
  rewritten to describe actual behaviour, to name GPIO 21 / aux header J7 pin 6
  as the board's lid pin, and to state that this is not a substitute for a
  mechanical interlock in the element circuit.
- **New** `KILN_LID_SWITCH_ACTIVE_HIGH`, bool, default `n`. Default assumes
  normally-closed wiring with the internal pull-up enabled: lid shut = contact
  closed = input low. A broken wire, a pulled connector, or an unfitted switch
  therefore reads **open** and fails safe. `y` inverts for people who already
  have a normally-open switch.

### 2. Shared state type

New `components/safety/include/lid_state.h`, mirroring `vent_state.h` — no
`esp_err.h`, no FreeRTOS, so the pure JSON builders in `api_json.c`, the LVGL
dashboard (compiled by the SDL simulator with no ESP-IDF at all), and `safety.c`
can share one type:

```c
typedef enum {
    LID_STATE_NOT_FITTED = -1,
    LID_STATE_CLOSED = 0,
    LID_STATE_OPEN = 1,
} lid_state_t;
```

`NOT_FITTED` is distinct from `CLOSED` for the same reason `VENT_STATE_NOT_FITTED`
is distinct from `OFF`: the pin defaults to `-1`, so most kilns have no switch,
and an indicator permanently reading "lid closed" would be reporting on hardware
that is not there. Consumers omit the reading entirely in that case.

Added to `tests/host/fixture_sources.txt` so a change to it invalidates the
fixture manifest.

### 3. Mode setting

In `components/firing_engine/include/firing_types.h`, beside `kiln_settings_t`:

```c
typedef enum {
    LID_MODE_WARN = 0,
    LID_MODE_PAUSE,
    LID_MODE_INTERLOCK,
} lid_mode_t;
```

`kiln_settings_t` gains `lid_mode_t lid_mode;`. Default `LID_MODE_PAUSE`, set
explicitly alongside the other defaults in `firing_engine.c` (~line 189, before
the NVS overrides) and persisted under a new NVS key `lid_mode`. The ceramic
default is chosen because it is the project's primary market; a heat-treat owner
changes one setting.

### 4. Sampling and debounce (safety)

`safety_init_io()` gains a third parameter for the lid GPIO, configured as an
input with the internal pull-up enabled. Polarity comes from
`CONFIG_KILN_LID_SWITCH_ACTIVE_HIGH`.

Sampled in `safety_task` at its existing 500 ms cadence, with **asymmetric
debounce**:

- **Open is believed on the first sample.** Cutting heat is cheap.
- **Closed requires two consecutive samples (~1 s).** Restoring heat should be
  deliberate.

The asymmetry both fails safe and stops a bouncing or marginal switch from
chattering the SSR.

`lid_state_t safety_get_lid_state(void)` reports the debounced state, or
`LID_STATE_NOT_FITTED` when no GPIO is configured. As with
`safety_get_vent_state()`, this reports the *sampled pin*, not a re-derivation.

### 5. SSR gate (safety)

`void safety_set_lid_interlock_armed(bool armed)` — called by `firing_engine`
whenever settings load or change, with `armed = (lid_mode != LID_MODE_WARN)`.

`ssr_window_apply()` gains the lid to its existing guard:

```c
if (safety_is_emergency() || !s_supervised || lid_blocks_output()) {
    gpio_set_level(s_ssr_pin, 0);
    return;
}
```

where `lid_blocks_output()` is `s_lid_interlock_armed && s_lid_state == LID_STATE_OPEN`.

Because that guard runs on the 100 ms window timer, the element is cut within
~600 ms of the lid opening (500 ms sample + 100 ms window), and it stays cut even
if the firing task wedges — the same property the emergency-stop gate has. The
firing engine's own `safety_set_ssr(0.0f)` calls below are then bookkeeping, not
the safety mechanism.

### 6. Policy (firing engine)

`firing_tick()` reads `safety_get_lid_state()` once per tick and applies the
configured mode. `s_state` gains a `bool lid_paused` flag.

**`LID_MODE_WARN`** — no control action. The state is reported and nothing else.

**`LID_MODE_PAUSE`** — on the transition to open, while a firing is active and
not already paused: record `pause_prev_status`, set `status = FIRING_STATUS_PAUSED`,
`safety_set_ssr(0.0f)`, stamp `pause_start_us`, and set `lid_paused = true`. On
the transition to closed, *only if `lid_paused`*: restore `pause_prev_status` and
shift `segment_start_time_us`, `check_start_time_us`, and (when holding)
`segment_hold_start_time_s` forward by the paused duration — exactly what
`FIRING_CMD_RESUME` does — then clear `lid_paused`.

The `lid_paused` flag is load-bearing: closing the lid must **not** resume a
firing that the operator paused by hand. Conversely, an explicit `FIRING_CMD_RESUME`
while the lid is still open must not re-energize the element — the safety gate
holds it off regardless, but the engine should also clear `lid_paused` so the
lid-close handler does not later fight the operator.

**`LID_MODE_INTERLOCK`** — on open: `safety_set_ssr(0.0f)` and skip the PID
update for that tick. Status stays `HEATING`/`HOLDING`, `elapsed_accum_us` keeps
accumulating, and no segment clocks shift. The program runs on; only the heat
stops. The lid indicator is what tells the operator.

Both acting modes must leave the not-rising and runaway watchdogs coherent. In
`pause` mode the existing resume-shift handles it. In `interlock` mode the
program clock deliberately keeps running, so `check_start_time_us` must be reset
on lid close to avoid a false `FIRING_ERR_NOT_RISING` — an open door for ten
minutes is a real stall by the watchdog's measure, but not a fault.

### 7. Start gate

Starting a firing with the lid open, in `pause` or `interlock` mode, is refused:

- `POST /firing/start` in `components/web_server/api_handlers.c` returns `409`
  with the bare body `"Lid is open"` — matching the project's error contract
  (no JSON envelope; `services/api.ts` reads `res.text()` on non-2xx).
- The same refusal lives in the engine's `FIRING_CMD_START` handler so the LCD
  start path behaves identically, logged like the existing `delay_active`
  refusals.

`warn` mode does not block the start; blocking would make the name a lie.

Rationale: a firing that starts and immediately sits at zero power is hard to
diagnose from the dashboard. An error at the moment of the click is not.

### 8. Reporting

Follows `ventActive` precisely. Every payload goes through a `build_*_json()` in
`api_json.c` — no inline `cJSON_Add*` at the handler — so it stays
fixture-dumpable and visible to the contract tests.

| Surface | Change |
|---|---|
| `build_status_json()` | new `lidOpen` (bool), **omitted entirely** when `LID_STATE_NOT_FITTED`; takes a `lid_state_t` parameter |
| `build_ws_temp_update_json()` | same field, same omission, same parameter |
| `build_settings_json()` | new `lidMode` (`"warn"`/`"pause"`/`"interlock"`), **always present** — it is a setting, not a hardware reading |
| `PUT /settings` | parses and validates `lidMode`; unknown value → 400 |
| `web_ui/src/app/schemas/api.ts`, `ws.ts` | `lidOpen: z.boolean().optional()`, `lidMode` enum |
| `web_ui/src/app/types/kiln.ts`, `stores/kilnStore.ts` | `lidOpen: boolean \| null` |
| `web_ui/src/app/components/FiringDashboard.tsx` | lid badge beside the existing vent badge, rendered only when `lidOpen !== null` |
| Settings UI | mode selector, with copy explaining the ceramic/heat-treat split |
| `web_ui/mock-server/simulator.ts` | emits `lidOpen`, with a way to toggle it for UI work |
| iOS `Codable` models | `lidOpen`, `lidMode` |
| `components/display/dashboard.c` | "LID" badge in the status bar next to VENT; `dashboard_update()` takes a `lid_state_t` |
| `components/display/display_task.c`, `simulator/main.c` | pass `safety_get_lid_state()` / a simulated value |

Schemas stay non-`.strict()` for the app-facing path so a newer kiln still parses
in an older tab; the contract test rebuilds them `.strict()` to catch unmodelled
firmware fields.

## Error handling

- **Not fitted** (`pin == -1`) is the default and is not an error. The reading is
  omitted from JSON, the LCD badge never appears, and the SSR gate never arms.
- **Broken wire / unplugged switch** reads open under the default NC polarity,
  which cuts heat and (in `pause` mode) pauses the firing. This is the intended
  failure direction, and the operator sees the lid indicator explaining it.
- **Bouncing switch** is absorbed by the asymmetric debounce; worst case is a
  1 s delay restoring heat.
- **Lid open at start** is a `409`, not a silent zero-power firing.
- **Lid opened during an emergency stop** changes nothing — the emergency gate
  already holds the SSR low and latches first-cause.

## Testing

**Host (`tests/host/`)**
- `stubs/safety_host.c` / `safety_host.h` gain lid state, `safety_test_set_lid()`,
  and mirror the real driver's arm/gate behaviour — the same way the vent stub
  mirrors the 700 °C rule.
- `test_api_json.c`: `lidOpen` present when fitted, omitted when not; `lidMode`
  always present; WS frame and `/status` agree (extend `assert_ws_and_status_agree`);
  new fixtures for the lid-open and no-lid cases.
- `test_firing_scenarios.c`: `warn` takes no action; `pause` auto-pauses on open
  and auto-resumes on close with clocks shifted; `interlock` cuts power without
  changing status and without shifting the clock; a lid close does **not** resume
  an operator-initiated pause; `check_start_time_us` reset prevents a false
  NOT_RISING after a long interlock hold; start is refused while open.
- `fixture_sources.txt` += `components/safety/include/lid_state.h`.

**Web (`make test-web`)**
- Schema round-trip against the new fixtures; `kilnStore` maps `lidOpen` and
  nulls it when absent (mirroring the existing `ventActive` tests); a
  `FiringDashboard` component test for the badge; a Settings test for the mode
  selector.

**iOS (`make test-ios`)**
- `FirmwareContractTests`: new fixtures land in `decoded`; `lidOpen`/`lidMode` are
  modelled or explicitly listed in `knownUnmodelled`.

**Simulator (`make sim-verify`, `make sim`)**
- A `--verify` assertion that the LID badge appears and clears across a
  lid-open → lid-close sequence — this is exactly the "state surviving a
  transition" case that pixel diffing misses. Plus a regenerated screenshot
  baseline for the badge's appearance.

**Firmware build**: `make firmware` (via `scripts/idf-env.sh`). `tests/host/`
links only a subset of components, so `api_handlers.c`, `ws_handler.c` and
`main/` changes are otherwise uncompiled by `make test`.

## Out of scope

- PCB input conditioning (external pull-up, RC filter, ESD clamp) on the
  `LID_SW` net, and the `docs/*.svg` wiring diagrams. The connectivity already
  exists on the board; hardening it is tracked separately.
- Any change to the mechanical interlock story. This feature supplements a
  microswitch in the element circuit; it does not replace one.
