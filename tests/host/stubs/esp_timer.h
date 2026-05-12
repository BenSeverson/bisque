#pragma once

#include <stdint.h>

/* esp_timer monotonic clock — virtualized for tests so a 12-hour firing can
 * complete in microseconds of wall time. */
int64_t esp_timer_get_time(void);

/* Test-only helpers. Not part of the real esp_timer API; tests call these
 * to set or advance the virtual clock. */
void host_clock_set(int64_t now_us);
void host_clock_advance(int64_t delta_us);
