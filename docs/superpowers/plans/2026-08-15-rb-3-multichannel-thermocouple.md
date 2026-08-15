# RB-3: Multi-Channel Thermocouple API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `components/thermocouple/` channel awareness via an atomic multi-channel snapshot, without touching any of its ~20 existing call sites.

**Architecture:** Add `thermocouple_get_snapshot()` returning all channels captured under one lock acquisition, plus per-channel init. `thermocouple_get_latest()` survives unchanged as a channel-0 wrapper, which is what keeps `firing_engine`, `safety`, `display`, `web_server`, the host stub and the simulator mock compiling untouched. This plan adds the *capability*; RB-4 fits the second sensor and RM-B1 decides what to do with it.

**Tech Stack:** ESP-IDF SPI, FreeRTOS spinlock, Unity host tests.

**Issue:** [#308](https://github.com/BenSeverson/bisque/issues/308) · Depends on [RB-1 #306](https://github.com/BenSeverson/bisque/issues/306)

## Global Constraints

- **`thermocouple_get_latest()` must not change signature or behaviour.** It has ~20 call sites across `firing_engine.c` (5), `api_handlers.c` (3), `safety.c`, `ws_handler.c`, `display_task.c`, the host stub and `simulator/mock_esp.c`. Changing it turns a contained addition into a repo-wide refactor.
- **The snapshot must be atomic.** The entire point is that a tick cannot pair a fresh air reading with a stale load reading. One `portENTER_CRITICAL` covering all channels, not a loop of per-channel calls.
- `TC_MAX_CHANNELS` is 2 — the board has two CS lines. Do not write a dynamically-sized API for hardware that cannot grow.
- A channel that was never initialised must be distinguishable from one reading 0 °C. `firing_engine` treats 0 °C as a fault sentinel already; an absent channel must not look like a faulted one.
- After editing any firmware C/H file, run `clang-format -i` on it.

## File Structure

| File | Responsibility |
|---|---|
| `components/thermocouple/include/thermocouple.h` | Snapshot type, per-channel init, unchanged legacy API |
| `components/thermocouple/thermocouple.c` | Per-channel device handles, one cache array, one lock |
| `tests/host/stubs/thermocouple_host.c` / `.h` | Stub must grow the snapshot too, or the host suite stops linking |
| `simulator/mock_esp.c` / `.h` | Same, or `make sim` stops linking |
| `tests/host/test_thermocouple_snapshot.c` (new) | Snapshot semantics against the stub |

**The stub and the mock are not optional follow-ups.** They implement the same header; adding a function to it breaks both builds until they do too. `make test` and `make sim` are the two commands that catch it.

---

### Task 1: Extend the header

**Files:**
- Modify: `components/thermocouple/include/thermocouple.h`

**Interfaces:**
- Produces: `TC_MAX_CHANNELS`, `thermocouple_snapshot_t`, `thermocouple_init_channel()`, `thermocouple_get_snapshot()`, `thermocouple_channel_count()`. Tasks 2–4 implement and consume these.

- [ ] **Step 1: Add the snapshot type and per-channel API**

```c
/* Maximum thermocouple channels. Two, because the board has two CS lines
   (TC1_CS GPIO 10, TC2_CS GPIO 35). Not a growth parameter. */
#define TC_MAX_CHANNELS 2

/* Channel roles. Channel 0 is the control probe and always exists; the
   firing engine's PID reads it. Channel 1 is the optional load probe. */
#define TC_CHANNEL_CONTROL 0
#define TC_CHANNEL_LOAD    1

typedef struct {
    thermocouple_reading_t ch[TC_MAX_CHANNELS];
    /* Number of channels actually initialised. Readings at index >=
       channel_count are zeroed and meaningless — an absent channel is NOT a
       0 °C reading, and callers must check this before believing ch[i]. */
    uint8_t channel_count;
} thermocouple_snapshot_t;

/**
 * Initialize one thermocouple channel on the shared SPI bus.
 *
 * @param channel  0..TC_MAX_CHANNELS-1. Channel 0 is the control probe.
 * @param host     SPI host (already initialized)
 * @param cs_pin   GPIO for this channel's chip select
 */
esp_err_t thermocouple_init_channel(int channel, spi_host_device_t host, int cs_pin);

/**
 * Capture every initialized channel under a single lock acquisition.
 *
 * This is the reason the type exists: reading channels one at a time lets a
 * firing tick pair a fresh control reading with a stale load reading, which
 * silently corrupts load-gated soak timing (RM-B1) in a way that looks like
 * a thermal problem rather than a software one.
 */
void thermocouple_get_snapshot(thermocouple_snapshot_t *out);

/** Number of initialized channels. */
uint8_t thermocouple_channel_count(void);
```

- [ ] **Step 2: Document `thermocouple_init` as the compatibility wrapper**

Leave the signature alone; change its doc comment to say it initializes channel 0 and exists so existing callers need no change.

- [ ] **Step 3: Commit**

```bash
clang-format -i components/thermocouple/include/thermocouple.h
git add components/thermocouple/include/thermocouple.h
git commit -m "feat(tc): declare a multi-channel snapshot API

Channel-at-a-time reads let a firing tick pair a fresh control reading
with a stale load reading. That corrupts load-gated soak timing in a way
that presents as a thermal fault rather than a software one, so the
capture is one lock acquisition over all channels by construction.

thermocouple_get_latest() is untouched: ~20 call sites depend on it and
none of them need to move for this.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Implement in the driver

**Files:**
- Modify: `components/thermocouple/thermocouple.c`

**Interfaces:**
- Consumes: the header from Task 1, and RB-1's `reg_read`/`reg_write` helpers.

- [ ] **Step 1: Replace the single-device state with arrays**

```c
static spi_device_handle_t s_spi_dev[TC_MAX_CHANNELS];
static portMUX_TYPE s_reading_mux = portMUX_INITIALIZER_UNLOCKED;
static thermocouple_reading_t s_latest[TC_MAX_CHANNELS];
static uint8_t s_channel_count;
```

- [ ] **Step 2: Make `reg_read`/`reg_write` channel-aware**

Both gain a leading `int channel` parameter and use `s_spi_dev[channel]`. `thermocouple_read` becomes `thermocouple_read_channel(int channel, thermocouple_reading_t *out)`, with `thermocouple_read()` kept as a channel-0 wrapper for the existing callers and the host stub's contract.

- [ ] **Step 3: Implement `thermocouple_init_channel`**

Move RB-1's device-add plus config-register write and CR0 read-back into it, indexed by channel. Track the highest initialized index:

```c
    if (channel + 1 > s_channel_count) {
        s_channel_count = (uint8_t)(channel + 1);
    }
```

Then make the legacy entry point a wrapper:

```c
esp_err_t thermocouple_init(spi_host_device_t host, int cs_pin)
{
    return thermocouple_init_channel(TC_CHANNEL_CONTROL, host, cs_pin);
}
```

- [ ] **Step 4: Implement the snapshot and the count**

```c
void thermocouple_get_snapshot(thermocouple_snapshot_t *out)
{
    portENTER_CRITICAL(&s_reading_mux);
    memcpy(out->ch, s_latest, sizeof(out->ch));
    out->channel_count = s_channel_count;
    portEXIT_CRITICAL(&s_reading_mux);
}

uint8_t thermocouple_channel_count(void)
{
    portENTER_CRITICAL(&s_reading_mux);
    uint8_t n = s_channel_count;
    portEXIT_CRITICAL(&s_reading_mux);
    return n;
}
```

`thermocouple_get_latest()` keeps its current body but reads `s_latest[TC_CHANNEL_CONTROL]`.

- [ ] **Step 5: Make `temp_read_task` poll every initialized channel**

Read each channel, then publish them **together** under one lock:

```c
    for (;;) {
        thermocouple_reading_t fresh[TC_MAX_CHANNELS] = {0};
        uint8_t n = thermocouple_channel_count();
        for (uint8_t i = 0; i < n; i++) {
            if (thermocouple_read_channel(i, &fresh[i]) != ESP_OK) {
                /* Leave this channel's slot zeroed for this pass rather than
                   republishing a stale value under a new timestamp — the
                   safety watchdog ages readings by timestamp, so refreshing
                   it here would hide a dead sensor from the fault path. */
                continue;
            }
        }
        portENTER_CRITICAL(&s_reading_mux);
        memcpy(s_latest, fresh, sizeof(s_latest));
        portEXIT_CRITICAL(&s_reading_mux);
        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(250));
    }
```

> **Check this against `safety_tc_watchdog_step()` before accepting it.** That function decides a fault from the reading's `timestamp_us`, and the existing task only overwrote the cache on a *successful* read. The version above publishes a zeroed slot on failure, which changes what the watchdog sees. Read `components/safety/safety_helpers.c` and `tests/host/test_safety_helpers.c` and pick whichever behaviour those tests actually pin — then make this comment say the true thing.

- [ ] **Step 6: Format and build**

```bash
clang-format -i components/thermocouple/thermocouple.c
make firmware
```

Expected: builds. `make test` will still fail until Task 3.

---

### Task 3: Update the stub and the simulator mock

**Files:**
- Modify: `tests/host/stubs/thermocouple_host.c`, `tests/host/stubs/thermocouple_host.h`
- Modify: `simulator/mock_esp.c`, `simulator/mock_esp.h`

- [ ] **Step 1: Confirm both are broken first**

```bash
make test-host; echo "host EXIT=$?"
make sim-verify; echo "sim EXIT=$?"
```

Expected: both fail to link on the missing symbols. If they pass, the header change did not reach them and something is wrong with the include paths.

- [ ] **Step 2: Add snapshot support to the host stub**

Give the stub a channel array mirroring the driver, keep `thermocouple_get_latest()` returning channel 0, and add a test hook so a test can set channel 1 independently:

```c
void thermocouple_host_set_channel(int channel, const thermocouple_reading_t *r);
```

Declare it in `thermocouple_host.h` beside the existing hooks.

- [ ] **Step 3: Add the same to `simulator/mock_esp.c`**

The simulator only ever drives channel 0 today; `thermocouple_get_snapshot()` there can return one channel with `channel_count = 1`. Mirror `mock_set_thermocouple` into the array.

- [ ] **Step 4: Confirm both build**

```bash
make test-host && make sim-verify
```

Expected: both pass.

---

### Task 4: Test the snapshot semantics

**Files:**
- Create: `tests/host/test_thermocouple_snapshot.c`
- Modify: `tests/host/CMakeLists.txt`

- [ ] **Step 1: Write the tests**

```c
#include "unity.h"
#include "thermocouple.h"
#include "thermocouple_host.h"

static void test_absent_channel_is_not_a_zero_reading(void)
{
    thermocouple_snapshot_t s;
    thermocouple_get_snapshot(&s);
    /* With only the control channel initialized, a caller must be able to
       tell "no load probe fitted" from "load probe reads 0 C" — the latter
       is firing_engine's fault sentinel. */
    TEST_ASSERT_EQUAL_UINT8(1, s.channel_count);
}

static void test_snapshot_reports_both_channels(void)
{
    thermocouple_reading_t air = {.temperature_c = 900.0f, .timestamp_us = 1000};
    thermocouple_reading_t load = {.temperature_c = 850.0f, .timestamp_us = 1000};
    thermocouple_host_set_channel(TC_CHANNEL_CONTROL, &air);
    thermocouple_host_set_channel(TC_CHANNEL_LOAD, &load);

    thermocouple_snapshot_t s;
    thermocouple_get_snapshot(&s);
    TEST_ASSERT_EQUAL_UINT8(2, s.channel_count);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 900.0f, s.ch[TC_CHANNEL_CONTROL].temperature_c);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 850.0f, s.ch[TC_CHANNEL_LOAD].temperature_c);
}

/* The compatibility guarantee the whole plan rests on. */
static void test_get_latest_still_returns_channel_zero(void)
{
    thermocouple_reading_t air = {.temperature_c = 777.0f, .timestamp_us = 2000};
    thermocouple_host_set_channel(TC_CHANNEL_CONTROL, &air);
    thermocouple_reading_t out;
    thermocouple_get_latest(&out);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 777.0f, out.temperature_c);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_absent_channel_is_not_a_zero_reading);
    RUN_TEST(test_snapshot_reports_both_channels);
    RUN_TEST(test_get_latest_still_returns_channel_zero);
    return UNITY_END();
}
```

Order matters here: `test_absent_channel_is_not_a_zero_reading` must run before the test that initializes channel 1, since the stub's state persists across tests in one binary. If that coupling bothers you, add a `thermocouple_host_reset()` and call it in each test — preferable, and cheap.

- [ ] **Step 2: Register, run, commit**

```bash
make test
git add components/thermocouple/ tests/host/ simulator/
git commit -m "feat(tc): capture all channels in one lock acquisition

Adds thermocouple_get_snapshot() plus per-channel init, leaving
thermocouple_get_latest() as a channel-0 wrapper so none of its ~20 call
sites move.

An uninitialized channel reports via channel_count rather than a zeroed
reading, because firing_engine already treats 0 C as its fault sentinel
and an absent load probe must not be indistinguishable from a shorted
one.

The host stub and the simulator mock implement the same header, so both
grow the function too — make test and make sim-verify are what catch it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
