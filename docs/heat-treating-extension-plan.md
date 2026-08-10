# Extension Plan: Metal Heat Treating & Annealing Support

Status: **proposal / design doc** — no implementation yet. See also
[`application-roadmap-and-pcb-provisions.md`](application-roadmap-and-pcb-provisions.md)
for the broader application catalog and the PCB provisions that support this plan's
Phase 3 hardware.

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
(`firing_engine_save_profile` → `nvs_set_blob(key, profile, sizeof(firing_profile_t))`).
Append-only + **zero-means-legacy-behavior** (`PROCESS_CERAMIC = 0`) is the rule for
every field added in this plan — but it is *not sufficient on its own*:
`nvs_get_blob` writes only as many bytes as the stored blob contains, and
`firing_engine_load_profile()` passes a caller-supplied (often uninitialized stack)
struct. Loading an old, smaller blob into the grown struct would leave the appended
`process_type` byte as whatever garbage was on the stack, randomly classifying legacy
ceramic profiles and applying the wrong vent/safety policy. Phase 1 therefore **must**
also make the loader deterministic: `memset(profile, 0, sizeof *profile)` before the
`nvs_get_blob` call (and treat a stored size larger than `sizeof(firing_profile_t)`
as an error). The old-blob → new-struct round-trip test in §8 exists to pin exactly
this behavior.

**Zero-filling the destination is not enough for fields that land in existing
padding.** It works for `process_type` because that byte is *past* the end of a
legacy blob, so `nvs_get_blob` never writes it. It does **not** work for §3.2's
segment fields. Measured layout of today's `firing_segment_t`: `id[40]`, `name[48]`,
`ramp_rate` @88, `target_temp` @92, `hold_time` @96–97, **two bytes of tail padding
@98–99**, `sizeof == 100`. Appending `hold_tolerance_c` and `flags` fills exactly
those two padding bytes, so the struct stays 100 bytes and a legacy blob is
byte-for-byte the same length — `nvs_get_blob` copies all 100 bytes per segment,
**overwriting the memset zeros with whatever the padding held when the profile was
saved**. Padding is indeterminate (`nvs_set_blob` writes `sizeof` bytes straight
from the struct, padding included), so an old profile can come back with guaranteed
soak, natural cooling, or a quench alert silently enabled.

The fix is an explicit persisted-format version rather than inference from size:

```c
/* appended to firing_profile_t in Phase 1, before any segment field exists */
uint8_t schema_version;  /* 0 = pre-versioning legacy blob; 1 = this layout, … */
```

`schema_version` sits past the legacy blob's end, so the memset above *does* make it
reliably 0 for old profiles. On load, after `nvs_get_blob`: if `schema_version == 0`,
explicitly zero the fields that occupy former padding across all
`FIRING_MAX_SEGMENTS` segments (whatever their indeterminate bytes said), then stamp
the current version. Three supporting rules:

- **`firing_engine_save_profile()` must stamp the current version on the struct it
  writes** — `profile->schema_version = FIRING_SCHEMA_VERSION` immediately before
  `nvs_set_blob`, on its own canonical copy. Stamping only during load is not
  enough, and this is the failure that would bite first: `profile_from_json()`
  begins with `memset(out, 0, sizeof(*out))` (`api_handlers.c:248`), so **every
  profile arriving over REST or import carries `schema_version == 0`**, as do
  generated and default profiles that never set the field. A Phase 2 profile with
  real `hold_tolerance_c`/`flags` would then persist as a version-0 blob, and its
  very next load would run the legacy migration and silently wipe exactly the
  fields the user just set. The version must describe *the layout being written*,
  which only the writer knows.
- **`firing_engine_save_profile()` must also zero the whole struct before
  populating it** so padding written from here on is deterministic — otherwise the
  same class of bug recurs at the next schema bump.
- Every future field lands either past the end (covered by memset + version) or in
  known-zeroed padding (covered by the migration). Bump `schema_version` and add a
  migration step whenever a field moves into previously indeterminate bytes.

The §8 round-trip tests must therefore cover the hostile case and the save path, not
just the benign read: a legacy blob with **0xFF-filled** segment padding must load
with `hold_tolerance_c == 0` and `flags == 0`, **and** a profile saved with
tolerance/flags set must survive a save → load round-trip with those values intact
(the regression test for an unstamped save).

`firing_cmd_t` carries a profile by value through a 4-deep queue, so keep an eye on
queue RAM as the struct grows. The current footprint is larger than it looks:
`firing_segment_t` is 100 bytes (40 id + 48 name + 2 floats + hold + padding), so the
16-segment array alone is 1,600 bytes and `firing_profile_t` totals **~1.83 KB** —
the 4-deep command queue already reserves ~7.3 KB for profile-bearing commands before
queue overhead. The additions below are a few dozen bytes, but any *future* schema
growth should re-check this figure (or switch the START command to a pointer +
engine-owned copy) rather than assuming a ~1.3 KB baseline.

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

⚠️ These two bytes land in `firing_segment_t`'s existing tail padding (@98–99), so
they are the exact case the destination memset cannot protect — they require the
`schema_version` migration described in §3.1. Do not implement Phase 2 without it.

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
consumer fires `safety_trigger_alarm()` and the webhook.

Note the flag must **not** be combined with `FIRING_HOLD_INDEFINITE` on a single
segment to model a hardening soak: an indefinite hold only ever finishes because the
operator presses skip, so a completion-triggered alert would fire *after* the action
it is meant to prompt. Model the minimum soak and the open-ended wait as **two
segments** at the same temperature instead:

1. Segment N — soak at 815 °C, `hold_time = 15 min` (guaranteed via
   `hold_tolerance_c`), `SEG_FLAG_ALERT_ON_COMPLETE`. When the minimum soak is
   satisfied, the segment completes on its own and the alert fires:
   **beep + webhook: quench now**.
2. Segment N+1 — same target, `FIRING_HOLD_INDEFINITE`. The kiln keeps holding at
   temperature while the operator opens the lid, pulls the part, and presses skip.

This needs no new event semantics — the alert rides an ordinary timed-segment
completion, and the indefinite wait is a plain hold. `heat_treat_generate()` emits
the two-segment pair for hardening cycles; the ProfileBuilder just documents the
pattern.

### 4.4 Control quality at tempering temperatures (Phase 2)

- **Gain scheduling:** store 2–3 PID gain sets in NVS keyed by temperature band
  (e.g. <400 °C / 400–900 °C / >900 °C), selected by current setpoint in `firing_tick`.
  `pid_load_gains/pid_save_gains` grow a band parameter; autotune
  (`FIRING_CMD_AUTOTUNE_START` already takes an arbitrary setpoint) saves into the band
  containing its setpoint. Default: one band = exactly today's behavior.
- **Smarter not-rising check.** Today's watchdog (`firing_tick`) is unconditional
  while heating: less than `RISING_THRESHOLD_C` (10 °C) of rise across a 15-minute
  window trips `FIRING_ERR_NOT_RISING`. It needs to tolerate the PID flattening out
  as it converges on a target, without ever going blind on a stalled kiln. Two
  tempting formulations are both wrong, and the reasons are worth recording because
  each looks correct in isolation:

  - *"Skip when the dynamic setpoint is within ~15 °C of the reading."* On a slow
    programmed ramp (say 20 °C/hr) the moving setpoint stays within 15 °C of a
    stalled kiln for ~45 minutes, so a failed element goes undetected far past the
    existing window — and slow ramps are exactly what these recipes are made of.
  - *"Compare measured rise against the rise `firing_planned_temp_at()` intended
    over the window."* This one fails in the opposite direction, permanently. The
    ideal-profile timeline is anchored to firing start, so it does not slip when the
    real kiln falls behind: once a dead element makes the kiln lag, the ideal curve
    runs ahead, reaches the final target, and **plateaus**. Planned rise then reads
    zero for every subsequent window, so the check exempts itself forever while the
    kiln sits hundreds of degrees below target. The same misalignment appears after
    any ordinary ramp or soak overrun, and the first bad window is the one that
    straddles the ideal plateau — planned rise there is already below any sensible
    floor.

  The invariant the check actually wants is **segment-relative**, referencing only
  the active segment's own target and programmed rate — quantities that do not drift
  with the wall clock:

  - **Scale the threshold to the segment's own `ramp_rate`, capping at today's
    value.** Expected rise over the window is `ramp_rate × 0.25 h`; trip when
    measured rise falls below
    `min(RISING_THRESHOLD_C, 0.5 × expected_rise)`. It must be a **cap, not a
    floor**: a healthy 20 °C/hr ramp only gains 5 °C per 15-minute window, so a
    10 °C floor would emergency-stop a perfectly good firing. `min()` gives that
    ramp a 2.5 °C threshold, while any ramp of 80 °C/hr or faster saturates the cap
    and keeps exactly today's 10 °C behavior.
  - **The near-target exemption must be bounded**, or it becomes its own blind spot.
    Exempting purely on `|target − current| ≤ ~15 °C` never terminates: if an element
    dies 10 °C short, the kiln is permanently "near target" but
    `at_target_predicate()` needs it within 2 °C to start the hold, so the segment
    never advances, the exemption never lifts, and nothing ever trips — a stall that
    hangs forever is precisely what this watchdog exists to catch. Two extra
    conditions, either of which is sufficient to trip:
    - **Not saturated.** Genuine PID convergence backs off the element as it
      closes on target; a dead element sits at full duty with no rise. So exempt
      only while duty is below ~0.9. Note `pid_compute()` runs *after* this check
      in `firing_tick()`, so it reads the previous tick's duty — fine at 1 Hz, but
      store it explicitly rather than relying on statement order.
    - **Time-bounded.** Cap the exemption at ~2 consecutive windows (~30 min).
      Converging the last 15 °C takes minutes, not half an hour; past that, trip
      regardless of duty.
  - Natural-cool segments (§4.2) and any non-heating status stay exempt as they are
    today.

  This also fixes a latent false-trip risk for ceramics, but it matters most for
  long low-temp tempers where the approach is asymptotic. Host-harness coverage —
  the last three are regression tests for formulations rejected above, so they must
  all assert a **trip**:

  | Scenario | Expected |
  |---|---|
  | Healthy 20 °C/hr ramp (5 °C/window) | no trip — the cap-vs-floor case |
  | Fast ramp, healthy | no trip; threshold is exactly today's 10 °C |
  | Slow ramp, dead element | trips within one window |
  | Near-target PID convergence, duty backing off | no trip |
  | Stalled 10 °C below target at full duty | **trips** (saturation bound) |
  | Stalled just below target, duty ambiguous | **trips** after ~2 windows (time bound) |
  | Far below target, ideal profile long since plateaued | **trips** (planned-rise regression) |

## 5. Safety & hardware policy

### 5.1 Unchanged and still binding

Over-temp watchdog, TC-fault handling, emergency stop, per-start profile validation
against `safety_get_max_temp()` all apply as-is *for the single-sensor phases (1–2)*.
Heat-treat profiles are *lower* risk thermally; the new risk is process-quality, not
fire. Phase 3's second sensor changes the picture — once a load TC can gate progress,
its faults must feed the safety path too (see §5.3).

### 5.2 Mode-aware vent (Phase 1)

`safety_update_vent(is_firing, temp)` currently opens the vent whenever firing below
700 °C — correct for burning off organics, wrong for a 200 °C temper (heat loss, scale,
temperature gradients). Pass the active profile's `process_type` through (or a
`vent_policy` derived from it): `PROCESS_HEAT_TREAT` keeps the vent closed by default.

### 5.3 Optional hardware (Phase 3)

- **Second thermocouple (load TC):** the shared SPI bus (`APP_SPI_HOST`) has room for
  another CS GPIO via Kconfig. The companion PCB plan
  ([roadmap §3.2](application-roadmap-and-pcb-provisions.md)) fits **MAX31856**
  front-ends, which are *not* drop-in MAX31855s: they need register configuration and
  MOSI write transactions, where the current driver only does read-only 32-bit frames.
  This phase therefore adds a **second driver backend, never a replacement**: a
  MAX31856 backend in `components/thermocouple/` (config registers on init,
  fault-register decode) alongside the existing MAX31855 one, both generalized to N
  channels.

  **The component's public API has to grow channel awareness — it cannot stay as it
  is.** Today it is single-sensor from top to bottom: `thermocouple_init(host,
  cs_pin)` takes one CS, and `thermocouple_get_latest(thermocouple_reading_t *out)`
  returns one cached reading backed by one spinlock-protected slot. Keeping that
  signature would leave every caller — the firing engine and the safety task
  included — able to see only the primary probe, which defeats both `control_source`
  and the fault routing below by construction. Phase 3 needs an indexed accessor
  (`thermocouple_get_latest_ch(int ch, …)`) or, better, an **atomic multi-channel
  snapshot** so the engine cannot mix a fresh air reading with a stale load reading
  inside one tick. Keep a single-channel convenience wrapper so existing call sites
  and the host harness stay unchanged.

  **The installed base makes "replace the driver" a device-bricking change.** Every
  controller in the field today — the perfboard build and the generated PCB
  (`hardware/kicad/`, BOM part MAX31855KASA+) — carries a MAX31855, and
  `.github/workflows/release.yml` publishes a **single** `bisque.bin` plus one
  `manifest.json` that all devices fetch from
  `/releases/latest/download/manifest.json`. There is no hardware-revision axis in
  the release, so a MAX31856-only image would OTA itself onto MAX31855 hardware and
  leave it unable to read temperature — i.e. unable to fire. A build-time Kconfig
  choice alone does not fix this either, for the same reason: one published image.
  So the backend must be **selectable at runtime** — probe at init (the MAX31856 has
  readable/writable config registers; the MAX31855 is a read-only frame, so a
  write-then-read-back of a known register value distinguishes them), with a
  settings override for anything ambiguous, and both backends compiled into the
  shipped image. Publishing hardware-specific images is the alternative, but it
  means a release-workflow matrix and an OTA manifest keyed by hardware revision —
  strictly more work than carrying two small drivers.

  Add per-profile `control_source` (air TC controls PID; load TC gates
  guaranteed-soak). This is the single biggest correctness upgrade for thick
  sections.

  **Fault handling is part of the feature, not an afterthought:** the current safety
  task watches only the singleton primary reading, and §5.1's "unchanged" claim stops
  being true the moment a second sensor can *gate* progress. If the load probe opens
  or its reading goes stale while the air probe stays valid, a guaranteed soak would
  sit out-of-band forever with the PID happily holding the chamber at temperature.
  Multi-channel support must route faults and staleness from **every configured
  control or gating sensor** into the existing safety path — a load-TC fault during
  a gated segment raises `FIRING_ERR_TC_FAULT` (SSR off, alarm) rather than
  silently stalling the profile. Host-harness tests cover the fault-during-soak
  case explicitly.
- **Atmosphere purge relay:** one more optional GPIO (pattern: `APP_PIN_VENT`) driving an
  argon/N₂ solenoid to reduce decarb/scale, on during HEATING/HOLDING for heat-treat
  profiles. (Documentation should still recommend stainless foil wrap for tool steels.)
- **Lid switch:** the interlock is now implemented in firmware (PR #286):
  `components/safety/` debounces the input, reports `lid_state_t` to the UIs, and an
  armable SSR gate cuts the elements on lid-open (`safety_set_lid_interlock_armed`,
  enforced in `ssr_window_apply()`), with `warn` / `pause` / `interlock` modes.

  What remains for heat treating is only the **policy** layer around a quench: after
  a `SEG_FLAG_ALERT_ON_COMPLETE` segment, opening the lid is expected, so it should
  not read as a fault or stall the program. **The transfer window must never disarm
  the SSR gate.** That is precisely the moment an operator has both hands in an
  815 °C oven reaching for a part, and disarming would let the PID — which still
  sees a large negative error from the open door — energize the elements. The
  correct behavior already exists as `LID_MODE_INTERLOCK`: `safety.c`'s
  `lid_blocks_output()` holds the SSR off for as long as the lid reads open, while
  `firing_tick()` deliberately keeps the program clock and segment advance running
  (it sets a `lid_holds_heat` flag rather than returning early, so the following
  indefinite hold still behaves like a hold).

  So the transfer window is a *notification and mode* concern, not a gating one:
  during it, suppress the lid-open warning/alarm and force interlock semantics for
  the duration even if the profile is otherwise running in `pause` mode (a
  pause-then-auto-resume would fight the operator mid-transfer). Elements stay
  hard-gated off by safety throughout, exactly as on any other lid-open event.
- **Accuracy note:** K-type + MAX31855 (today's hardware) is ±2–3 °C class — fine for
  annealing/most tempering; document it. The PCB run's MAX31856 improves
  cold-junction accuracy and adds 50/60 Hz filtering. Consider a two-point
  calibration (extend the existing single `tc_offset_c`) as a stretch item.

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
| **1 — Domain packaging** | `process_type` + `schema_version` fields end-to-end, load-path zero-fill, `heat_treat_table` component + presets, mode-aware vent, web UI type badge/filter/wizard | Low (append-only data, no control-loop changes) | ~3–5 days |
| **2 — Engine precision** | Segment-padding migration (§3.1), guaranteed soak, natural-cool + alert segment flags, `FIRING_EVENT_SEGMENT_ALERT`, gain scheduling + banded autotune, segment-relative not-rising check, ProfileBuilder fields, simulator lag model | Medium (touches `firing_tick`; fully coverable by host tests) | ~1–2 weeks |
| **3 — Hardware options** | Second (load) TC: MAX31856 backend *added alongside* MAX31855 with runtime selection, N channels, control-source selection, gating-sensor fault routing; purge relay; quench transfer-window policy (gate stays armed); two-point TC cal | Medium (needs bench; OTA reaches mixed hardware) | as-needed |

**Testing:** every Phase 2 behavior gets host-harness coverage via `firing_tick()` with a
virtual clock (soak clock freezes out-of-band; natural-cool completes on threshold;
alert event emitted once; gain set switches at band edges; the four not-rising cases
in §4.4). Phase 1 is covered by existing web UI tests plus profile round-trip tests —
including the hostile legacy blob (0xFF segment padding) described in §3.1.

## 9. Explicit non-goals

- Faster-than-natural cooling or quench automation — the hardware is a heater; quench is
  an operator action by design.
- Atmosphere *control* (carburizing, gas mixing) — purge only.
- Multi-cycle automation (e.g. auto double-temper) — run the temper profile twice;
  a `repeat_count` could be a later follow-up if demand shows up.
