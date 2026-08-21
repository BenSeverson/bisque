/* components/safety/wdt_kick.h
 *
 * The liveness half of the hardware watchdog (RB-2). Kept free of ESP-IDF so
 * tests/host/test_wdt_kick.c can drive it; safety.c owns the pin and the timer.
 *
 * KILN_PIN_WDT_KICK retriggers a monostable whose output gates BOTH SSR opto
 * channels, and it retriggers on EDGES — a pin wedged at either level expires
 * the window exactly like a pin that stopped. So the question this file answers
 * is not "is the output on" but "is the firmware still alive enough to be
 * allowed to heat".
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* safety_task runs every 500 ms, so this tolerates ~400 ms of scheduling
 * jitter. It is deliberately NOT one full missed cycle: a cycle genuinely
 * missed means a supervision pass did not complete, which is the condition the
 * watchdog exists to report.
 *
 * The budget it has to fit inside is the monostable's worst-case window
 * (1.65 s): this timeout plus one kick period must expire the window later than
 * the firmware notices, or the hardware cuts power before the firmware can say
 * why. 900 + 200 = 1100 ms leaves 550 ms of headroom — asserted in the tests. */
#define WDT_HEARTBEAT_TIMEOUT_MS 900u

/* Rising edge every 200 ms (the 100 ms SSR timer toggles the pin each call). */
#define WDT_KICK_PERIOD_MS 200u

/* True when the kick may toggle this tick.
 *
 * last_heartbeat_ms of 0 means safety_task has not completed a pass yet and is
 * deliberately treated as stale: the element is unsupervised then, the same
 * reason s_supervised gates ssr_window_apply(). A real timestamp can also land
 * on 0 — once per 49.7-day wrap, for one millisecond — and the cost is one
 * skipped kick tick, three orders of magnitude inside the window.
 *
 * Arithmetic is unsigned on purpose: the difference is correct across the wrap
 * without a special case.
 *
 * Note what is NOT here: an open lid. That is a normal operating condition in
 * warn and pause modes, ssr_window_apply() already holds the SSR low for it in
 * software, and cutting the rail would both add recovery latency on close and
 * make warn mode cut heat, which is exactly what warn means not to do. */
static inline bool wdt_kick_allowed(uint32_t now_ms, uint32_t last_heartbeat_ms, bool emergency)
{
    if (emergency) {
        return false;
    }
    if (last_heartbeat_ms == 0u) {
        return false;
    }
    return (uint32_t)(now_ms - last_heartbeat_ms) < WDT_HEARTBEAT_TIMEOUT_MS;
}
