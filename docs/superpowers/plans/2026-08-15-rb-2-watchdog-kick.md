# RB-2: Hardware Watchdog Kick Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toggle `KILN_PIN_WDT_KICK` (GPIO 36) so the charge pump gating both SSR channels stays energized while — and only while — the firmware is demonstrably healthy, letting rev B boards run without the SJ2 "WDT DEFEAT" jumper.

**Architecture:** A liveness **heartbeat** written by `safety_task` and a **kick** emitted by the existing 100 ms SSR timer. The timer toggles the pin only if the heartbeat is fresh and no emergency stop is latched. Splitting it this way is the whole design: a kick emitted directly from a timer would keep toggling after `safety_task` died, which is precisely the failure the hardware exists to catch.

**Tech Stack:** ESP-IDF `esp_timer`, `driver/gpio.h`, Unity host tests.

**Issue:** [#307](https://github.com/BenSeverson/bisque/issues/307)

**Spec:** [`docs/firmware-backlog.md`](../../firmware-backlog.md) RB-2

## Global Constraints

- **The pump needs transitions.** A pin held high fails identically to a pin that stopped moving. Any implementation that "sets the pin high when healthy" is wrong.
- **The kick must stop when the system is unhealthy.** A kicker driven unconditionally from a timer silently defeats the hardware interlock and is worse than no watchdog, because the board then *appears* protected.
- **Lid-open must NOT stop the kick.** An open lid in `pause` or `warn` mode is a normal operating condition, not a fault; `ssr_window_apply()` already holds the SSR low in software. Stopping the pump there would add re-charge latency on lid close and would make `warn` mode — which is specified not to cut heat — cut heat anyway.
- `CONFIG_KILN_PIN_WDT_KICK` may be `-1` (hardware without the circuit, and every rev A build). Everything here must no-op cleanly in that case.
- After editing any firmware C/H file, run `clang-format -i` on it.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `components/safety/wdt_kick.h` (new) | The liveness decision as a pure function — no ESP-IDF, caller-supplied state |
| `tests/host/test_wdt_kick.c` (new) | Unity tests for the decision, including the stale-heartbeat case |
| `components/safety/safety.c` | Pin init, heartbeat write in `safety_task`, toggle in `ssr_timer_cb` |
| `components/safety/include/safety.h` | `safety_init_wdt()` declaration |
| `main/main.c` | Pass `APP_PIN_WDT_KICK` at startup |
| `tests/host/CMakeLists.txt` | Register the new test binary |

The decision is split out for the same reason `log_sink.c` and `safety_helpers.c` are: it is the part with the interesting failure modes and the part a host test can reach.

---

### Task 1: The liveness decision, host-tested

**Files:**
- Create: `components/safety/wdt_kick.h`
- Create: `tests/host/test_wdt_kick.c`
- Modify: `tests/host/CMakeLists.txt`

**Interfaces:**
- Produces: `bool wdt_kick_allowed(int64_t now_us, int64_t last_heartbeat_us, bool emergency)` and `WDT_HEARTBEAT_TIMEOUT_US`. Task 2 calls both.

- [ ] **Step 1: Write the failing test**

```c
/* tests/host/test_wdt_kick.c */
#include "unity.h"
#include "wdt_kick.h"

#define SEC 1000000LL

static void test_fresh_heartbeat_kicks(void)
{
    TEST_ASSERT_TRUE(wdt_kick_allowed(10 * SEC, 10 * SEC, false));
}

/* safety_task runs at 500 ms. One missed cycle is jitter, not death. */
static void test_one_missed_cycle_still_kicks(void)
{
    TEST_ASSERT_TRUE(wdt_kick_allowed(10 * SEC + 600000, 10 * SEC, false));
}

/* This is the case the hardware exists for: the task stopped, so the kick
   must stop, so the pump decays and both SSRs de-energize. */
static void test_stale_heartbeat_stops_the_kick(void)
{
    TEST_ASSERT_FALSE(wdt_kick_allowed(20 * SEC, 10 * SEC, false));
}

static void test_emergency_stops_the_kick(void)
{
    TEST_ASSERT_FALSE(wdt_kick_allowed(10 * SEC, 10 * SEC, true));
}

/* Before safety_task's first pass the heartbeat is 0. That must read as
   stale, not as "1970 was a long time ago but the arithmetic works out" —
   the element has no supervision yet. */
static void test_unset_heartbeat_stops_the_kick(void)
{
    TEST_ASSERT_FALSE(wdt_kick_allowed(10 * SEC, 0, false));
}

/* The timeout must be shorter than the pump's ~1 s decay, or the firmware
   concludes it is unhealthy only after the hardware has already cut power —
   which works, but reports the wrong cause. */
static void test_timeout_is_shorter_than_pump_decay(void)
{
    TEST_ASSERT_LESS_THAN_INT64(1000000LL, WDT_HEARTBEAT_TIMEOUT_US);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_fresh_heartbeat_kicks);
    RUN_TEST(test_one_missed_cycle_still_kicks);
    RUN_TEST(test_stale_heartbeat_stops_the_kick);
    RUN_TEST(test_emergency_stops_the_kick);
    RUN_TEST(test_unset_heartbeat_stops_the_kick);
    RUN_TEST(test_timeout_is_shorter_than_pump_decay);
    return UNITY_END();
}
```

- [ ] **Step 2: Run it and confirm it fails to build**

```bash
make test-host
```

Expected: failure — `wdt_kick.h` does not exist.

- [ ] **Step 3: Write the header**

```c
/* components/safety/wdt_kick.h
 *
 * The liveness half of the hardware watchdog (RB-2). Kept free of ESP-IDF so
 * tests/host/test_wdt_kick.c can drive it; safety.c owns the pin and the
 * timer.
 *
 * The charge pump on KILN_PIN_WDT_KICK gates BOTH SSR opto channels and
 * needs TRANSITIONS — a stuck-high pin decays exactly like a stopped one.
 * So the question this file answers is not "is the output on" but "is the
 * firmware still alive enough to be allowed to heat".
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* safety_task runs every 500 ms. 900 ms tolerates one missed cycle plus
   scheduling jitter, and still lands inside the pump's ~1 s decay so the
   firmware notices before the hardware acts. */
#define WDT_HEARTBEAT_TIMEOUT_US 900000LL

/* True when the kick may toggle this tick.
 *
 * last_heartbeat_us of 0 means safety_task has not completed a pass yet and
 * is deliberately treated as stale: the element is unsupervised then, which
 * is the same reason s_supervised gates ssr_window_apply().
 *
 * Note what is NOT here: an open lid. That is a normal operating condition
 * in warn and pause modes, ssr_window_apply() already holds the SSR low for
 * it in software, and cutting the pump would both add re-charge latency on
 * close and make warn mode cut heat, which is exactly what warn means not to
 * do. */
static inline bool wdt_kick_allowed(int64_t now_us, int64_t last_heartbeat_us, bool emergency)
{
    if (emergency) {
        return false;
    }
    if (last_heartbeat_us <= 0) {
        return false;
    }
    return (now_us - last_heartbeat_us) < WDT_HEARTBEAT_TIMEOUT_US;
}
```

- [ ] **Step 4: Register the test**

In `tests/host/CMakeLists.txt`, copy the `test_log_sink` block, rename to `test_wdt_kick`, and put `components/safety` on its include path.

- [ ] **Step 5: Run and confirm green**

```bash
make test-host
```

Expected: the six new tests pass alongside the existing suite.

- [ ] **Step 6: Commit**

```bash
git add components/safety/wdt_kick.h tests/host/test_wdt_kick.c tests/host/CMakeLists.txt
git commit -m "feat(safety): the watchdog's liveness rule, host-tested

The charge pump gating both SSR channels needs transitions, so the
question is not whether the output is on but whether the firmware is
alive enough to be allowed to heat. That decision is a pure function here
so a test can drive the case that matters: heartbeat goes stale, kick
stops, pump decays, elements drop.

An unset heartbeat counts as stale rather than as a very old timestamp —
before safety_task's first pass the element is unsupervised, the same
condition s_supervised already gates ssr_window_apply() on.

Lid state is deliberately absent: an open lid is normal in warn and pause
modes and is already handled in software, and cutting the pump would make
warn mode cut heat.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Wire it into `safety.c`

**Files:**
- Modify: `components/safety/safety.c`
- Modify: `components/safety/include/safety.h`
- Modify: `main/main.c`

**Interfaces:**
- Consumes: `wdt_kick_allowed()`, `WDT_HEARTBEAT_TIMEOUT_US` from Task 1.
- Produces: `void safety_init_wdt(int wdt_gpio);` — called once from `app_main` after `safety_init()`.

- [ ] **Step 1: Add the state and the init**

In `safety.c`, near `static int s_ssr_pin = -1;`:

```c
static int s_wdt_gpio = -1;
static bool s_wdt_level;
/* Written by safety_task at the end of each completed pass, read by the SSR
   timer callback. int64_t writes are not atomic on a 32-bit core, so this
   goes under the existing spinlock rather than being declared volatile and
   hoped about. */
static int64_t s_wdt_heartbeat_us;
```

And the init function:

```c
void safety_init_wdt(int wdt_gpio)
{
    s_wdt_gpio = wdt_gpio;
    if (wdt_gpio < 0) {
        ESP_LOGW(TAG, "No WDT kick pin configured; the board needs the SJ2 "
                      "WDT DEFEAT jumper fitted or it will not heat");
        return;
    }
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << wdt_gpio,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
    s_wdt_level = false;
    gpio_set_level(wdt_gpio, 0);
    ESP_LOGI(TAG, "WDT kick on GPIO %d", wdt_gpio);
}
```

- [ ] **Step 2: Declare it**

In `safety.h`, beside `safety_init_io`:

```c
/**
 * Configure the hardware watchdog kick output.
 *
 * The pin feeds a charge pump that gates BOTH SSR opto channels: if it stops
 * transitioning, or wedges at either level, both SSRs de-energize within
 * about a second regardless of what firmware commands.
 *
 * Pass -1 on hardware without the circuit. A board with neither the kick nor
 * the SJ2 "WDT DEFEAT" jumper will not heat.
 */
void safety_init_wdt(int wdt_gpio);
```

- [ ] **Step 3: Emit the kick from the existing SSR timer**

`ssr_timer_cb` already fires on the 100 ms window and calls `ssr_window_apply()`. Add the kick beside it:

```c
static void wdt_kick_step(void)
{
    if (s_wdt_gpio < 0) {
        return;
    }
    int64_t hb;
    portENTER_CRITICAL(&s_safety_mux);
    hb = s_wdt_heartbeat_us;
    portEXIT_CRITICAL(&s_safety_mux);

    if (!wdt_kick_allowed(esp_timer_get_time(), hb, safety_is_emergency())) {
        /* Stop toggling and leave the level where it is. Do NOT drive it to a
           defined level "for safety" — the pump decays on absence of edges,
           so holding a level is the same as stopping, and pretending
           otherwise invites someone to add a gpio_set_level here later. */
        return;
    }
    s_wdt_level = !s_wdt_level;
    gpio_set_level(s_wdt_gpio, s_wdt_level ? 1 : 0);
}
```

and call it from `ssr_timer_cb`:

```c
static void ssr_timer_cb(void *arg)
{
    (void)arg;
    ssr_window_apply();
    wdt_kick_step();
}
```

- [ ] **Step 4: Write the heartbeat from `safety_task`**

At the **end** of `safety_task`'s `for(;;)` body — after every check has run, immediately before `xTaskDelayUntil` — so the heartbeat means "a full supervision pass completed", not "the loop was entered":

```c
        portENTER_CRITICAL(&s_safety_mux);
        s_wdt_heartbeat_us = esp_timer_get_time();
        portEXIT_CRITICAL(&s_safety_mux);
```

- [ ] **Step 5: Call it from `app_main`**

In `main/main.c`, after `safety_init_io(...)`:

```c
    safety_init_wdt(APP_PIN_WDT_KICK);
```

- [ ] **Step 6: Format, build, test**

```bash
clang-format -i components/safety/safety.c components/safety/include/safety.h components/safety/wdt_kick.h main/main.c
make firmware
make test
```

Expected: builds clean; full suite passes.

- [ ] **Step 7: Commit**

```bash
git add components/safety/ main/main.c
git commit -m "feat(safety): kick the hardware watchdog, and stop when wedged

Rev B gates both SSR opto channels behind a charge pump on GPIO 36. Until
now nothing toggled it, so every board needed the SJ2 WDT DEFEAT jumper
fitted or it would not heat.

The kick is split across two places on purpose. safety_task stamps a
heartbeat at the END of each completed pass, and the existing 100 ms SSR
timer toggles the pin only while that stamp is fresh. Emitting the kick
directly from the timer would have kept it toggling after safety_task
died — the exact failure the pump exists to catch — and stamping at the
top of the loop would have meant 'the loop was entered' rather than 'the
checks ran'.

When the kick stops it stops; it does not drive the pin to a 'safe'
level, because the pump decays on absence of edges and a held level is
already indistinguishable from a stopped one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Bench bring-up and jumper removal

**HUMAN GATE — needs a rev B board and a scope or logic analyser.**

- [ ] **Step 1: Confirm the waveform before removing the jumper**

With SJ2 still fitted, probe GPIO 36. Expected: a square wave toggling every 100 ms (5 Hz) once `safety_task` starts. If it is static, the heartbeat is not reaching the timer.

- [ ] **Step 2: Remove the SJ2 jumper and confirm the kiln still heats**

Run a short firing. The elements should energize normally. If they do not, the pump is not being satisfied — check kick frequency against the pump's requirement before assuming a firmware bug.

- [ ] **Step 3: Prove the watchdog actually bites**

The point of the exercise. With the jumper removed and the element energized, suspend `safety_task` from the console (or add a temporary debug command that does), and confirm **both** SSR channels de-energize within about a second, without firmware commanding anything.

Then repeat with the pin forced high, to confirm a stuck level fails the same way as a stopped one.

**If either case keeps the elements on, the watchdog is decorative — stop and fix it before firing anything unattended.**

- [ ] **Step 4: Update the docs**

`main/Kconfig.projbuild`'s `KILN_PIN_WDT_KICK` help says "NOTHING TOGGLES THIS PIN YET, so a rev B board runs with the WDT DEFEAT solder jumper fitted until the kick task lands." Replace that with the measured kick rate and the fact that the jumper should now be removed. `docs/pin-assignments.md`'s GPIO 36 row says the same thing and needs the same correction.

- [ ] **Step 5: Close the issue**

Close [#307](https://github.com/BenSeverson/bisque/issues/307), recording the measured kick frequency and the observed de-energize time from Step 3.
