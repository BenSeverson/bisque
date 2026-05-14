#pragma once

#include <stdbool.h>

/* Deterministic temperature evolution model for scenario tests.
 *
 * State-machine tests don't need closed-loop PID physics — the unit-level
 * PID tests cover that. So by default the plant tracks the firing engine's
 * own setpoint with a small first-order lag, which guarantees state
 * transitions fire deterministically. Two override modes simulate the
 * failure paths the engine's safety checks are designed to catch:
 *
 *  - `stuck` — temperature ignores the setpoint (kiln-not-rising trip).
 *  - `runaway_rate_c_per_s > 0` — temperature climbs at the given fixed
 *    rate regardless of the setpoint (rate-of-rise runaway trip). */

typedef struct {
    float temp_c;
    float ambient_c;
    float tau_track_s;          /* lag time constant for setpoint tracking */
    float tau_cool_s;           /* cooling time constant when setpoint is 0 / engine idle */
    float runaway_rate_c_per_s; /* >0 forces this linear rise per second */
    bool stuck;
} plant_t;

void plant_init(plant_t *p, float start_temp_c);

/* Advance the plant by `dt_s` seconds. The harness reads the engine's
 * current target temperature (progress.target_temp, which firing_tick
 * writes at end-of-tick) and passes it as `setpoint_c`. */
void plant_step(plant_t *p, float setpoint_c, float dt_s);
