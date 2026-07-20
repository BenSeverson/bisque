# Extension Plan: Metal Heat Treating & Annealing Support

Status: **proposal / design doc** — no implementation yet.

## 1. Summary

Bisque's firing engine is already a generic multi-segment **ramp → soak → controlled-cool**
executor (`components/firing_engine/`): segments carry a signed ramp rate, a target
temperature, and a hold time, and the PID/SSR loop doesn't know or care that the load is
ceramic. Metal heat treating (annealing, stress relief, tempering, hardening soaks,
normalizing — and, as a bonus, glass annealing) uses the exact same primitive, so this is
an **extension, not a rewrite**.

What metals actually add beyond ceramics:

| Need | Ceramics today | Metals requirement |
|---|---|---|
| Soak accuracy | Hold timer starts at target, keeps counting regardless of drift | **Guaranteed soak**: hold clock should only accumulate while temp is inside a tolerance band (±3–10 °C typical; tool-steel tempering wants tight bands) |
| Low-temp control | PID tuned once, typically for 1000 °C+ operation | Tempering runs at 150–650 °C where the plant gain is very different → **gain scheduling / multi-point autotune** |
| Cooling semantics | Negative ramp = elements assist a slow cool | Also need **"natural cool" (SSR off, wait for temp X)** and **operator-action steps** (e.g. "remove part and quench now") |
| Vent behavior | Vent relay active when firing < 700 °C (water smoke/organics) | Venting during a metals soak wastes heat and increases scale → vent policy must be **per process mode** |
| Load vs. air temp | Single thermocouple is fine | Big steel sections lag the chamber; correctness improves a lot with a **second (load) thermocouple** |
| Recipes | Cone table + `cone_fire_generate()` | An **alloy table** (O1, A2, 1084, 4140, 6061-T6 anneal, copper/brass anneal, glass schedules) generating profiles the same way |

The plan is phased so Phase 1 ships with zero engine-behavior risk, Phase 2 adds the
engine precision features, and Phase 3 covers optional hardware.

## 2. What already works, unchanged

- **Multi-segment profiles with signed ramps** — the built-in "Crystalline Glaze" profile
  (`firing_engine.c`, `s_default_profiles`) already does ramp-up → controlled cool-down →
  cool, which is structurally identical to a subcritical anneal.
- **Indefinite holds** (`FIRING_HOLD_INDEFINITE`) — "soak until the operator advances" is
  already how a hardening soak before quench can be modeled today.
- **Pause/resume, delayed start, skip-segment**, live setpoint computation
  (`compute_dynamic_setpoint`), ETA (`firing_remaining_s`), history, webhooks, alarm
  output, per-profile max-temp validation against `max_safe_temp`.
- **Temperature range** — `APP_HARDWARE_MAX_TEMP_C` (1400 °C) comfortably covers every
  common heat-treat cycle (hardening high-alloy steels tops out ~1100 °C).
- **Host test harness hooks** (`firing_tick()` with injected clock,
  `firing_engine_dispatch_cmd_for_test`) — every engine change below is testable off-target.

## 3. Data-model changes

### 3.1 `firing_profile_t`: process type (Phase 1)

```c
typedef enum {
    PROCESS_CERAMIC = 0,   /* zero = legacy default, see NVS note */
    PROCESS_HEAT_TREAT,    /* metals: anneal / temper / harden / stress-relieve */
    PROCESS_GLASS,         /* glass annealing/slumping (free rider) */
} process_type_t;
```

Append `uint8_t process_type;` to `firing_profile_t` (and `processType` to
`web_ui/src/app/types/kiln.ts` `FiringProfile`). It drives:

- vent policy (§5.2), UI grouping/badges, which safety heuristics apply, and which
  preset library the pickers show.

**NVS compatibility constraint:** profiles are stored as raw struct blobs
(`firing_engine_save_profile` → `nvs_set_blob(key, profile, sizeof(firing_profile_t))`)
and loaded with a caller-sized buffer. Old (smaller) blobs load into the grown struct
fine *only if* new fields are appended at the end and **zero is the correct legacy
default** (`PROCESS_CERAMIC = 0`). Rule for every field added in this plan: append-only,
zero-means-legacy-behavior. `firing_cmd_t` carries a profile by value through a
4-deep queue, so keep an eye on queue RAM as the struct grows (currently ~1.3 KB/profile;
the additions below are a few dozen bytes).

### 3.2 `firing_segment_t`: soak tolerance + segment flags (Phase 2)

```c
/* appended to firing_segment_t */
uint8_t hold_tolerance_c; /* 0 = legacy (timer runs once target reached);
                             N = guaranteed soak, clock only counts within ±N °C */
uint8_t flags;            /* bit0 SEG_FLAG_NATURAL_COOL: SSR forced off, segment
                             completes when temp <= target (ramp_rate ignored)
                             bit1 SEG_FLAG_ALERT_ON_COMPLETE: fire alarm + webhook
                             when this segment finishes ("quench now") */
```

Mirror both in `kiln.ts`, the JSON API (`api_json.c`), the zod schemas
(`web_ui/src/app/schemas/`), and the mock/demo simulator.

## 4. Engine changes (`firing_tick`)

### 4.1 Guaranteed soak (Phase 2, the key metallurgy feature)

Today the hold clock starts when `at_target_predicate()` fires and then counts wall time
even if the kiln sags 30 °C. For `hold_tolerance_c > 0`:

- Accumulate hold time only while `|current_temp − target| ≤ hold_tolerance_c`
  (switch the hold from "start timestamp" to a µs accumulator, same pattern as
  `s_state.elapsed_accum_us`).
- Surface it: add a `soak_ok` boolean (or an out-of-band flag) to `firing_progress_t`
  so the dashboard/web UI can show "SOAKING 42/60 min (in band)" vs. "recovering".
- Log/history-annotate band excursions so a heat-treat run is auditable.

### 4.2 Natural-cool segments (Phase 2)

`SEG_FLAG_NATURAL_COOL`: SSR stays at 0, segment completes when
`current_temp <= target_temp`. Needed because segment validation (rightly) rejects
`ramp_rate == 0`, and a PID-assisted "cool" segment can never cool *faster* than the
kiln's natural loss — normalizing and air-hardening recipes just want "power off, tell
me when it's below X". Suppress the not-rising and runaway checks for these segments;
ETA can use a simple exponential-cooling estimate or report unknown.

### 4.3 Operator-action alerts (Phase 2)

`SEG_FLAG_ALERT_ON_COMPLETE` reuses the existing event queue: emit a new
`FIRING_EVENT_SEGMENT_ALERT` (alongside `FIRING_EVENT_COMPLETE`/`ERROR`) so the existing
consumer fires `safety_trigger_alarm()` and the webhook. Combined with
`FIRING_HOLD_INDEFINITE`, this models the hardening flow precisely:
"soak at 815 °C ≥ 15 min → **beep + webhook: quench now** → operator opens lid, pulls
part, presses skip".

### 4.4 Control quality at tempering temperatures (Phase 2)

- **Gain scheduling:** store 2–3 PID gain sets in NVS keyed by temperature band
  (e.g. <400 °C / 400–900 °C / >900 °C), selected by current setpoint in `firing_tick`.
  `pid_load_gains/pid_save_gains` grow a band parameter; autotune
  (`FIRING_CMD_AUTOTUNE_START` already takes an arbitrary setpoint) saves into the band
  containing its setpoint. Default: one band = exactly today's behavior.
- **Smarter not-rising check:** the 10 °C/15 min heating watchdog should be skipped when
  the setpoint is within ~15 °C of current temp (PID is *supposed* to flatten out near
  target). This fixes a latent false-trip risk for ceramics too, but matters more for
  long low-temp tempers where approach is asymptotic.

## 5. Safety & hardware policy

### 5.1 Unchanged and still binding

Over-temp watchdog, TC-fault handling, emergency stop, per-start profile validation
against `safety_get_max_temp()` all apply as-is. Heat-treat profiles are *lower* risk
thermally; the new risk is process-quality, not fire.

### 5.2 Mode-aware vent (Phase 1)

`safety_update_vent(is_firing, temp)` currently opens the vent whenever firing below
700 °C — correct for burning off organics, wrong for a 200 °C temper (heat loss, scale,
temperature gradients). Pass the active profile's `process_type` through (or a
`vent_policy` derived from it): `PROCESS_HEAT_TREAT` keeps the vent closed by default.

### 5.3 Optional hardware (Phase 3)

- **Second thermocouple (load TC):** MAX31855 is SPI with one CS per chip; the shared
  bus (`APP_SPI_HOST`) has room for another CS GPIO via Kconfig. Extend the
  `thermocouple` component to N channels; add per-profile `control_source`
  (air TC controls PID; load TC gates guaranteed-soak). This is the single biggest
  correctness upgrade for thick sections.
- **Atmosphere purge relay:** one more optional GPIO (pattern: `APP_PIN_VENT`) driving an
  argon/N₂ solenoid to reduce decarb/scale, on during HEATING/HOLDING for heat-treat
  profiles. (Documentation should still recommend stainless foil wrap for tool steels.)
- **Lid switch:** `APP_PIN_LID_SWITCH` already exists in config; wire it to auto-pause
  (SSR off) on lid-open during heat-treat runs, with an explicit "transfer window"
  after a quench alert where opening is expected.
- **Accuracy note:** K-type + MAX31855 is ±2–3 °C class. Fine for annealing/most
  tempering; document it, and consider a two-point calibration (extend the existing
  single `tc_offset_c`) as a stretch item.

## 6. Recipe library: `heat_treat_table` component (Phase 1)

New component mirroring `cone_table/`:

- Table of common recipes: knife steels (O1, W2, 1084, 1095, 80CrV2, A2, D2, 52100),
  structural (4140 anneal/normalize/stress-relieve), aluminum (6061 anneal; note T6
  aging is doable, solution-quench is operator-action), copper/brass anneal, plus
  soda-lime and borosilicate glass annealing schedules.
- `heat_treat_generate(alloy_id, cycle_kind, out_profile)` emits a `firing_profile_t`
  exactly like `cone_fire_generate()` does — e.g. O1 anneal: ramp 150 °C/hr → 760 °C,
  soak 30 min (tolerance ±8), controlled cool −22 °C/hr → 540 °C, natural cool → 150 °C,
  alert. Recipes cite published supplier data sheets in comments.
- 2–3 heat-treat presets join `s_default_profiles` (tagged `PROCESS_HEAT_TREAT`).

## 7. UI work

**Web UI (Phase 1, then 2):**
- `FiringProfiles.tsx`: type badge + filter tabs (Ceramic / Heat treat / Glass).
- `ProfileBuilder.tsx`: process-type selector; per-segment tolerance and
  natural-cool/alert toggles (Phase 2 fields); an "alloy wizard" mirroring the cone
  picker, backed by a new `/api/v1/heat-treat` table endpoint (or a bundled static table,
  like the demo build does for cones).
- Dashboard: soak-band indicator ("in band 42/60 min"); chart unchanged.
- Mock/demo simulator (`web_ui/mock-server/`): add a load-thermal-mass lag so guaranteed
  soak is demoable in the GitHub Pages build.

**LVGL display (small, Phase 1–2):** the adaptive dashboard is status-driven and needs
almost nothing. `modal_profile_picker.c` shows the process type in the row subtitle;
a "QUENCH NOW"-style alert state reuses the existing status-pill + alarm pattern. No new
screens (per the modal-stack architecture rule).

**API:** all additions are optional JSON fields with legacy defaults — additive, no
version bump needed for existing clients.

## 8. Phasing & effort

| Phase | Contents | Risk | Est. size |
|---|---|---|---|
| **1 — Domain packaging** | `process_type` field end-to-end, `heat_treat_table` component + presets, mode-aware vent, web UI type badge/filter/wizard | Low (append-only data, no control-loop changes) | ~3–5 days |
| **2 — Engine precision** | Guaranteed soak, natural-cool + alert segment flags, `FIRING_EVENT_SEGMENT_ALERT`, gain scheduling + banded autotune, setpoint-aware not-rising check, ProfileBuilder fields, simulator lag model | Medium (touches `firing_tick`; fully coverable by host tests) | ~1–2 weeks |
| **3 — Hardware options** | Second (load) TC + control-source selection, purge relay, lid-switch pause, two-point TC cal | Medium (needs bench) | as-needed |

**Testing:** every Phase 2 behavior gets host-harness coverage via `firing_tick()` with a
virtual clock (soak clock freezes out-of-band; natural-cool completes on threshold;
alert event emitted once; gain set switches at band edges). Phase 1 is covered by
existing web UI tests plus profile round-trip (old blob → new struct) tests.

## 9. Explicit non-goals

- Faster-than-natural cooling or quench automation — the hardware is a heater; quench is
  an operator action by design.
- Atmosphere *control* (carburizing, gas mixing) — purge only.
- Multi-cycle automation (e.g. auto double-temper) — run the temper profile twice;
  a `repeat_count` could be a later follow-up if demand shows up.
