#pragma once

#include "firing_types.h"
#include "plant.h"

#include <stdbool.h>
#include <stdint.h>

/* Tick cadence used by the firing engine on the device (and asserted in the
 * docs/wiring); host harness matches it so safety windows trip at the same
 * simulated wall-clock time as production. */
#define HARNESS_TICK_US 1000000LL

/* Reset everything between scenarios: virtual clock to t=0, NVS wiped,
 * safety/history stubs cleared, firing engine state cleared. Leaves the
 * cmd/event queues created by firing_engine_init() intact (init is one-shot
 * for the whole test binary). */
void scenario_setup(plant_t *plant, float start_temp_c);

/* Send a synchronous command to the engine (bypassing the cmd queue). */
void scenario_dispatch(const firing_cmd_t *cmd);

/* Convenience: build a START command for the given profile and dispatch it. */
void scenario_start(const firing_profile_t *profile, uint32_t delay_minutes);

/* Convenience: STOP / PAUSE / RESUME / SKIP_SEGMENT. */
void scenario_stop(void);
void scenario_pause(void);
void scenario_resume(void);
void scenario_skip(void);

/* Convenience: RELAY_TEST (diagnostic SSR pulse). */
void scenario_relay_test(uint32_t duration_s);

/* Convenience: AUTOTUNE_START / AUTOTUNE_STOP. */
void scenario_autotune_start(float setpoint, float hysteresis);
void scenario_autotune_stop(void);

/* Run N ticks of (advance clock, step plant on last duty, push TC reading,
 * call firing_tick). Returns the current progress status after the last
 * tick. */
firing_status_t scenario_run_ticks(plant_t *plant, int tick_count);

/* Run ticks until status == target_status or N_ticks exhausted. Returns true
 * if status reached, false if the loop hit the cap. */
bool scenario_run_until_status(plant_t *plant, firing_status_t target_status, int max_ticks);

/* Build a synthetic profile with two segments suitable for fast end-to-end
 * tests. Both ramp rates use the bench-realistic 600 °C/hr; targets and
 * hold_time stay low so a full firing completes in a few simulated minutes. */
firing_profile_t scenario_short_profile(void);
