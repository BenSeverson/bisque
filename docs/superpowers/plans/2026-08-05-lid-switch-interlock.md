# Lid Switch Interlock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the previously-unused `APP_PIN_LID_SWITCH` into the firing path as an optional, runtime-configurable lid/door interlock with three modes (`warn`, `pause`, `interlock`), reported through every UI.

**Architecture:** `components/safety` owns the pin — polarity, debounced sampling, and a hard SSR gate alongside the existing emergency-stop gate. `components/firing_engine` owns the policy — it reads `lid_mode` from `kiln_settings_t` and decides what an open lid means for firing status and the program clock. The reading is published as `lid_state_t` (a standalone type mirroring `vent_state_t`) and threaded through the JSON builders to the web UI, iOS app, and LVGL dashboard.

**Tech Stack:** ESP-IDF (C), Unity + ctest for host tests, cJSON, zod + Vitest + React for the web UI, Swift/XCTest for iOS, LVGL + SDL2 for the display simulator.

**Spec:** `docs/superpowers/specs/2026-08-05-lid-switch-interlock-design.md`

## Global Constraints

- **Firmware builds must go through `make`**, never a bare `idf.py` — non-interactive shells have not sourced ESP-IDF's `export.sh`. Use `make firmware`. For a one-off: `. ./scripts/idf-env.sh && idf.py <cmd>` in a *single* command.
- **`tests/host/` links only a subset of components.** Changes to `api_handlers.c`, `ws_handler.c`, and `main/` are completely uncompiled by `make test`. Every task that touches those must also run `make firmware`.
- **Run `clang-format -i` on every changed C/H file** under `main/` or `components/` (or `./scripts/format.sh`). CI fails on unformatted code.
- **Declare each function in exactly one header.** `readability-redundant-declaration` is an error in `.clang-tidy`.
- **Every device payload goes through a `build_*_json()` in `api_json.c`** — never inline `cJSON_Add*` in a handler. Handlers gather inputs into plain structs and delegate.
- **Error bodies are bare messages**, no JSON envelope: `httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing ssid")`.
- **New firmware JSON fields fail the contract tests until the schemas model them.** The web contract test rebuilds each zod schema `.strict()`; iOS `FirmwareContractTests` requires every fixture key in `decoded` or `knownUnmodelled`. Firmware and schema changes land together.
- **App-facing zod schemas stay non-`.strict()`** so a newer kiln still parses in an older tab.
- **LVGL config changes must be mirrored in `simulator/lv_conf.h`** or the sim silently diverges.
- **Mode names are exactly** `warn`, `pause`, `interlock` (JSON strings, lowercase).
- **Field names are exactly** `lidOpen` (bool, omitted when not fitted) and `lidMode` (string, always present).

---

### Task 1: Pure lid-debounce helper and configuration

The debounce decision is pure logic, so it goes in `safety_helpers.c` next to `safety_tc_watchdog_step()` where the host tests can reach it without compiling `safety.c` (which drags in GPIO, LEDC, and an endless task loop).

**Files:**
- Create: `components/safety/include/lid_state.h`
- Modify: `components/safety/include/safety_internal.h`
- Modify: `components/safety/safety_helpers.c`
- Modify: `main/Kconfig.projbuild:86-91`
- Modify: `components/app_config/include/app_config.h:84-88`
- Modify: `tests/host/fixture_sources.txt`
- Test: `tests/host/test_safety_helpers.c`

**Interfaces:**
- Produces: `lid_state_t { LID_STATE_NOT_FITTED = -1, LID_STATE_CLOSED = 0, LID_STATE_OPEN = 1 }`; `lid_debounce_t`; `lid_state_t safety_lid_debounce_step(lid_debounce_t *d, bool raw_open)`; `APP_LID_SWITCH_ACTIVE_HIGH`.

- [ ] **Step 1: Create the shared state type**

Create `components/safety/include/lid_state.h`:

```c
#pragma once

/**
 * State of the lid/door interlock switch, as reported to the UIs.
 *
 * Deliberately standalone — no esp_err.h, no FreeRTOS — so the three consumers
 * can share one type without dragging the safety driver's dependencies along:
 * the pure JSON builders in web_server/api_json.c (host-buildable by contract),
 * the LVGL dashboard (which the SDL simulator compiles with no ESP-IDF at all),
 * and safety.c itself.
 *
 * NOT_FITTED is a distinct state rather than a "closed": the lid GPIO defaults
 * to -1 (see CONFIG_KILN_PIN_LID_SWITCH), so most kilns have no switch at all,
 * and an indicator permanently reading "lid closed" would be reporting on
 * hardware that isn't there. Consumers omit the reading entirely in that case.
 */
typedef enum {
    LID_STATE_NOT_FITTED = -1,
    LID_STATE_CLOSED = 0,
    LID_STATE_OPEN = 1,
} lid_state_t;
```

- [ ] **Step 2: Declare the debounce helper**

Add to `components/safety/include/safety_internal.h`, after the `safety_tc_watchdog_step` declaration and before the closing `#ifdef __cplusplus`:

```c
/* Consecutive "closed" samples required before heat is allowed back on. At
 * safety_task's 500 ms cadence this is ~1 s. */
#define LID_CLOSE_DEBOUNCE_SAMPLES 2

typedef struct {
    lid_state_t state;  /* debounced result; seed with LID_STATE_OPEN */
    int close_samples;  /* consecutive raw-closed samples seen so far */
} lid_debounce_t;

/**
 * Advance the lid debounce by one sample and return the debounced state.
 *
 * Deliberately asymmetric: an open reading is believed immediately, while a
 * closed reading must repeat LID_CLOSE_DEBOUNCE_SAMPLES times before the lid is
 * declared shut. Cutting heat is cheap and restoring it should be deliberate,
 * so the asymmetry both fails safe and stops a bouncing or marginal switch from
 * chattering the SSR.
 *
 * Seed `state` with LID_STATE_OPEN: at boot the true position is unknown, and
 * assuming open costs at most ~1 s before the first firing can start.
 *
 * `raw_open` is the polarity-corrected pin reading, not the raw level — see
 * APP_LID_SWITCH_ACTIVE_HIGH. Pure: no globals, no I/O.
 */
lid_state_t safety_lid_debounce_step(lid_debounce_t *d, bool raw_open);
```

Add `#include "lid_state.h"` to the include block at the top of the same file.

- [ ] **Step 3: Write the failing tests**

Add to `tests/host/test_safety_helpers.c`, before `main()`:

```c
/* ── Lid debounce ────────────────────────────────────────────────────────── */

static void test_lid_open_is_believed_immediately(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    /* Get to a settled closed state first. */
    safety_lid_debounce_step(&d, false);
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, safety_lid_debounce_step(&d, false));
    /* One open sample is enough — no debounce on the way to cutting heat. */
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, true));
}

static void test_lid_close_requires_two_consecutive_samples(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, false));
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, safety_lid_debounce_step(&d, false));
}

/* A switch that bounces while closing must not accumulate credit across the
   bounce — otherwise two closed samples separated by an open one would declare
   the lid shut while it is still moving. */
static void test_lid_bounce_resets_the_close_counter(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, false));
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, true));
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, false));
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, safety_lid_debounce_step(&d, false));
}

/* Staying closed must not overflow or change state on long runs. */
static void test_lid_stays_closed_while_closed(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    for (int i = 0; i < 100; i++) {
        safety_lid_debounce_step(&d, false);
    }
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, d.state);
    TEST_ASSERT_TRUE(d.close_samples >= LID_CLOSE_DEBOUNCE_SAMPLES);
}
```

Register them inside `main()` alongside the existing `RUN_TEST` calls:

```c
    RUN_TEST(test_lid_open_is_believed_immediately);
    RUN_TEST(test_lid_close_requires_two_consecutive_samples);
    RUN_TEST(test_lid_bounce_resets_the_close_counter);
    RUN_TEST(test_lid_stays_closed_while_closed);
```

- [ ] **Step 4: Run the tests to verify they fail**

```bash
make test-host
```

Expected: compile failure — `unknown type name 'lid_debounce_t'` / implicit declaration of `safety_lid_debounce_step`.

- [ ] **Step 5: Implement the helper**

Append to `components/safety/safety_helpers.c`:

```c
lid_state_t safety_lid_debounce_step(lid_debounce_t *d, bool raw_open)
{
    if (raw_open) {
        /* Believed immediately, and the close counter restarts from zero so a
           bounce partway through closing cannot bank credit toward "shut". */
        d->close_samples = 0;
        d->state = LID_STATE_OPEN;
        return d->state;
    }

    if (d->close_samples < LID_CLOSE_DEBOUNCE_SAMPLES) {
        d->close_samples++;
    }
    if (d->close_samples >= LID_CLOSE_DEBOUNCE_SAMPLES) {
        d->state = LID_STATE_CLOSED;
    }
    return d->state;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
make test-host
```

Expected: PASS, including the four new lid tests.

- [ ] **Step 7: Add the polarity Kconfig option and fix the help text**

In `main/Kconfig.projbuild`, replace the `KILN_PIN_LID_SWITCH` block (currently lines 86-91) with:

```kconfig
        config KILN_PIN_LID_SWITCH
            int "Lid/door switch GPIO (-1 = disabled)"
            default -1
            help
                GPIO input for a lid/door interlock switch. On the Bisque PCB
                this net is LID_SW, brought out on aux header J7 pin 6 (GPIO21),
                with +3V3 and GND on pins 1 and 2 of the same connector.

                When fitted, opening the lid during a firing de-energizes the
                elements. What happens to the running program depends on the
                "lid mode" setting: warn (report only), pause (hold the program
                clock, auto-resume on close) or interlock (elements off, program
                keeps running — the heat-treat oven convention).

                THIS IS NOT A SAFETY DEVICE. It is a supplementary, firmware-level
                interlock, and it does nothing if the firmware has crashed or the
                controller has lost power. The real protection is a mechanical
                microswitch wired in series with the element contactor. Fit one.

                Set to -1 to disable.

        config KILN_LID_SWITCH_ACTIVE_HIGH
            bool "Lid switch reads HIGH when open"
            default n
            depends on KILN_PIN_LID_SWITCH >= 0
            help
                Leave this off for normally-closed wiring, which is the
                recommended arrangement: lid shut holds the contact closed and
                pulls the input low against the internal pull-up, so a broken
                wire, a pulled connector or a failed switch all read OPEN and
                fail safe.

                Turn it on only if you already have a normally-open switch, and
                understand that a broken wire will then read "lid closed".
```

- [ ] **Step 8: Expose the polarity in app_config.h**

In `components/app_config/include/app_config.h`, in the `--- Optional GPIOs (-1 = disabled) ---` block, after the existing `APP_PIN_LID_SWITCH` line:

```c
#define APP_PIN_LID_SWITCH CONFIG_KILN_PIN_LID_SWITCH
/* True when the switch reads HIGH with the lid open (normally-open wiring).
   The default is normally-closed, which fails safe — see Kconfig help. The
   Kconfig symbol only exists when a lid pin is configured, so default it here
   for the -1 case rather than making every consumer #ifdef. */
#ifdef CONFIG_KILN_LID_SWITCH_ACTIVE_HIGH
#define APP_LID_SWITCH_ACTIVE_HIGH 1
#else
#define APP_LID_SWITCH_ACTIVE_HIGH 0
#endif
```

- [ ] **Step 9: Register the new header with the fixture manifest**

In `tests/host/fixture_sources.txt`, add on its own line next to the existing `components/safety/include/vent_state.h` entry:

```
components/safety/include/lid_state.h
```

- [ ] **Step 10: Format, verify, and commit**

```bash
clang-format -i components/safety/include/lid_state.h components/safety/include/safety_internal.h components/safety/safety_helpers.c components/app_config/include/app_config.h tests/host/test_safety_helpers.c
make test-host
```

Expected: PASS.

```bash
git add components/safety/include/lid_state.h components/safety/include/safety_internal.h components/safety/safety_helpers.c components/app_config/include/app_config.h main/Kconfig.projbuild tests/host/fixture_sources.txt tests/host/test_safety_helpers.c
git commit -m "safety: add a debounced lid-switch state helper and its config (#83)"
```

---

### Task 2: Sample the pin and gate the SSR

**Files:**
- Modify: `components/safety/include/safety.h:37-42, 56-67`
- Modify: `components/safety/safety.c`
- Modify: `main/main.c:78`
- Modify: `tests/host/stubs/safety_host.c`
- Modify: `tests/host/stubs/safety_host.h`

**Interfaces:**
- Consumes: `lid_state_t`, `lid_debounce_t`, `safety_lid_debounce_step()`, `APP_LID_SWITCH_ACTIVE_HIGH` (Task 1).
- Produces: `void safety_init_io(int alarm_gpio, int vent_gpio, int lid_gpio)` (signature change — third parameter added); `lid_state_t safety_get_lid_state(void)`; `void safety_set_lid_interlock_armed(bool armed)`; test hooks `void safety_test_set_lid(lid_state_t state)` and `bool safety_test_lid_interlock_armed(void)`.

- [ ] **Step 1: Extend the public safety header**

In `components/safety/include/safety.h`, add `#include "lid_state.h"` next to the existing `#include "vent_state.h"`, then change the `safety_init_io` declaration and add two functions after `safety_get_vent_state()`:

```c
/**
 * Configure optional alarm, vent and lid-switch GPIOs.
 * Pass -1 to disable any of them.
 * @param alarm_gpio  GPIO for buzzer/relay on error or complete.
 * @param vent_gpio   GPIO for downdraft vent relay (active when firing at <700°C).
 * @param lid_gpio    GPIO input for the lid/door interlock switch. Configured
 *                    with the internal pull-up; polarity from
 *                    APP_LID_SWITCH_ACTIVE_HIGH.
 */
void safety_init_io(int alarm_gpio, int vent_gpio, int lid_gpio);

/**
 * Debounced lid position as of the last safety_task tick, or
 * LID_STATE_NOT_FITTED when no lid GPIO was configured.
 *
 * As with safety_get_vent_state(), this is the sampled pin rather than a
 * re-derivation of anything: an operator looking at a lid indicator wants to
 * know what the switch says.
 */
lid_state_t safety_get_lid_state(void);

/**
 * Arm or disarm the lid interlock's SSR gate.
 *
 * Called by the firing engine whenever settings load or change, with
 * `armed = (lid_mode != LID_MODE_WARN)`. When armed and the lid reads open, the
 * SSR is held low by ssr_window_apply() — the same hard gate the emergency stop
 * uses, so it holds even if the firing task wedges. The mode itself stays in the
 * engine; safety only needs the boolean.
 */
void safety_set_lid_interlock_armed(bool armed);
```

- [ ] **Step 2: Implement in safety.c**

Add near the other statics (after `s_vent_active`, around line 36):

```c
static int s_lid_gpio = -1;
/* Written by safety_task, read by the firing/web/display tasks via
   safety_get_lid_state(); volatile for the same reason s_vent_active is. */
static volatile lid_state_t s_lid_state = LID_STATE_NOT_FITTED;
static volatile bool s_lid_interlock_armed = false;
static lid_debounce_t s_lid_debounce = {.state = LID_STATE_OPEN, .close_samples = 0};
```

Add the raw read and the gate predicate above `ssr_window_apply()`:

```c
/* Polarity-corrected "is the lid open" reading, straight off the pin. */
static bool lid_raw_open(void)
{
    int level = gpio_get_level(s_lid_gpio);
    return APP_LID_SWITCH_ACTIVE_HIGH ? (level != 0) : (level == 0);
}

/* True when the interlock should be holding the element off right now. */
static bool lid_blocks_output(void)
{
    return s_lid_interlock_armed && s_lid_state == LID_STATE_OPEN;
}
```

Extend the guard in `ssr_window_apply()` (currently line 340):

```c
    if (safety_is_emergency() || !s_supervised || lid_blocks_output()) {
        gpio_set_level(s_ssr_pin, 0);
        return;
    }
```

Add the accessors next to `safety_get_vent_state()`:

```c
lid_state_t safety_get_lid_state(void)
{
    return s_lid_state;
}

void safety_set_lid_interlock_armed(bool armed)
{
    s_lid_interlock_armed = armed;
}
```

- [ ] **Step 3: Configure the pin in safety_init_io**

Change the signature to `void safety_init_io(int alarm_gpio, int vent_gpio, int lid_gpio)`, add `s_lid_gpio = lid_gpio;` next to the other assignments, and append after the existing vent block:

```c
    if (lid_gpio >= 0) {
        gpio_config_t io = {
            .pin_bit_mask = (1ULL << lid_gpio),
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&io);
        /* Start from "open" and let safety_task debounce its way to the truth.
           Assuming closed here would allow one unsupervised SSR window against a
           lid that might be up. */
        s_lid_state = LID_STATE_OPEN;
        s_lid_debounce.state = LID_STATE_OPEN;
        s_lid_debounce.close_samples = 0;
        ESP_LOGI(TAG, "Lid switch GPIO %d configured (active %s = open)", lid_gpio,
                 APP_LID_SWITCH_ACTIVE_HIGH ? "high" : "low");
    } else {
        s_lid_state = LID_STATE_NOT_FITTED;
    }
```

- [ ] **Step 4: Sample it in safety_task**

In `safety_task`, immediately after `int64_t now = esp_timer_get_time();`:

```c
        /* Lid switch. Sampled before the thermocouple work so an open lid cuts
           heat on this tick rather than the next one; ssr_window_apply() is what
           actually holds the pin low, within one 100 ms window. */
        if (s_lid_gpio >= 0) {
            lid_state_t lid = safety_lid_debounce_step(&s_lid_debounce, lid_raw_open());
            if (lid != s_lid_state) {
                ESP_LOGI(TAG, "Lid %s", lid == LID_STATE_OPEN ? "opened" : "closed");
            }
            s_lid_state = lid;
        }
```

Add `#include "safety_internal.h"` if not already present (it is, at line 2).

- [ ] **Step 5: Update the one production call site**

In `main/main.c:78`:

```c
    safety_init_io(APP_PIN_ALARM, APP_PIN_VENT, APP_PIN_LID_SWITCH);
```

- [ ] **Step 6: Update the host stub to match**

In `tests/host/stubs/safety_host.c`, add alongside the vent statics:

```c
static lid_state_t s_lid_state = LID_STATE_NOT_FITTED;
static bool s_lid_interlock_armed;
```

Change `safety_init_io` to the three-parameter form and set the lid default:

```c
void safety_init_io(int alarm_gpio, int vent_gpio, int lid_gpio)
{
    (void)alarm_gpio;
    s_vent_fitted = vent_gpio >= 0;
    s_vent_active = false;
    s_lid_state = (lid_gpio >= 0) ? LID_STATE_CLOSED : LID_STATE_NOT_FITTED;
}
```

Add the accessors and test hooks:

```c
lid_state_t safety_get_lid_state(void)
{
    return s_lid_state;
}

void safety_set_lid_interlock_armed(bool armed)
{
    s_lid_interlock_armed = armed;
}

/* Test hook: place the lid directly, bypassing debounce. The debounce itself is
   covered by test_safety_helpers.c; scenario tests care about the settled
   state. Setting a state also marks the switch as fitted. */
void safety_test_set_lid(lid_state_t state)
{
    s_lid_state = state;
}

bool safety_test_lid_interlock_armed(void)
{
    return s_lid_interlock_armed;
}
```

In `safety_test_reset()`, add:

```c
    s_lid_state = LID_STATE_NOT_FITTED;
    s_lid_interlock_armed = false;
```

Mirror the real driver's gate in the stub's `safety_set_ssr()` so scenario tests
see the same behaviour — find the existing emergency check and extend it:

```c
    if (s_emergency || (s_lid_interlock_armed && s_lid_state == LID_STATE_OPEN)) {
        s_last_duty = 0.0f;
        s_ssr_call_count++;
        return;
    }
```

In `tests/host/stubs/safety_host.h`, add:

```c
void safety_test_set_lid(lid_state_t state);
bool safety_test_lid_interlock_armed(void);
```

- [ ] **Step 7: Verify both builds**

```bash
make test-host
```

Expected: PASS (the stub signature now matches the header).

```bash
make firmware
```

Expected: builds clean. This is the step that proves `safety.c` and `main.c` compile — `make test` cannot, since `tests/host/` substitutes the stub.

- [ ] **Step 8: Format and commit**

```bash
clang-format -i components/safety/safety.c components/safety/include/safety.h main/main.c tests/host/stubs/safety_host.c tests/host/stubs/safety_host.h
git add components/safety/safety.c components/safety/include/safety.h main/main.c tests/host/stubs/safety_host.c tests/host/stubs/safety_host.h
git commit -m "safety: sample the lid switch and gate the SSR on it (#83)"
```

---

### Task 3: The `lid_mode` setting

**Files:**
- Modify: `components/firing_engine/include/firing_types.h`
- Modify: `components/firing_engine/firing_engine.c:188-198` (defaults), `:200-234` (NVS load), `:427-436` (NVS save)
- Test: `tests/host/test_firing_scenarios.c`

**Interfaces:**
- Consumes: `safety_set_lid_interlock_armed()` (Task 2).
- Produces: `lid_mode_t { LID_MODE_WARN = 0, LID_MODE_PAUSE, LID_MODE_INTERLOCK }`; `kiln_settings_t.lid_mode`; NVS key `"lid_mode"` (u8).

- [ ] **Step 1: Add the enum and the settings field**

In `components/firing_engine/include/firing_types.h`, immediately before `typedef struct { char temp_unit; ... } kiln_settings_t;`:

```c
/* What an open lid does to a running firing. The mechanism is the same in every
 * case — the element is de-energized — and only the program-clock policy
 * differs, which is why this is one setting rather than a build-time fork.
 *
 * PAUSE is the ceramic-kiln convention: opening the lid mid-firing is abnormal,
 * so the program clock stops with the heat and the segment does not run ahead
 * while the kiln sheds temperature.
 *
 * INTERLOCK is the heat-treat / knife-oven convention: opening the door at full
 * temperature is the normal workflow (pull the blade, quench it), so the program
 * must keep running and only the elements cut out.
 */
typedef enum {
    LID_MODE_WARN = 0,   /* report the lid position, take no control action */
    LID_MODE_PAUSE,      /* elements off, program clock held, auto-resume on close */
    LID_MODE_INTERLOCK,  /* elements off, program clock keeps running */
} lid_mode_t;
```

Add the field to `kiln_settings_t` after `electricity_cost_kwh`:

```c
    lid_mode_t lid_mode; /* behaviour when the lid switch reads open */
```

- [ ] **Step 2: Write the failing test**

Add to `tests/host/test_firing_scenarios.c`, before `main()`:

```c
/* The default matters for anyone who fits a switch without visiting settings:
   pause is the ceramic convention and this is a ceramic-first controller. */
static void test_lid_mode_defaults_to_pause(void)
{
    kiln_settings_t s;
    firing_engine_get_settings(&s);
    TEST_ASSERT_EQUAL_INT(LID_MODE_PAUSE, s.lid_mode);
}

/* The engine owns the mode; safety only ever learns the boolean. Warn must
   leave the SSR gate disarmed or a "report only" mode would cut heat. */
static void test_setting_the_mode_arms_the_safety_gate(void)
{
    kiln_settings_t s;
    firing_engine_get_settings(&s);

    s.lid_mode = LID_MODE_WARN;
    TEST_ASSERT_EQUAL(ESP_OK, firing_engine_set_settings(&s));
    TEST_ASSERT_FALSE(safety_test_lid_interlock_armed());

    s.lid_mode = LID_MODE_PAUSE;
    TEST_ASSERT_EQUAL(ESP_OK, firing_engine_set_settings(&s));
    TEST_ASSERT_TRUE(safety_test_lid_interlock_armed());

    s.lid_mode = LID_MODE_INTERLOCK;
    TEST_ASSERT_EQUAL(ESP_OK, firing_engine_set_settings(&s));
    TEST_ASSERT_TRUE(safety_test_lid_interlock_armed());
}
```

Register both in `main()`:

```c
    RUN_TEST(test_lid_mode_defaults_to_pause);
    RUN_TEST(test_setting_the_mode_arms_the_safety_gate);
```

Ensure `tests/host/stubs/safety_host.h` is included by that file (it already is — it provides `safety_test_vent_active`).

- [ ] **Step 3: Run to verify failure**

```bash
make test-host
```

Expected: FAIL — `kiln_settings_t` has no `lid_mode`, and the default is unset.

- [ ] **Step 4: Default, load, save, and arm**

In `firing_engine.c`, add to the defaults block (after `s_settings.electricity_cost_kwh = 0.15f;`, line 198):

```c
    s_settings.lid_mode = LID_MODE_PAUSE;
```

Add to the NVS load block (after the `elec_c` read):

```c
        if (nvs_get_u8(handle, "lid_mode", &u8) == ESP_OK && u8 <= LID_MODE_INTERLOCK) {
            s_settings.lid_mode = (lid_mode_t)u8;
        }
```

Add to the NVS save block (after the `elec_c` write, line 436):

```c
    nvs_set_u8(handle, "lid_mode", (uint8_t)safe.lid_mode);
```

At the end of `firing_engine_init()`, just before the final `ESP_LOGI`, and at the end of `firing_engine_set_settings()` after the settings are committed:

```c
    safety_set_lid_interlock_armed(s_settings.lid_mode != LID_MODE_WARN);
```

Add `#include "safety.h"` to `firing_engine.c` if not already present.

In `firing_engine_set_settings()`, clamp an out-of-range mode as the other fields are clamped — locate the `safe` copy and add:

```c
    if (safe.lid_mode < LID_MODE_WARN || safe.lid_mode > LID_MODE_INTERLOCK) {
        safe.lid_mode = LID_MODE_PAUSE;
    }
```

- [ ] **Step 5: Run to verify pass**

```bash
make test-host
```

Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
clang-format -i components/firing_engine/include/firing_types.h components/firing_engine/firing_engine.c tests/host/test_firing_scenarios.c
make firmware
git add components/firing_engine/include/firing_types.h components/firing_engine/firing_engine.c tests/host/test_firing_scenarios.c
git commit -m "firing: add the lid_mode setting and arm the safety gate from it (#83)"
```

---

### Task 4: Engine policy and the start refusal

**Files:**
- Modify: `components/firing_engine/firing_engine.c` (engine state struct, `firing_tick`, `FIRING_CMD_START`, `FIRING_CMD_RESUME`)
- Test: `tests/host/test_firing_scenarios.c`

**Interfaces:**
- Consumes: `lid_mode_t`, `safety_get_lid_state()`, `safety_test_set_lid()`.
- Produces: engine state fields `bool lid_paused;` and `lid_state_t lid_prev;`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/host/test_firing_scenarios.c`. These use the file's existing scenario harness — follow the surrounding tests for how a firing is started and ticked (`plant.c` drives the thermal model); the helper names below match the existing ones in that file.

```c
/* ── Lid interlock policy ────────────────────────────────────────────────── */

/* warn mode is exactly what it says: the reading is published and nothing else
   happens. A firing must keep heating with the lid up. */
static void test_lid_warn_mode_takes_no_action(void)
{
    scenario_start_simple_firing(LID_MODE_WARN);
    safety_test_set_lid(LID_STATE_OPEN);
    scenario_tick_seconds(5);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_INT(FIRING_STATUS_HEATING, prog.status);
    TEST_ASSERT_TRUE_MESSAGE(safety_test_last_duty() > 0.0f, "warn mode must not cut the element");
}

/* pause mode: elements off, status PAUSED, and the program clock held. */
static void test_lid_pause_mode_pauses_and_auto_resumes(void)
{
    scenario_start_simple_firing(LID_MODE_PAUSE);
    scenario_tick_seconds(5);

    safety_test_set_lid(LID_STATE_OPEN);
    scenario_tick_seconds(1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_INT(FIRING_STATUS_PAUSED, prog.status);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());
    TEST_ASSERT_TRUE(prog.is_active);

    safety_test_set_lid(LID_STATE_CLOSED);
    scenario_tick_seconds(1);

    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_INT_MESSAGE(FIRING_STATUS_HEATING, prog.status, "closing the lid must resume the firing");
}

/* The load-bearing case: a firing the operator paused by hand must NOT be
   resumed by a lid close. Only a lid-initiated pause auto-resumes. */
static void test_lid_close_does_not_resume_an_operator_pause(void)
{
    scenario_start_simple_firing(LID_MODE_PAUSE);
    scenario_tick_seconds(5);

    scenario_send_cmd(FIRING_CMD_PAUSE);
    scenario_tick_seconds(1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_INT(FIRING_STATUS_PAUSED, prog.status);

    /* Lid opens and closes while the operator's pause stands. */
    safety_test_set_lid(LID_STATE_OPEN);
    scenario_tick_seconds(1);
    safety_test_set_lid(LID_STATE_CLOSED);
    scenario_tick_seconds(1);

    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_INT_MESSAGE(FIRING_STATUS_PAUSED, prog.status,
                                  "a lid close resumed a firing the operator had paused");
}

/* interlock mode: heat off, but the status and the program clock run on — the
   heat-treat convention, where the door is opened at temperature by design. */
static void test_lid_interlock_mode_cuts_heat_but_keeps_the_clock(void)
{
    scenario_start_simple_firing(LID_MODE_INTERLOCK);
    scenario_tick_seconds(5);

    firing_progress_t before;
    firing_engine_get_progress(&before);

    safety_test_set_lid(LID_STATE_OPEN);
    scenario_tick_seconds(10);

    firing_progress_t during;
    firing_engine_get_progress(&during);
    TEST_ASSERT_EQUAL_INT_MESSAGE(FIRING_STATUS_HEATING, during.status, "interlock must not change the status");
    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());
    TEST_ASSERT_TRUE_MESSAGE(during.elapsed_time > before.elapsed_time, "the program clock must keep running");
}

/* The program clock running on is exactly what would otherwise convince the
   not-rising watchdog the kiln has stalled. Closing the lid must restart that
   window rather than let a long, legitimate door-open trip FIRING_ERR_NOT_RISING. */
static void test_lid_interlock_does_not_trip_not_rising(void)
{
    scenario_start_simple_firing(LID_MODE_INTERLOCK);
    scenario_tick_seconds(5);

    safety_test_set_lid(LID_STATE_OPEN);
    scenario_tick_seconds(20 * 60); /* longer than RISING_CHECK_INTERVAL_US */
    safety_test_set_lid(LID_STATE_CLOSED);
    scenario_tick_seconds(60);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_NOT_EQUAL_INT_MESSAGE(FIRING_STATUS_ERROR, prog.status,
                                      "a long interlock hold tripped the not-rising watchdog");
    TEST_ASSERT_EQUAL_INT(FIRING_ERR_NONE, firing_engine_get_error_code());
}

/* Starting into an open lid is refused, so the operator gets an error at the
   moment of the click instead of a firing that silently sits at zero power. */
static void test_start_is_refused_while_the_lid_is_open(void)
{
    safety_test_set_lid(LID_STATE_OPEN);
    scenario_set_lid_mode(LID_MODE_PAUSE);

    scenario_send_start_cmd();
    scenario_tick_seconds(1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_FALSE_MESSAGE(prog.is_active, "the engine started a firing with the lid open");
}

/* warn mode is "report only", so it must not block a start either. */
static void test_start_is_allowed_in_warn_mode_with_the_lid_open(void)
{
    safety_test_set_lid(LID_STATE_OPEN);
    scenario_set_lid_mode(LID_MODE_WARN);

    scenario_send_start_cmd();
    scenario_tick_seconds(1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_TRUE_MESSAGE(prog.is_active, "warn mode must not block a start");
}
```

Register all seven in `main()`.

If `scenario_start_simple_firing`, `scenario_tick_seconds`, `scenario_send_cmd`, `scenario_send_start_cmd`, or `scenario_set_lid_mode` do not exist under those exact names, adapt the tests to the harness that file already uses rather than inventing new helpers — read the existing tests first and match them.

- [ ] **Step 2: Run to verify failure**

```bash
make test-host
```

Expected: FAIL — no lid handling exists in the tick, so pause/interlock assertions fail and the start is not refused.

- [ ] **Step 3: Add the engine state**

In `firing_engine.c`, add to the engine state struct (the one holding `pause_prev_status`, `pause_start_us`, `check_start_time_us`):

```c
    /* True only while the *lid* is what paused this firing. A lid close must not
       resume a pause the operator asked for, so the auto-resume is gated on
       this rather than on status == PAUSED. */
    bool lid_paused;
    /* Debounced lid position observed on the previous tick, so the policy runs
       on transitions rather than every tick. */
    lid_state_t lid_prev;
```

Initialize both where the rest of `s_state` is reset at firing start: `lid_paused = false;` and `lid_prev = safety_get_lid_state();`.

- [ ] **Step 4: Apply the policy in firing_tick**

In `firing_tick()`, insert immediately after the emergency-stop block returns and after `progress_lock()` has published `s_progress.current_temp` — i.e. right before the existing `if (!active || status == FIRING_STATUS_PAUSED || ...)` early-return:

```c
    /* ── Lid interlock ───────────────────────────────────────────────────
     * The element cut itself is safety's job (ssr_window_apply holds the pin
     * low whenever the interlock is armed and the lid is open, which survives a
     * wedged firing task). What happens here is the bookkeeping: firing status
     * and the program clock, per the configured mode. */
    lid_mode_t lid_mode;
    settings_lock();
    lid_mode = s_settings.lid_mode;
    settings_unlock();

    lid_state_t lid_now = safety_get_lid_state();
    bool lid_opened = (lid_now == LID_STATE_OPEN && s_state.lid_prev != LID_STATE_OPEN);
    bool lid_closed = (lid_now == LID_STATE_CLOSED && s_state.lid_prev == LID_STATE_OPEN);
    s_state.lid_prev = lid_now;

    if (lid_mode == LID_MODE_PAUSE && active) {
        if (lid_opened) {
            bool did_pause = false;
            progress_lock();
            if (s_progress.status != FIRING_STATUS_PAUSED) {
                s_state.pause_prev_status = s_progress.status;
                s_progress.status = FIRING_STATUS_PAUSED;
                did_pause = true;
            }
            progress_unlock();
            if (did_pause) {
                safety_set_ssr(0.0f);
                s_state.pause_start_us = now_us;
                s_state.lid_paused = true;
                ESP_LOGI(TAG, "Lid opened: firing paused");
            }
            status = FIRING_STATUS_PAUSED;
        } else if (lid_closed && s_state.lid_paused) {
            progress_lock();
            s_progress.status = s_state.pause_prev_status;
            status = s_state.pause_prev_status;
            progress_unlock();
            /* Same shift FIRING_CMD_RESUME performs, for the same reason: the
               ramp setpoint, not-rising window, runaway baseline and hold timer
               must all resume where they left off. */
            int64_t paused_us = now_us - s_state.pause_start_us;
            if (paused_us > 0) {
                s_state.segment_start_time_us += paused_us;
                s_state.check_start_time_us += paused_us;
                if (s_state.holding) {
                    s_state.segment_hold_start_time_s += (float)paused_us / 1000000.0f;
                }
            }
            s_state.lid_paused = false;
            ESP_LOGI(TAG, "Lid closed: firing resumed");
        }
    } else if (lid_mode == LID_MODE_INTERLOCK && active) {
        if (lid_closed) {
            /* The program clock deliberately ran on while the door was open, so
               the not-rising window has been measuring a kiln that was never
               being heated. Restart it from here or a legitimate door-open trips
               FIRING_ERR_NOT_RISING a few minutes later. */
            s_state.check_start_time_us = now_us;
            s_state.check_start_temp = current_temp;
            ESP_LOGI(TAG, "Lid closed: heat restored");
        }
        if (lid_now == LID_STATE_OPEN) {
            /* Status and the clock are untouched — only the heat stops. */
            safety_set_ssr(0.0f);
            ESP_LOGD(TAG, "Lid open: element held off");
            return;
        }
    }
```

If `settings_lock()`/`settings_unlock()` are not the names used in this file, read the surrounding code and use whatever guards `s_settings` (there is an `s_settings_mutex`).

- [ ] **Step 5: Refuse a start into an open lid**

In the `FIRING_CMD_START` handler, alongside the existing `delay_active` guards:

```c
        /* Refuse rather than start into a firing that would sit at zero power.
           warn mode is "report only" and must not block anything. */
        lid_mode_t start_lid_mode;
        settings_lock();
        start_lid_mode = s_settings.lid_mode;
        settings_unlock();
        if (start_lid_mode != LID_MODE_WARN && safety_get_lid_state() == LID_STATE_OPEN) {
            ESP_LOGW(TAG, "START ignored: lid is open");
            break;
        }
```

- [ ] **Step 6: Clear `lid_paused` on an explicit resume**

In the `FIRING_CMD_RESUME` handler, alongside the existing `did_resume` bookkeeping:

```c
        /* An operator who resumes by hand owns the pause from here on: a later
           lid close must not re-run the auto-resume against a stale timestamp.
           The element stays gated off by safety while the lid is still open. */
        s_state.lid_paused = false;
```

- [ ] **Step 7: Run to verify pass**

```bash
make test-host
```

Expected: PASS, all seven new scenario tests.

- [ ] **Step 8: Format, build, commit**

```bash
clang-format -i components/firing_engine/firing_engine.c tests/host/test_firing_scenarios.c
make firmware
git add components/firing_engine/firing_engine.c tests/host/test_firing_scenarios.c
git commit -m "firing: apply the lid interlock policy and refuse a start with the lid open (#83)"
```

---

### Task 5: JSON contract — `lidOpen` and `lidMode`

**Files:**
- Modify: `components/web_server/include/api_json.h:37-42, 46`
- Modify: `components/web_server/api_json.c:39-82` (`json_add_progress_fields`), `:84-90` (`build_status_json`), `:126-142` (`build_settings_json`)
- Modify: `components/web_server/api_handlers.c:366` (status), `:758-765` (settings PUT), `:596-640` (start)
- Modify: `components/web_server/ws_handler.c:248`
- Test: `tests/host/test_api_json.c`

**Interfaces:**
- Consumes: `lid_state_t`, `lid_mode_t`, `safety_get_lid_state()`.
- Produces: `build_status_json(..., vent_state_t vent, lid_state_t lid)`; `build_ws_temp_update_json(..., vent_state_t vent, lid_state_t lid)`; `const char *lid_mode_to_string(lid_mode_t m)`; `bool lid_mode_from_string(const char *s, lid_mode_t *out)`.

- [ ] **Step 1: Write the failing tests**

In `tests/host/test_api_json.c`, extend `test_status_full_shape` to assert the new key, and add:

```c
/* The lid GPIO defaults to disabled (CONFIG_KILN_PIN_LID_SWITCH = -1), so most
 * kilns have no switch to report on. Sending `lidOpen: false` for those would be
 * indistinguishable from a fitted switch that happens to be closed, and every
 * such kiln would render a dead indicator. Omit the key entirely instead —
 * the same contract ventActive follows. */
static void test_status_omits_lid_when_not_fitted(void)
{
    firing_progress_t prog = {.is_active = false, .status = FIRING_STATUS_IDLE};
    thermocouple_reading_t tc = {.temperature_c = 22.0f};
    cJSON *root = build_status_json(&prog, &tc, 0.0f, 0.0f, VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED);

    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "lidOpen"));
    /* Everything else is still there — a missing lid switch is not a degraded status. */
    assert_bool_field(root, "isActive");
    TEST_ASSERT_NOT_NULL(cJSON_GetObjectItem(root, "status"));

    dump_fixture("status_no_lid", root);
    cJSON_Delete(root);
}

static void test_status_reports_an_open_lid(void)
{
    firing_progress_t prog = {.is_active = true, .status = FIRING_STATUS_PAUSED};
    thermocouple_reading_t tc = {.temperature_c = 640.0f};
    cJSON *root = build_status_json(&prog, &tc, 0.0f, 0.0f, VENT_STATE_ON, LID_STATE_OPEN);

    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "lidOpen")));

    dump_fixture("status_lid_open", root);
    cJSON_Delete(root);
}

static void test_status_reports_a_closed_lid(void)
{
    firing_progress_t prog = {.is_active = true, .status = FIRING_STATUS_HEATING};
    thermocouple_reading_t tc = {.temperature_c = 640.0f};
    cJSON *root = build_status_json(&prog, &tc, 0.0f, 0.5f, VENT_STATE_ON, LID_STATE_CLOSED);

    cJSON *j = cJSON_GetObjectItem(root, "lidOpen");
    TEST_ASSERT_NOT_NULL(j);
    TEST_ASSERT_TRUE(cJSON_IsFalse(j));
    cJSON_Delete(root);
}

/* lidMode is a setting, not a hardware reading, so unlike lidOpen it is always
   present — a client needs to render the selector whether or not a switch is
   fitted. */
static void test_settings_always_carry_the_lid_mode(void)
{
    kiln_settings_t s = {.temp_unit = 'C', .max_safe_temp = 1300.0f, .lid_mode = LID_MODE_INTERLOCK};
    cJSON *root = build_settings_json(&s);

    cJSON *j = cJSON_GetObjectItem(root, "lidMode");
    TEST_ASSERT_NOT_NULL(j);
    TEST_ASSERT_TRUE(cJSON_IsString(j));
    TEST_ASSERT_EQUAL_STRING("interlock", cJSON_GetStringValue(j));
    cJSON_Delete(root);
}

static void test_lid_mode_string_round_trip(void)
{
    const lid_mode_t modes[] = {LID_MODE_WARN, LID_MODE_PAUSE, LID_MODE_INTERLOCK};
    for (unsigned i = 0; i < sizeof(modes) / sizeof(modes[0]); i++) {
        lid_mode_t back;
        TEST_ASSERT_TRUE(lid_mode_from_string(lid_mode_to_string(modes[i]), &back));
        TEST_ASSERT_EQUAL_INT(modes[i], back);
    }
    lid_mode_t unused;
    TEST_ASSERT_FALSE_MESSAGE(lid_mode_from_string("ajar", &unused), "unknown modes must be rejected, not defaulted");
}
```

Extend the existing `assert_ws_and_status_agree(vent_state_t vent)` helper to take a lid too, so the WS frame and `/status` are checked against the same expectations:

```c
static void assert_ws_and_status_agree(vent_state_t vent, lid_state_t lid)
{
    /* ...existing body, with both builders given `lid`... */
    cJSON *status = build_status_json(&prog, &tc, 0.0f, 0.5f, vent, lid);
    cJSON *frame = build_ws_temp_update_json(&prog, 480.0f, 0.5f, vent, lid);
    /* ...existing key-by-key comparison, which now covers lidOpen for free... */
}
```

and call it with the lid variants alongside the existing vent ones:

```c
    assert_ws_and_status_agree(VENT_STATE_ON, LID_STATE_CLOSED);
    assert_ws_and_status_agree(VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED);
    assert_ws_and_status_agree(VENT_STATE_OFF, LID_STATE_OPEN);
```

Register the new tests in `main()`. Update **every** existing `build_status_json(...)` and `build_ws_temp_update_json(...)` call in this file to pass a lid argument — `LID_STATE_NOT_FITTED` for the ones that predate this feature, so their fixtures keep their current shape.

- [ ] **Step 2: Run to verify failure**

```bash
make test-host
```

Expected: FAIL — too many arguments to `build_status_json`, `lid_mode_to_string` undeclared.

- [ ] **Step 3: Extend the JSON builders**

In `components/web_server/include/api_json.h`, add `#include "lid_state.h"` next to `#include "vent_state.h"`, update the two declarations, and add the mode helpers:

```c
cJSON *build_status_json(const firing_progress_t *prog, const thermocouple_reading_t *tc, float tc_offset_c,
                         float ssr_duty, vent_state_t vent, lid_state_t lid);

/** Wire name for a lid mode: "warn" | "pause" | "interlock". */
const char *lid_mode_to_string(lid_mode_t m);

/** Parse a wire name into a lid mode. Returns false for anything unrecognized —
 *  callers answer with 400 rather than silently defaulting, so a client typo
 *  cannot quietly disarm an interlock. */
bool lid_mode_from_string(const char *s, lid_mode_t *out);
```

Update the `build_ws_temp_update_json` declaration in the same header the same way (add `lid_state_t lid` as the final parameter).

In `components/web_server/api_json.c`, change `json_add_progress_fields` to take `lid_state_t lid` as its final parameter and add, immediately after the `ventActive` block:

```c
    /* Lid/door interlock switch (#83). Omitted rather than sent false when no
       switch is fitted, for exactly the reason ventActive is: "the lid is shut"
       and "this kiln has no lid switch" are different facts, and a client that
       saw `false` either way would render a dead indicator on every kiln that
       never had the hardware. */
    if (lid != LID_STATE_NOT_FITTED) {
        cJSON_AddBoolToObject(target, "lidOpen", lid == LID_STATE_OPEN);
    }
```

Thread `lid` through `build_status_json` and `build_ws_temp_update_json` to that call.

Add the mode helpers near `firing_status_to_string`:

```c
const char *lid_mode_to_string(lid_mode_t m)
{
    switch (m) {
    case LID_MODE_WARN:
        return "warn";
    case LID_MODE_PAUSE:
        return "pause";
    case LID_MODE_INTERLOCK:
        return "interlock";
    default:
        return "pause";
    }
}

bool lid_mode_from_string(const char *s, lid_mode_t *out)
{
    if (!s || !out) {
        return false;
    }
    if (strcmp(s, "warn") == 0) {
        *out = LID_MODE_WARN;
    } else if (strcmp(s, "pause") == 0) {
        *out = LID_MODE_PAUSE;
    } else if (strcmp(s, "interlock") == 0) {
        *out = LID_MODE_INTERLOCK;
    } else {
        return false;
    }
    return true;
}
```

Add to `build_settings_json`, after `electricityCostKwh`:

```c
    cJSON_AddStringToObject(root, "lidMode", lid_mode_to_string(settings->lid_mode));
```

- [ ] **Step 4: Run to verify pass**

```bash
make test-host
```

Expected: PASS.

- [ ] **Step 5: Update the handlers**

`components/web_server/api_handlers.c:366` — pass the lid state:

```c
    return send_json(req, build_status_json(&prog, &tc, settings.tc_offset_c, safety_get_ssr_duty(),
                                            safety_get_vent_state(), safety_get_lid_state()));
```

`components/web_server/ws_handler.c:248`:

```c
    cJSON *root = build_ws_temp_update_json(&prog, adjusted_temp, safety_get_ssr_duty(), safety_get_vent_state(),
                                            safety_get_lid_state());
```

Settings PUT — add after the `electricityCostKwh` block (~line 762):

```c
    j = cJSON_GetObjectItem(root, "lidMode");
    if (cJSON_IsString(j)) {
        lid_mode_t mode;
        if (!lid_mode_from_string(cJSON_GetStringValue(j), &mode)) {
            cJSON_Delete(root);
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid lidMode");
            return ESP_FAIL;
        }
        settings.lid_mode = mode;
    }
```

Match the surrounding code's cleanup convention exactly — read how the neighbouring `apiToken` length check frees `root` before returning and mirror it.

Start handler — add after the relay-test 409 block (~line 604):

```c
    /* A firing started into an open lid would sit at zero power with no visible
       cause; answer at the moment of the click instead. warn mode is report-only
       and deliberately does not block. */
    kiln_settings_t lid_settings;
    firing_engine_get_settings(&lid_settings);
    if (lid_settings.lid_mode != LID_MODE_WARN && safety_get_lid_state() == LID_STATE_OPEN) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_send(req, "Lid is open", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }
```

- [ ] **Step 6: Regenerate fixtures and verify both builds**

```bash
make fixtures
make test-host
make firmware
```

Expected: all pass. `make firmware` is essential here — `api_handlers.c` and `ws_handler.c` are not in the host build.

- [ ] **Step 7: Format and commit**

```bash
clang-format -i components/web_server/api_json.c components/web_server/include/api_json.h components/web_server/api_handlers.c components/web_server/ws_handler.c tests/host/test_api_json.c
git add components/web_server tests/host/test_api_json.c
git commit -m "api: publish lidOpen and lidMode, and 409 a start with the lid open (#83)"
```

---

### Task 6: Web UI

**Files:**
- Modify: `web_ui/src/app/schemas/api.ts:49`, `web_ui/src/app/schemas/ws.ts:33,55`
- Modify: `web_ui/src/app/types/kiln.ts:97`
- Modify: `web_ui/src/app/stores/kilnStore.ts:66,184,287`
- Modify: `web_ui/src/app/components/FiringDashboard.tsx:384-400`
- Modify: the Settings component (find it under `web_ui/src/app/components/`)
- Modify: `web_ui/mock-server/simulator.ts:464,493`
- Test: `web_ui/src/app/stores/kilnStore.test.ts`, plus a new `FiringDashboard` test

**Interfaces:**
- Consumes: the `lidOpen` / `lidMode` fixtures from Task 5.
- Produces: `lidOpen: boolean | null` on the store's `firingProgress`; `lidMode: "warn" | "pause" | "interlock"` on settings.

- [ ] **Step 1: Write the failing tests**

Add to `web_ui/src/app/stores/kilnStore.test.ts`, mirroring the existing `ventActive` tests:

```ts
it("maps lidOpen from the websocket frame", () => {
  wsSubscriber!(tempFrame({ lidOpen: true, isActive: true, status: "heating" }));
  expect(useKilnStore.getState().firingProgress.lidOpen).toBe(true);
  wsSubscriber!(tempFrame({ lidOpen: false, isActive: true, status: "heating" }));
  expect(useKilnStore.getState().firingProgress.lidOpen).toBe(false);
});

// A kiln with no lid switch omits the key entirely. That must read as "no
// hardware" (null), not as "lid closed" (false) — the dashboard keys its
// indicator off exactly this distinction.
it("nulls lidOpen when the firmware omits it", () => {
  wsSubscriber!(tempFrame({ isActive: true, status: "heating" }));
  expect(useKilnStore.getState().firingProgress.lidOpen).toBeNull();
});
```

Create `web_ui/src/app/components/FiringDashboard.lid.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FiringDashboard } from "./FiringDashboard";
import { queryWrapper } from "../test/queryWrapper";
import { useKilnStore } from "../stores/kilnStore";

describe("FiringDashboard lid indicator", () => {
  it("shows nothing when no lid switch is fitted", () => {
    useKilnStore.setState((s) => ({ firingProgress: { ...s.firingProgress, lidOpen: null } }));
    render(<FiringDashboard />, { wrapper: queryWrapper() });
    expect(screen.queryByText(/lid/i)).not.toBeInTheDocument();
  });

  it("reports an open lid", () => {
    useKilnStore.setState((s) => ({ firingProgress: { ...s.firingProgress, lidOpen: true } }));
    render(<FiringDashboard />, { wrapper: queryWrapper() });
    expect(screen.getByText(/lid open/i)).toBeInTheDocument();
  });

  it("reports a closed lid", () => {
    useKilnStore.setState((s) => ({ firingProgress: { ...s.firingProgress, lidOpen: false } }));
    render(<FiringDashboard />, { wrapper: queryWrapper() });
    expect(screen.getByText(/lid closed/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
make test-web
```

Expected: FAIL — `lidOpen` is not on the store type, and the contract test fails because the new fixture fields are unmodelled under `.strict()`.

- [ ] **Step 3: Model the fields**

`web_ui/src/app/schemas/api.ts` — add beside `ventActive`:

```ts
  lidOpen: z.boolean().optional(),
```

and to the settings schema:

```ts
  lidMode: z.enum(["warn", "pause", "interlock"]),
```

`web_ui/src/app/schemas/ws.ts` — add `lidOpen: z.boolean().optional(),` beside `ventActive`, and extend the comment at line 33 to name `lidOpen` as the second field the firmware genuinely omits.

`web_ui/src/app/types/kiln.ts:97` — add beside `ventActive`:

```ts
  lidOpen: boolean | null;
```

`web_ui/src/app/stores/kilnStore.ts` — add `lidOpen: null,` to the initial state (line 66) and `lidOpen: s.lidOpen ?? null,` / `lidOpen: d.lidOpen ?? null,` at the two mapping sites (lines 184 and 287).

- [ ] **Step 4: Render the indicator**

In `web_ui/src/app/components/FiringDashboard.tsx`, add a badge beside the existing vent badge (lines 384-400), matching its structure and class names exactly:

```tsx
{firingProgress.lidOpen !== null && (
  <div
    className={cn(
      "flex items-center gap-1.5",
      firingProgress.lidOpen ? "text-foreground" : "text-muted-foreground",
    )}
  >
    <DoorOpen
      className={cn("h-4 w-4", firingProgress.lidOpen ? "text-amber-500" : "text-muted-foreground")}
    />
    Lid {firingProgress.lidOpen ? "open" : "closed"}
  </div>
)}
```

Import `DoorOpen` from `lucide-react` alongside the icon the vent badge already uses.

- [ ] **Step 5: Add the settings selector**

In the Settings component, add a mode selector next to the other kiln settings, using whatever Select primitive the file already uses. The copy must explain the split, since the choice is not self-evident:

- **Warn** — "Show the lid position, but never interrupt a firing."
- **Pause** — "Cut the elements and hold the program while the lid is open. Resumes automatically. Recommended for ceramics."
- **Interlock** — "Cut the elements but keep the program running. Recommended for heat treating, where the door is opened at temperature by design."

Include a line below the selector: "Not a substitute for a mechanical interlock wired into the element circuit."

- [ ] **Step 6: Emit it from the mock server**

In `web_ui/mock-server/simulator.ts`, mirror the `publishedVentActive()` treatment at lines 464 and 493 with a `publishedLidOpen()` and a settable lid position, so the UI can be exercised without hardware.

- [ ] **Step 7: Run to verify pass**

```bash
make test-web
```

Expected: PASS.

```bash
cd web_ui && npm run typecheck && npm run lint
```

Expected: clean.

- [ ] **Step 8: Verify the demo build still works**

```bash
make web-demo
```

Expected: builds. The demo bundle is tree-shaken out of every other build, so only this target catches a break in it.

- [ ] **Step 9: Commit**

```bash
git add web_ui
git commit -m "web: surface the lid switch state and its mode setting (#83)"
```

---

### Task 7: iOS app

**Files:**
- Modify: the `Codable` status/settings models under `ios/Bisque/Bisque/` (find them by grepping for `ventActive`)
- Modify: `ios/Bisque/BisqueTests/FirmwareContractTests.swift`

**Interfaces:**
- Consumes: the `status_lid_open` and `status_no_lid` fixtures from Task 5.

- [ ] **Step 1: Run the contract tests to see them fail**

```bash
make test-ios
```

Expected: FAIL — the new fixtures are in none of the three tables (`decoded`, `notModelled`, `knownUnmodelled`), which is exactly the designed failure.

- [ ] **Step 2: Model the fields**

Add `lidOpen: Bool?` to the status model beside `ventActive` (optional, because the firmware omits it when no switch is fitted), and `lidMode: String` to the settings model.

- [ ] **Step 3: Register the fixtures**

Add `status_lid_open` and `status_no_lid` to the `decoded` table in `FirmwareContractTests.swift`. If the app does not consume `lidMode`, list it in `knownUnmodelled` rather than leaving it silently dropped — `Codable` ignores unknown keys, so that table is the Swift stand-in for the web schemas' `.strict()` pass.

- [ ] **Step 4: Run to verify pass**

```bash
make test-ios
```

Expected: PASS.

Do **not** override `setUp()`/`tearDown()` in any new test — they are nonisolated in Xcode 16's XCTest (what CI uses) and `@MainActor` in Xcode 26's (what a current Mac has), so an override touching `@MainActor` state builds locally and fails CI. Set fixtures up inside each test.

- [ ] **Step 5: Commit**

```bash
git add ios
git commit -m "ios: model the lid switch fields in the firmware contract (#83)"
```

---

### Task 8: LVGL dashboard, simulator, and docs

**Files:**
- Modify: `components/display/include/dashboard.h:29`
- Modify: `components/display/dashboard.c:59-64, 205-215, 698-711, 735, 786-818`
- Modify: `components/display/display_task.c:61`
- Modify: `simulator/main.c:122, 188, 665`
- Modify: `CLAUDE.md`
- Modify: `docs/screenshots/lcd-*.png` (regenerated)

**Interfaces:**
- Consumes: `lid_state_t`, `safety_get_lid_state()`.
- Produces: `void dashboard_update(const thermocouple_reading_t *tc, const firing_progress_t *prog, vent_state_t vent, lid_state_t lid)`.

- [ ] **Step 1: Add the badge**

In `dashboard.c`, add statics beside the vent ones:

```c
/* Lid interlock indicator, parked in the status bar beside the vent marker and
 * created at the same time, so it survives every layout swap — the lid can open
 * during any firing state. */
static lv_obj_t *s_lid_label = NULL;
static bool s_lid_shown = false;
```

Create it in the same place the vent label is created (~line 699), using `ui_make_label` and the same style calls, with text `"LID"` and `UI_COLOR_HEATING` as its background so it reads as a warning rather than a status. Align it to the left of `s_vent_label` in `align_vent_label()` (rename the function to `align_status_markers()` and re-park both), and extend `dashboard_update()`:

```c
void dashboard_update(const thermocouple_reading_t *tc, const firing_progress_t *prog, vent_state_t vent,
                      lid_state_t lid)
```

with, beside the vent block:

```c
    /* Lid indicator. Shown only while the lid is actually open: a kiln with no
     * lid GPIO (the default) reports LID_STATE_NOT_FITTED and must never see the
     * label, and a fitted-but-closed lid has nothing to announce. */
    bool show_lid = (lid == LID_STATE_OPEN);
    if (show_lid != s_lid_shown) {
        if (show_lid) {
            lv_obj_clear_flag(s_lid_label, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(s_lid_label, LV_OBJ_FLAG_HIDDEN);
        }
        s_lid_shown = show_lid;
    }
```

Update the declaration in `dashboard.h:29` to match.

- [ ] **Step 2: Update both call sites**

`components/display/display_task.c:61`:

```c
    dashboard_update(&tc, &prog, safety_get_vent_state(), safety_get_lid_state());
```

`simulator/main.c` — add `static lid_state_t s_lid = LID_STATE_NOT_FITTED;` beside `s_vent` (line 122) and pass it at both `dashboard_update()` call sites (lines 188 and 665).

- [ ] **Step 3: Add a `--verify` state check**

In `simulator/main.c`'s verify path, add a sequence that drives the lid open and then closed and asserts the badge's hidden flag flips both ways. This belongs in `--verify` rather than as a new screenshot baseline because it is about *state surviving a transition* — a badge that appears and never clears renders identically to a correct one in any single capture.

- [ ] **Step 4: Run the simulator checks**

```bash
make sim-verify
```

Expected: PASS, including the new lid assertions.

```bash
make sim
```

Expected: the pixel diff fails on any scene whose status bar now differs. Inspect the diff, confirm the change is the intended badge, then rebaseline:

```bash
cd simulator/build && ./bisque_sim --screenshot
```

Eyeball the regenerated `docs/screenshots/lcd-*.png` — the README screenshots come from these same files.

- [ ] **Step 5: Document it**

Add to `CLAUDE.md` under the Display / UI System hardware notes, beside the existing optional-GPIO material: one short paragraph naming the lid switch, its three modes, the safety/engine split, and the "not a safety device" caveat.

- [ ] **Step 6: Full verification**

```bash
make ci
```

Expected: PASS. This is the closest local approximation of the PR check.

```bash
make clang-tidy
```

Filter to this repo's own findings — the header filter matches ESP-IDF's `components/` too, so most output is not yours:

```bash
grep -E ':[0-9]+:[0-9]+: (warning|error): ' warnings.txt | grep -v clang-diagnostic- | grep "$PWD/\(components\|main\)/"
```

Expected: no new findings. Watch for `readability-redundant-declaration` — it is an error here, and this change adds functions to several headers.

```bash
make cppcheck
```

- [ ] **Step 7: Commit**

```bash
clang-format -i components/display/dashboard.c components/display/include/dashboard.h components/display/display_task.c simulator/main.c
git add components/display simulator docs/screenshots CLAUDE.md
git commit -m "display: show a lid indicator on the LCD status bar (#83)"
```

---

## Self-Review

**Spec coverage:** Every spec section maps to a task — config and the shared type to Task 1; sampling, debounce and the SSR gate to Task 2; the mode setting to Task 3; engine policy, the `lid_paused` interaction and the NOT_RISING reset to Task 4; the start gate split across Tasks 4 (engine) and 5 (HTTP 409); reporting to Tasks 5–8; the "not a safety device" framing to Tasks 1 (Kconfig), 6 (settings copy) and 8 (CLAUDE.md). The spec's "out of scope" items are correctly absent.

**Known soft spot:** Task 4's tests assume scenario-harness helper names (`scenario_start_simple_firing`, `scenario_tick_seconds`, `scenario_send_cmd`, `scenario_send_start_cmd`, `scenario_set_lid_mode`) that were not verified against `tests/host/test_firing_scenarios.c`. The task says to read the existing tests and match the real harness rather than invent helpers — the implementer must do that first.

**Type consistency:** `lid_state_t` / `lid_mode_t` / `lid_debounce_t`, `safety_get_lid_state()`, `safety_set_lid_interlock_armed()`, `safety_lid_debounce_step()`, `lid_mode_to_string()`, `lid_mode_from_string()`, `safety_test_set_lid()`, and `safety_test_lid_interlock_armed()` are each defined in exactly one task and used consistently. `lidOpen` and `lidMode` keep the same spelling and optionality across C, TypeScript and Swift.
