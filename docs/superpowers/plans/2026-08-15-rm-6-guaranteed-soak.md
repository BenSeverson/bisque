# RM-6: Guaranteed Soak Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a hold mean "N minutes *at* temperature" rather than "N minutes elapsed while roughly near temperature", when `hold_tolerance_c > 0`.

**Architecture:** Replace the segment's hold **start timestamp** with a µs **accumulator**, following the pattern `s_state.elapsed_accum_us` already uses. The accumulator advances only while `|current_temp − target| ≤ hold_tolerance_c`. `hold_tolerance_c == 0` keeps today's behaviour exactly. A `soak_ok` flag on `firing_progress_t` lets the UIs distinguish soaking from recovering.

**Tech Stack:** `firing_tick()`, the host firing-scenario harness (`plant.c`), zod, Swift.

**Issue:** [#324](https://github.com/BenSeverson/bisque/issues/324) · **Depends on [RM-5 #323](https://github.com/BenSeverson/bisque/issues/323)** for `hold_tolerance_c`

**Spec:** [`docs/heat-treating-extension-plan.md`](../../heat-treating-extension-plan.md) §4.1

## Global Constraints

- **`hold_tolerance_c == 0` must be bit-identical to today.** Every existing profile and every existing firing-scenario test depends on it. If a scenario test's timing shifts, the legacy path was changed — that is a bug, not a rebaseline.
- **The accumulator must survive pause/resume.** `segment_hold_start_time_s` is currently fixed up in two places (`firing_engine.c:1102` and `:1465`) by adding the paused duration. An accumulator removes the need for both — **delete them rather than leaving them to double-count.** Grep for `segment_hold_start_time_s` and make sure every reference is gone or converted.
- **Not-rising and runaway checks interact.** A kiln sagging out of band during a soak is exactly what the not-rising watchdog is built to notice; a guaranteed soak legitimately extends wall-clock time. Decide explicitly whether an out-of-band soak re-arms or suppresses that check, and test it. RM-10 revisits this properly — do not silently change the watchdog here, but do record what you chose.
- This is fully host-testable via `firing_tick()` with a virtual clock and `plant.c`. **No hardware needed**, and no excuse for an untested path.

## File Structure

| File | Responsibility |
|---|---|
| `components/firing_engine/firing_engine.c` | The accumulator, the band predicate, `soak_ok` |
| `components/firing_engine/include/firing_engine.h` | `soak_ok` on `firing_progress_t` |
| `tests/host/test_firing_scenarios.c` | Scenario coverage using the virtual clock |
| `api_json.c`, zod, Swift, mock server | Report `soakOk` |
| `components/display/dashboard.c` | Show in-band vs recovering |

---

### Task 1: Scenario tests first

**Files:**
- Modify: `tests/host/test_firing_scenarios.c`

**Interfaces:**
- Consumes: `hold_tolerance_c` (RM-5), `firing_tick()`, `plant.c`.
- Produces: the failing tests Task 2 satisfies.

- [ ] **Step 1: Write the legacy-unchanged test**

```c
/* The guard rail for the whole change. With tolerance 0 the hold must
   complete on wall time exactly as before, sag or no sag. */
static void test_zero_tolerance_holds_on_wall_time_despite_sag(void)
{
    firing_profile_t p = single_hold_profile(/*target*/ 900.0f,
                                             /*hold_min*/ 10,
                                             /*tolerance*/ 0);
    scenario_start(&p);
    scenario_run_until_hold_begins();
    plant_force_temperature(870.0f);         /* 30 C low, out of any band */
    scenario_advance_minutes(10);
    TEST_ASSERT_TRUE(scenario_segment_complete());
}
```

- [ ] **Step 2: Write the guaranteed-soak tests**

```c
/* The feature. 30 C low is outside a 5 C band, so the clock must not run. */
static void test_out_of_band_does_not_accumulate_soak(void)
{
    firing_profile_t p = single_hold_profile(900.0f, 10, /*tolerance*/ 5);
    scenario_start(&p);
    scenario_run_until_hold_begins();
    plant_force_temperature(870.0f);
    scenario_advance_minutes(10);
    TEST_ASSERT_FALSE(scenario_segment_complete());
    TEST_ASSERT_FALSE(scenario_progress().soak_ok);
}

/* And it must resume, not restart — a sag partway through a soak should
   cost the sag, not the soak so far. */
static void test_soak_resumes_after_an_excursion(void)
{
    firing_profile_t p = single_hold_profile(900.0f, 10, 5);
    scenario_start(&p);
    scenario_run_until_hold_begins();
    plant_force_temperature(900.0f);
    scenario_advance_minutes(6);             /* 6 of 10 banked */
    plant_force_temperature(870.0f);
    scenario_advance_minutes(30);            /* long excursion, banks nothing */
    TEST_ASSERT_FALSE(scenario_segment_complete());
    plant_force_temperature(900.0f);
    scenario_advance_minutes(4);             /* the remaining 4 */
    TEST_ASSERT_TRUE(scenario_segment_complete());
}

/* The band is symmetric: overshoot is as much "not at temperature" as sag,
   and for tempering it matters more. */
static void test_overshoot_also_stops_the_clock(void)
{
    firing_profile_t p = single_hold_profile(200.0f, 10, 5);
    scenario_start(&p);
    scenario_run_until_hold_begins();
    plant_force_temperature(230.0f);
    scenario_advance_minutes(10);
    TEST_ASSERT_FALSE(scenario_segment_complete());
}

/* Pause must not bank soak time. The old code fixed up a start timestamp in
   two places; an accumulator that keeps advancing while paused would give a
   free soak for the length of the pause. */
static void test_pause_does_not_bank_soak_time(void)
{
    firing_profile_t p = single_hold_profile(900.0f, 10, 5);
    scenario_start(&p);
    scenario_run_until_hold_begins();
    plant_force_temperature(900.0f);
    scenario_advance_minutes(5);
    scenario_pause();
    scenario_advance_minutes(30);
    scenario_resume();
    scenario_advance_minutes(4);
    TEST_ASSERT_FALSE(scenario_segment_complete());   /* 9 of 10 */
    scenario_advance_minutes(1);
    TEST_ASSERT_TRUE(scenario_segment_complete());
}
```

Helper names above (`single_hold_profile`, `scenario_*`, `plant_force_temperature`) are illustrative — **read `tests/host/test_firing_scenarios.c` and `scenario_helpers.c` and use whatever the harness actually provides**, adding helpers only where none fits.

- [ ] **Step 3: Run and confirm they fail for the right reason**

```bash
make test-host
```

Expected: the legacy test **passes** already; the four soak tests fail. A legacy test that fails here means the harness changed, not the feature.

---

### Task 2: Convert the hold to an accumulator

**Files:**
- Modify: `components/firing_engine/firing_engine.c`
- Modify: `components/firing_engine/include/firing_engine.h`

- [ ] **Step 1: Replace the state field**

```c
    /* Was: float segment_hold_start_time_s;
       An accumulator instead, matching elapsed_accum_us. The start-timestamp
       form could not express "the clock stopped for a while", which is the
       entire feature, and it needed a fix-up on every pause/resume. */
    int64_t segment_hold_accum_us;
```

- [ ] **Step 2: Delete the pause fix-ups**

Remove both `segment_hold_start_time_s += (float)paused_us / 1000000.0f;` sites. **An accumulator that simply is not advanced while paused needs no correction, and leaving these in double-counts.**

```bash
grep -n "segment_hold_start_time_s" components/firing_engine/firing_engine.c
```

Expected after the edit: no matches.

- [ ] **Step 3: Advance the accumulator conditionally**

In the hold branch of `firing_tick`:

```c
    bool in_band = true;
    if (seg->hold_tolerance_c > 0) {
        in_band = fabsf(current_temp - seg->target_temp) <= (float)seg->hold_tolerance_c;
    }
    if (in_band) {
        s_state.segment_hold_accum_us += tick_delta_us;
    }
    s_state.soak_ok = in_band;
```

Note that `in_band` defaults to **true** when `hold_tolerance_c == 0`, which is what makes the legacy path bit-identical: the accumulator then advances every tick, exactly as wall time did.

- [ ] **Step 4: Compare against the accumulator**

Wherever the hold completion is decided, compare `segment_hold_accum_us` against `hold_time` minutes in µs. Watch the `FIRING_HOLD_INDEFINITE` case — `firing_engine.c:635` already special-cases it and must keep doing so.

- [ ] **Step 5: Add `soak_ok` to `firing_progress_t`**

```c
    bool soak_ok;  /* true while the soak clock is running. With
                      hold_tolerance_c == 0 this is true throughout the hold,
                      so a UI can show it unconditionally. */
```

- [ ] **Step 6: Run the tests**

```bash
make test-host
```

Expected: all five pass, and **every pre-existing firing-scenario test still passes unchanged**. If any legacy scenario shifted timing, the `hold_tolerance_c == 0` path is not equivalent — fix that before going on.

- [ ] **Step 7: Format and commit**

```bash
clang-format -i components/firing_engine/
git add components/firing_engine/ tests/host/
git commit -m "feat(engine): make a hold mean time at temperature

The hold clock counted wall time from the moment the target was first
reached, so a kiln sagging 30 C for twenty minutes still recorded a
completed soak. For metallurgy that is the difference between a tempered
part and a decorative one.

Switches to a microsecond accumulator that advances only while the
temperature is within hold_tolerance_c of target, matching the pattern
elapsed_accum_us already uses. Tolerance 0 leaves in_band true every
tick, so the legacy path is bit-identical and every existing scenario
test passes unchanged.

Deletes both pause fix-ups: an accumulator that is not advanced while
paused needs no correction, and keeping them would have double-counted.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Surface it

**Files:** `api_json.c`, zod schemas, Swift models, `web_ui/mock-server/`, `components/display/dashboard.c`

- [ ] **Step 1: Report `soakOk`**

Add to `build_status_json()`, then `make fixtures && make test-web` and watch the contract fail until the zod schema models it. Then model it, and in Swift.

- [ ] **Step 2: Show it on the LCD**

The dashboard's active view shows hold progress. Distinguish "SOAKING 42/60 min" from "RECOVERING" — `ui_status_color()` and `ui_status_label()` are the helpers, and `UI_COLOR_HOLDING` already exists.

- [ ] **Step 3: Verify the display change**

```bash
make sim-verify   # state assertions
make sim          # pixel diff against baselines
```

If the change is intentional and the diff is correct, rewrite baselines with `bisque_sim --screenshot` and **eyeball the result** — the README screenshots come from the same files.

- [ ] **Step 4: Web UI**

Show the same distinction on the dashboard. A soak that is not accumulating looks identical to one that is, otherwise, and that is precisely the state a user needs to see.

- [ ] **Step 5: Full verification and close**

```bash
make test && make sim-verify && make lint && make web-demo
```

Close [#324](https://github.com/BenSeverson/bisque/issues/324). Note in the comment what you decided about the not-rising interaction, since RM-10 picks that up.
