#pragma once

/**
 * Internal helpers for the safety watchdog. NOT a public API — exposed only so
 * the host test harness (tests/host/) can unit-test the pure decision logic
 * without compiling the full safety.c translation unit (which pulls in GPIO,
 * LEDC, esp_timer and an endless FreeRTOS task loop).
 *
 * Anything declared here is permitted to change without notice.
 */

#include "app_config.h"
#include "thermocouple.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TEMP_FAULT_TIMEOUT_US ((int64_t)APP_TEMP_FAULT_TIMEOUT_MS * 1000LL)

/* What safety_task should do about the thermocouple on this tick. */
typedef enum {
    /* Reading is fault-free: clear the fault bit and run the over-temp check. */
    SAFETY_TC_OK = 0,
    /* Faulted, but still inside the APP_TEMP_FAULT_TIMEOUT_MS grace period. */
    SAFETY_TC_FAULT_GRACE,
    /* Faulted for longer than the grace period: trip the emergency stop. */
    SAFETY_TC_FAULT_TRIP,
} safety_tc_state_t;

/**
 * Advance the thermocouple fault-debounce timer by one tick.
 *
 * `*last_valid_reading_us` is the timestamp the grace period is measured from.
 * safety_task seeds it with esp_timer_get_time() at task start so a fault
 * present at boot still gets the full grace period; this function only ever
 * moves it forward to a real reading's timestamp.
 *
 * A cached reading that no producer has written yet is all zeroes — fault == 0
 * *and* timestamp_us == 0 — so a `timestamp_us > 0` guard is required before
 * adopting it, or the boot seed is clobbered with 0 and the grace period
 * collapses to nothing (see issue #120). safety_task runs at a higher priority
 * than temp_read_task, so it always observes that unset reading at least once.
 *
 * Pure: no globals, no I/O.
 */
safety_tc_state_t safety_tc_watchdog_step(const thermocouple_reading_t *reading, int64_t now_us,
                                          int64_t *last_valid_reading_us);

#ifdef __cplusplus
}
#endif
