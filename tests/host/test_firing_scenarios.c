#include "esp_timer.h"
#include "firing_engine.h"
#include "history_host.h"
#include "safety_host.h"
#include "scenario_helpers.h"
#include "thermocouple_host.h"
#include "unity.h"

#include <stdbool.h>
#include <string.h>

static plant_t g_plant;

void setUp(void)
{
    scenario_setup(&g_plant, 25.0f);
}

void tearDown(void)
{
    /* Make sure we never leave a firing active across tests. */
    scenario_stop();
}

/* ── Happy path: profile runs to completion ───────────────────────────── */

static void test_happy_path_short_profile_completes(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);

    /* Aggressive ramps + 1-minute hold + plant lag → completes in ~3 simulated
     * minutes. 10 min cap leaves plenty of margin. */
    bool completed = scenario_run_until_status(&g_plant, FIRING_STATUS_COMPLETE, 10 * 60);
    TEST_ASSERT_TRUE_MESSAGE(completed, "profile did not reach COMPLETE within 10 simulated minutes");

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_FALSE(prog.is_active);
    TEST_ASSERT_EQUAL(FIRING_STATUS_COMPLETE, prog.status);

    /* History recorded a firing_start + firing_end with COMPLETE outcome. */
    history_test_counts_t h = history_test_counts();
    TEST_ASSERT_EQUAL_INT(1, h.starts);
    TEST_ASSERT_EQUAL_INT(1, h.ends);
    TEST_ASSERT_EQUAL(HISTORY_OUTCOME_COMPLETE, h.last_outcome);
    TEST_ASSERT_EQUAL_INT(0, h.last_error_code);

    /* SSR forced off on completion. */
    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());

    /* Error code remains NONE. */
    TEST_ASSERT_EQUAL(FIRING_ERR_NONE, firing_engine_get_error_code());
}

/* ── Hold timing: engine waits for hold_time before advancing ─────────── */

static void test_hold_does_not_complete_before_hold_time_elapses(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "hold-test", FIRING_ID_LEN - 1);
    strncpy(p.name, "Hold Test", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 200.0f;
    p.estimated_duration = 5;
    p.segments[0].ramp_rate = 6000.0f;
    p.segments[0].target_temp = 200.0f;
    p.segments[0].hold_time = 5; /* 5-minute hold */

    scenario_start(&p, 0);

    /* Reach the hold within ~2 simulated min after the fast ramp settles. */
    bool holding = scenario_run_until_status(&g_plant, FIRING_STATUS_HOLDING, 3 * 60);
    TEST_ASSERT_TRUE_MESSAGE(holding, "never reached HOLDING");

    /* Run for 4 minutes — still inside the hold. */
    scenario_run_ticks(&g_plant, 4 * 60);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_HOLDING, prog.status, "exited HOLDING before hold_time elapsed");

    /* Run past the 5-minute mark — should now complete. */
    bool completed = scenario_run_until_status(&g_plant, FIRING_STATUS_COMPLETE, 2 * 60);
    TEST_ASSERT_TRUE(completed);
}

/* ── Indefinite hold: HOLDING persists until SKIP_SEGMENT ─────────────── */

static void test_indefinite_hold_waits_for_skip(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "hold-inf", FIRING_ID_LEN - 1);
    strncpy(p.name, "Indef Hold", FIRING_NAME_LEN - 1);
    p.segment_count = 2;
    p.max_temp = 200.0f;
    p.estimated_duration = 30;
    p.segments[0].ramp_rate = 6000.0f;
    p.segments[0].target_temp = 200.0f;
    p.segments[0].hold_time = FIRING_HOLD_INDEFINITE;
    p.segments[1].ramp_rate = 6000.0f;
    p.segments[1].target_temp = 250.0f;
    p.segments[1].hold_time = 0;

    scenario_start(&p, 0);

    /* Reach the hold. */
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HOLDING, 3 * 60));

    /* Run for 20 simulated minutes — indefinite hold never exits on its own. */
    scenario_run_ticks(&g_plant, 20 * 60);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_HOLDING, prog.status);
    TEST_ASSERT_EQUAL_UINT8(0, prog.current_segment);

    /* SKIP advances to next segment. */
    scenario_skip();
    scenario_run_ticks(&g_plant, 1);
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_UINT8(1, prog.current_segment);
    /* Second segment ramps up, so status is HEATING. */
    TEST_ASSERT_EQUAL(FIRING_STATUS_HEATING, prog.status);
}

/* ── Pause: status becomes PAUSED, SSR forced to 0 ──────────────────── */

static void test_pause_drives_ssr_off_and_resume_restores_heating(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);

    /* Tick until we're heating. */
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    scenario_pause();
    scenario_run_ticks(&g_plant, 1);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_PAUSED, prog.status);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());

    /* Run a couple ticks paused — SSR stays at zero. */
    scenario_run_ticks(&g_plant, 5);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());

    scenario_resume();
    scenario_run_ticks(&g_plant, 1);
    firing_engine_get_progress(&prog);
    /* Resume returns to HEATING (or HOLDING if we were holding); here we
     * were mid-ramp so HEATING is the expected state. */
    TEST_ASSERT_EQUAL(FIRING_STATUS_HEATING, prog.status);
}

/* ── Skip mid-ramp advances the segment index ────────────────────────── */

static void test_skip_mid_ramp_advances_segment(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_UINT8(0, prog.current_segment);

    scenario_skip();
    scenario_run_ticks(&g_plant, 1);
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_UINT8(1, prog.current_segment);
}

/* ── Stop returns engine to IDLE ─────────────────────────────────────── */

static void test_stop_drops_to_idle(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    scenario_stop();
    scenario_run_ticks(&g_plant, 1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_IDLE, prog.status);
    TEST_ASSERT_FALSE(prog.is_active);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());

    /* History saw an ABORTED end record. */
    history_test_counts_t h = history_test_counts();
    TEST_ASSERT_EQUAL_INT(1, h.starts);
    TEST_ASSERT_EQUAL_INT(1, h.ends);
    TEST_ASSERT_EQUAL(HISTORY_OUTCOME_ABORTED, h.last_outcome);
}

/* ── Delayed start: stays IDLE during delay, transitions when it ends ── */

static void test_delayed_start_transitions_after_delay(void)
{
    firing_profile_t p = scenario_short_profile();
    /* 2-minute delay. */
    scenario_start(&p, 2);

    /* During delay: status reports IDLE but is_active is true. */
    scenario_run_ticks(&g_plant, 60);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_IDLE, prog.status);
    TEST_ASSERT_TRUE(prog.is_active);

    /* Past the delay: heating starts. */
    bool heating = scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 90);
    TEST_ASSERT_TRUE_MESSAGE(heating, "delayed firing never transitioned to HEATING");
}

/* ── Cooling segment: status reports COOLING during a negative ramp ──── */

static void test_cooling_segment_reports_cooling_status(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "cool-test", FIRING_ID_LEN - 1);
    strncpy(p.name, "Cooling Test", FIRING_NAME_LEN - 1);
    p.segment_count = 2;
    p.max_temp = 600.0f;
    p.estimated_duration = 30;
    p.segments[0].ramp_rate = 12000.0f; /* fast climb */
    p.segments[0].target_temp = 600.0f;
    p.segments[0].hold_time = 0;
    p.segments[1].ramp_rate = -6000.0f; /* descending */
    p.segments[1].target_temp = 300.0f;
    p.segments[1].hold_time = 0;

    scenario_start(&p, 0);

    /* Reach the top — engine advances to cooling segment. */
    bool reached_cooling = scenario_run_until_status(&g_plant, FIRING_STATUS_COOLING, 10 * 60);
    TEST_ASSERT_TRUE_MESSAGE(reached_cooling, "never reached COOLING segment");

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_UINT8(1, prog.current_segment);
}

/* ── TC fault during firing → emergency stop ─────────────────────────── */

static void test_tc_fault_triggers_emergency_stop(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    /* Inject a TC fault directly via the thermocouple stub. The firing engine
     * doesn't check the fault flag itself — the production safety_task does
     * (after a 5s persistent window) and calls safety_emergency_stop(). We
     * simulate that by forcing emergency_stop directly. */
    safety_emergency_stop();
    scenario_run_ticks(&g_plant, 1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_ERROR, prog.status);
    TEST_ASSERT_FALSE(prog.is_active);

    history_test_counts_t h = history_test_counts();
    TEST_ASSERT_EQUAL(HISTORY_OUTCOME_ERROR, h.last_outcome);
    /* No specific error code set ahead of safety stop → engine attributes it
     * to EMERGENCY_STOP. */
    TEST_ASSERT_EQUAL_INT((int)FIRING_ERR_EMERGENCY_STOP, h.last_error_code);
}

/* ── Kiln not rising: emergency stop after 15 min of stuck heating ───── */

static void test_kiln_not_rising_trips_emergency_stop(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "stuck-test", FIRING_ID_LEN - 1);
    strncpy(p.name, "Stuck Kiln", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 600.0f;
    p.estimated_duration = 60;
    p.segments[0].ramp_rate = 100.0f;
    p.segments[0].target_temp = 600.0f;
    p.segments[0].hold_time = 0;

    scenario_start(&p, 0);

    /* Force the plant into "broken element" mode after the first tick so the
     * initial heating window starts normally then stalls. */
    g_plant.stuck = true;

    /* Run for 16 simulated minutes — the not-rising check fires at the 15-min
     * boundary. */
    scenario_run_ticks(&g_plant, 16 * 60);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_ERROR, prog.status);
    TEST_ASSERT_EQUAL(FIRING_ERR_NOT_RISING, firing_engine_get_error_code());
}

/* ── Runaway: emergency stop when actual rate exceeds 2× programmed ─── */

static void test_runaway_trips_emergency_stop(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "runaway-test", FIRING_ID_LEN - 1);
    strncpy(p.name, "Runaway Kiln", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 1200.0f;
    p.estimated_duration = 30;
    p.segments[0].ramp_rate = 60.0f; /* very slow — easy to overshoot */
    p.segments[0].target_temp = 1200.0f;
    p.segments[0].hold_time = 0;

    scenario_start(&p, 0);
    /* Force a fixed 1°C/s rise (3600°C/hr) regardless of duty so actual rate
     * blows past the 2× cap (programmed 60 → trip threshold 120) and the
     * 50°C/hr noise floor. */
    g_plant.runaway_rate_c_per_s = 1.0f;

    /* Runaway check kicks in after 5 minutes in segment. Allow a bit more. */
    scenario_run_ticks(&g_plant, 7 * 60);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_ERROR, prog.status);
    TEST_ASSERT_EQUAL(FIRING_ERR_RUNAWAY, firing_engine_get_error_code());
}

int main(void)
{
    /* Init firing engine once for the whole binary — queues/mutexes are
     * created lazily and the per-test reset wipes state without leaking. */
    firing_engine_init();

    UNITY_BEGIN();
    RUN_TEST(test_happy_path_short_profile_completes);
    RUN_TEST(test_hold_does_not_complete_before_hold_time_elapses);
    RUN_TEST(test_indefinite_hold_waits_for_skip);
    RUN_TEST(test_pause_drives_ssr_off_and_resume_restores_heating);
    RUN_TEST(test_skip_mid_ramp_advances_segment);
    RUN_TEST(test_stop_drops_to_idle);
    RUN_TEST(test_delayed_start_transitions_after_delay);
    RUN_TEST(test_cooling_segment_reports_cooling_status);
    RUN_TEST(test_tc_fault_triggers_emergency_stop);
    RUN_TEST(test_kiln_not_rising_trips_emergency_stop);
    RUN_TEST(test_runaway_trips_emergency_stop);
    return UNITY_END();
}
