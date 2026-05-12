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

#ifdef __cplusplus
}
#endif
