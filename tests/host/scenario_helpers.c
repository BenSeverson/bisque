#include "scenario_helpers.h"

#include "esp_timer.h"
#include "firing_engine.h"
#include "firing_engine_internal.h"
#include "history_host.h"
#include "nvs.h"
#include "safety_host.h"
#include "thermocouple_host.h"

#include <string.h>

void scenario_setup(plant_t *plant, float start_temp_c)
{
    host_clock_set(0);
    nvs_reset_for_test();
    safety_test_reset();
    history_test_reset();
    firing_engine_reset_for_test();
    plant_init(plant, start_temp_c);
    thermocouple_test_set(plant->temp_c, 0);
}

void scenario_dispatch(const firing_cmd_t *cmd)
{
    firing_engine_dispatch_cmd_for_test(cmd);
}

void scenario_start(const firing_profile_t *profile, uint32_t delay_minutes)
{
    firing_cmd_t cmd = {.type = FIRING_CMD_START};
    cmd.start.profile = *profile;
    cmd.start.delay_minutes = delay_minutes;
    scenario_dispatch(&cmd);
}

void scenario_stop(void)
{
    firing_cmd_t cmd = {.type = FIRING_CMD_STOP};
    scenario_dispatch(&cmd);
}

void scenario_pause(void)
{
    firing_cmd_t cmd = {.type = FIRING_CMD_PAUSE};
    scenario_dispatch(&cmd);
}

void scenario_resume(void)
{
    firing_cmd_t cmd = {.type = FIRING_CMD_RESUME};
    scenario_dispatch(&cmd);
}

void scenario_skip(void)
{
    firing_cmd_t cmd = {.type = FIRING_CMD_SKIP_SEGMENT};
    scenario_dispatch(&cmd);
}

bool scenario_relay_test(uint32_t duration_s)
{
    return firing_engine_relay_test_arm(duration_s);
}

void scenario_autotune_start(float setpoint, float hysteresis)
{
    firing_cmd_t cmd = {.type = FIRING_CMD_AUTOTUNE_START};
    cmd.autotune.setpoint = setpoint;
    cmd.autotune.hysteresis = hysteresis;
    scenario_dispatch(&cmd);
}

void scenario_autotune_stop(void)
{
    firing_cmd_t cmd = {.type = FIRING_CMD_AUTOTUNE_STOP};
    scenario_dispatch(&cmd);
}

static void harness_tick_once(plant_t *plant)
{
    /* The firmware order is: tick reads TC, computes new setpoint and duty,
     * publishes via progress. The harness then advances the plant toward
     * that setpoint with a short lag so the *next* tick sees a temperature
     * that's converging on the engine's plan. */
    host_clock_advance(HARNESS_TICK_US);
    firing_tick(esp_timer_get_time());
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    plant_step(plant, prog.target_temp, (float)HARNESS_TICK_US / 1000000.0f);
    thermocouple_test_set(plant->temp_c, 0);
}

firing_status_t scenario_run_ticks(plant_t *plant, int tick_count)
{
    for (int i = 0; i < tick_count; i++) {
        harness_tick_once(plant);
    }
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    return prog.status;
}

bool scenario_run_until_status(plant_t *plant, firing_status_t target_status, int max_ticks)
{
    firing_progress_t prog;
    for (int i = 0; i < max_ticks; i++) {
        harness_tick_once(plant);
        firing_engine_get_progress(&prog);
        if (prog.status == target_status) {
            return true;
        }
    }
    return false;
}

firing_profile_t scenario_short_profile(void)
{
    /* Ramps are intentionally aggressive (6000°C/hr ≈ 100°C/min) so the
     * engine reaches the hold/complete states in tens of simulated seconds
     * instead of tens of simulated minutes. State-machine behavior — segment
     * advance, hold timing, status transitions — is the same at any ramp
     * rate; the unit-level PID tests cover convergence dynamics. */
    firing_profile_t p = {0};
    strncpy(p.id, "test-short", FIRING_ID_LEN - 1);
    strncpy(p.name, "Test Short", FIRING_NAME_LEN - 1);
    strncpy(p.description, "Two-segment fast profile for scenario tests", FIRING_DESC_LEN - 1);
    p.segment_count = 2;
    p.max_temp = 200.0f;
    p.estimated_duration = 5;
    strncpy(p.segments[0].id, "1", FIRING_ID_LEN - 1);
    strncpy(p.segments[0].name, "Ramp", FIRING_NAME_LEN - 1);
    p.segments[0].ramp_rate = 6000.0f;
    p.segments[0].target_temp = 100.0f;
    p.segments[0].hold_time = 0;
    strncpy(p.segments[1].id, "2", FIRING_ID_LEN - 1);
    strncpy(p.segments[1].name, "Peak", FIRING_NAME_LEN - 1);
    p.segments[1].ramp_rate = 6000.0f;
    p.segments[1].target_temp = 200.0f;
    p.segments[1].hold_time = 1;
    return p;
}
