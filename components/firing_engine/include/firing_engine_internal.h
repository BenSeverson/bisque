#pragma once

/**
 * Internal helpers for the firing engine. NOT a public API — exposed only so
 * the host test harness (tests/host/) can unit-test the pure decision logic
 * without compiling the full firing_engine.c translation unit (which pulls
 * in FreeRTOS, NVS, the safety driver, etc.).
 *
 * Anything declared here is permitted to change without notice.
 */

#include "firing_types.h"
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Compute the active setpoint for a segment at `now_us`.
 *
 * Linear ramp from `seg_start_temp` toward `seg->target_temp` at
 * `seg->ramp_rate` (°C/hr), clamped at the target. When `holding` is true,
 * returns `seg->target_temp` directly.
 *
 * Pure: no globals, no I/O.
 */
float compute_dynamic_setpoint(const firing_segment_t *seg, float seg_start_temp, int64_t seg_start_time_us,
                               int64_t now_us, bool holding);

/**
 * Predicate: true once both the measured temperature and the planned setpoint
 * are within the target band (|current - target| < 2°C AND |setpoint -
 * target| < 0.5°C). Both clauses are required so we don't declare "at target"
 * while the ramp is still climbing.
 *
 * Pure: no globals, no I/O.
 */
bool at_target_predicate(float current_temp, float setpoint, float target_temp);

/**
 * Estimate seconds remaining in a firing from the *current* state rather than a
 * fixed up-front guess, so the value stays meaningful even once the kiln has
 * run past the profile's estimated_duration.
 *
 * Sums: the remaining ramp in the current segment (from current_temp to its
 * target at its ramp rate — only when still moving toward the target) plus its
 * remaining hold, then the full planned ramp + hold of every later segment
 * (each starting from the previous target). Indefinite holds contribute 0
 * (unknown duration). Returns 0 for a NULL/empty profile or an out-of-range
 * segment.
 *
 * Pure: no globals, no I/O.
 */
uint32_t firing_remaining_s(const firing_profile_t *profile, int current_segment, float current_temp, bool holding,
                            float hold_elapsed_s);

/**
 * Find the first segment whose ramp-rate sign is inconsistent with the
 * direction from its starting temperature to its target — the config in which
 * the engine labels a segment COOLING while actually driving full-power
 * heating (or vice versa), disabling the heating watchdogs.
 *
 * Segment 0 starts from `start_temp`; each later segment starts from the
 * previous segment's target. A move of more than RAMP_SIGN_EPS_C toward a
 * higher temperature requires a positive ramp; toward a lower temperature, a
 * negative ramp. Near-equal targets (|delta| <= eps) impose no direction.
 *
 * Pass a non-finite `start_temp` (e.g. NAN) to skip segment 0's own direction
 * check — used at profile-save time, when the kiln temperature the profile
 * will eventually fire from is unknown; the inter-segment checks still apply.
 *
 * Returns the offending segment index, or -1 if every segment is consistent
 * (also -1 for a NULL/empty profile). Pure: no globals, no I/O.
 *
 * Also declared in the public firing_engine.h for the web server; mirrored
 * here (dep-free) so the host helper test can link it without pulling in
 * FreeRTOS/esp_err.
 */
int firing_first_bad_ramp_sign(const firing_profile_t *profile, float start_temp);

/* Also declared in the public firing_engine.h; mirrored here so the host
 * scenario test can link it without the FreeRTOS-heavy public header. */
bool firing_engine_relay_test_active(void);

/**
 * Advance the firing engine by one tick using `now_us` as wall-clock time.
 *
 * On the firmware, firing_task() calls this once per second from the virtual
 * `esp_timer_get_time()` value; the host harness calls it directly with a
 * virtual clock so an 8-hour firing finishes in <1s of real time.
 *
 * Reads s_state, s_progress, the PID/autotune state, and emits SSR / vent /
 * history / safety side effects via the usual driver headers (which the host
 * harness link-replaces).
 */
void firing_tick(int64_t now_us);

/**
 * Dispatch a command synchronously (the firmware does this via the cmd queue
 * drained inside firing_task). Test-only entry point — production callers
 * still use the queue.
 */
void firing_engine_dispatch_cmd_for_test(const firing_cmd_t *cmd);

/**
 * Reset all firing-engine state (active profile, timing, errors, element
 * hours, PID, autotune, progress). Use between tests to keep cases
 * independent. Does NOT touch NVS — call nvs_reset_for_test() separately.
 */
void firing_engine_reset_for_test(void);

#ifdef __cplusplus
}
#endif
