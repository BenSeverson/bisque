#include "esp_timer.h"
#include "firing_engine.h"
#include "firing_engine_internal.h"
#include "history_host.h"
#include "safety_host.h"
#include "scenario_helpers.h"
#include "thermocouple.h"
#include "thermocouple_host.h"
#include "unity.h"

#include <math.h>
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

/* ── Command guards ───────────────────────────────────────────────────
 *
 * The command handler transitions the engine between states; each of the
 * cases below is a transition it used to make without checking the state it
 * was coming *from*. Regression cover for #108–#111.
 */

/* SKIP while PAUSED must not silently re-energize the kiln (#108). The
 * operator believes the elements are off; anything that turns them back on
 * without an explicit RESUME is the dangerous outcome. */
static void test_skip_while_paused_does_not_resume_heating(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    scenario_pause();
    scenario_run_ticks(&g_plant, 1);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_PAUSED, prog.status);
    uint8_t seg_before = prog.current_segment;

    scenario_skip();
    scenario_run_ticks(&g_plant, 5);

    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_PAUSED, prog.status, "SKIP while paused left the engine heating");
    TEST_ASSERT_EQUAL_UINT8_MESSAGE(seg_before, prog.current_segment, "SKIP while paused advanced the segment");
    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(0.0f, safety_test_last_duty(), "SKIP while paused re-energized the SSR");
}

/* Once resumed, SKIP works normally again — the guard rejects the command, it
 * doesn't wedge the engine. */
static void test_skip_after_resume_still_advances_segment(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    scenario_pause();
    scenario_run_ticks(&g_plant, 1);
    scenario_skip(); /* rejected */
    scenario_resume();
    scenario_run_ticks(&g_plant, 1);

    scenario_skip(); /* accepted */
    scenario_run_ticks(&g_plant, 1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_UINT8(1, prog.current_segment);
}

/* AUTOTUNE_START must not hijack a running firing (#109). */
static void test_autotune_start_rejected_during_active_firing(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    scenario_autotune_start(500.0f, 5.0f);
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_HEATING, prog.status, "autotune hijacked a running firing");
    TEST_ASSERT_TRUE(prog.is_active);
    TEST_ASSERT_EQUAL_UINT8_MESSAGE(2, prog.total_segments, "autotune clobbered the active profile");

    /* The firing's history record must still be open — a hijack would strand
     * it, leaving history_firing_end uncalled until the next firing. */
    history_test_counts_t h = history_test_counts();
    TEST_ASSERT_EQUAL_INT(1, h.starts);
    TEST_ASSERT_EQUAL_INT_MESSAGE(0, h.ends, "autotune closed or orphaned the firing's history record");
}

/* A NaN (or non-finite / out-of-range) setpoint must not produce a "ghost"
 * autotune: the engine used to ignore pid_autotune_start's return and flip to
 * AUTOTUNE regardless, so an invalid setpoint left is_active latched with the
 * relay loop running NaN comparisons. (#115) */
static void test_autotune_rejects_nan_setpoint(void)
{
    scenario_autotune_start(NAN, 5.0f);
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_FALSE_MESSAGE(prog.is_active, "NaN-setpoint autotune was accepted");
    TEST_ASSERT_NOT_EQUAL(FIRING_STATUS_AUTOTUNE, prog.status);
}

/* A setpoint above the safe limit must be rejected at the engine level, the
 * way FIRING_CMD_START rejects over-limit segment targets. */
static void test_autotune_rejects_over_max_setpoint(void)
{
    scenario_autotune_start(safety_get_max_temp() + 100.0f, 5.0f);
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_FALSE_MESSAGE(prog.is_active, "over-max-temp autotune was accepted");
}

/* The #109 guard must not be so broad it blocks the normal case. */
static void test_autotune_starts_when_no_firing_is_active(void)
{
    scenario_autotune_start(500.0f, 5.0f);
    scenario_run_ticks(&g_plant, 1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_AUTOTUNE, prog.status);
    TEST_ASSERT_TRUE(prog.is_active);
}

/* Resuming a paused autotune must return to AUTOTUNE, not fall through to a
 * "normal firing" against whatever profile happens to be in s_state (#110). */
static void test_pause_resume_during_autotune_restores_autotune(void)
{
    scenario_autotune_start(500.0f, 5.0f);
    scenario_run_ticks(&g_plant, 1);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_AUTOTUNE, prog.status);

    scenario_pause();
    scenario_run_ticks(&g_plant, 1);
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_PAUSED, prog.status);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());

    scenario_resume();
    scenario_run_ticks(&g_plant, 1);
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_AUTOTUNE, prog.status,
                              "resume relabelled a paused autotune as a normal firing");
}

/* Same root cause as #110: RESUME reconstructed the status from s_state.holding
 * instead of remembering it, so a paused COOLING segment came back as HEATING —
 * which also re-arms the heating watchdogs against a descending setpoint. */
static void test_pause_resume_during_cooling_restores_cooling(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "cool-pause", FIRING_ID_LEN - 1);
    strncpy(p.name, "Cooling Pause", FIRING_NAME_LEN - 1);
    p.segment_count = 2;
    p.max_temp = 600.0f;
    p.estimated_duration = 30;
    p.segments[0].ramp_rate = 12000.0f;
    p.segments[0].target_temp = 600.0f;
    p.segments[0].hold_time = 0;
    p.segments[1].ramp_rate = -6000.0f;
    p.segments[1].target_temp = 300.0f;
    p.segments[1].hold_time = 0;

    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_COOLING, 10 * 60));

    scenario_pause();
    scenario_run_ticks(&g_plant, 1);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_PAUSED, prog.status);

    scenario_resume();
    scenario_run_ticks(&g_plant, 1);
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_COOLING, prog.status,
                              "resume turned a paused cooling segment into HEATING");
}

/* Build a profile whose middle segment cools to a long indefinite hold, so
 * that skipping out of the hold leaves the not-rising window holding a
 * baseline *above* the current temperature. */
static firing_profile_t skip_out_of_hold_profile(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "skip-hold", FIRING_ID_LEN - 1);
    strncpy(p.name, "Skip Out Of Hold", FIRING_NAME_LEN - 1);
    p.segment_count = 3;
    p.max_temp = 700.0f;
    p.estimated_duration = 60;
    p.segments[0].ramp_rate = 12000.0f;
    p.segments[0].target_temp = 600.0f;
    p.segments[0].hold_time = 0;
    /* Cooling segment: entering it re-arms the not-rising window with a 600°C
     * baseline, and the check is then suppressed for the whole descent and
     * hold (it only runs while HEATING). */
    p.segments[1].ramp_rate = -6000.0f;
    p.segments[1].target_temp = 300.0f;
    p.segments[1].hold_time = FIRING_HOLD_INDEFINITE;
    p.segments[2].ramp_rate = 6000.0f;
    p.segments[2].target_temp = 400.0f;
    p.segments[2].hold_time = 0;
    return p;
}

/* Skipping out of a long hold must re-arm the not-rising window (#111).
 *
 * By the time the operator skips, the 15-minute window is long expired and its
 * baseline is from an unrelated earlier window — here, 300°C hotter than the
 * kiln actually is. Without a reset the very next tick computes a *negative*
 * rise, decides the kiln is stalled, and emergency-stops a healthy firing.
 * An indefinite hold is the worst case, since SKIP is the only way out of one.
 */
static void test_skip_out_of_long_hold_does_not_trip_not_rising(void)
{
    firing_profile_t p = skip_out_of_hold_profile();
    scenario_start(&p, 0);

    TEST_ASSERT_TRUE_MESSAGE(scenario_run_until_status(&g_plant, FIRING_STATUS_HOLDING, 30 * 60),
                             "never reached the indefinite hold");

    /* Sit in the hold well past the 15-minute not-rising interval. */
    scenario_run_ticks(&g_plant, 20 * 60);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_HOLDING, prog.status);

    scenario_skip();

    /* Run 14 simulated minutes — inside a freshly-armed window, so the
     * not-rising check should not have evaluated even once yet. */
    scenario_run_ticks(&g_plant, 14 * 60);

    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_ERR_NONE, firing_engine_get_error_code(),
                              "skipping out of a hold tripped a watchdog on a healthy firing");
    TEST_ASSERT_NOT_EQUAL_MESSAGE(FIRING_STATUS_ERROR, prog.status, "skip out of hold caused an emergency stop");
    TEST_ASSERT_EQUAL_UINT8(2, prog.current_segment);
}

/* The #111 fix re-arms the window rather than disabling it: a kiln that really
 * is stalled after a skip must still trip, just a full window later. */
static void test_skip_out_of_hold_still_arms_not_rising(void)
{
    firing_profile_t p = skip_out_of_hold_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HOLDING, 30 * 60));
    scenario_run_ticks(&g_plant, 20 * 60);

    scenario_skip();
    g_plant.stuck = true; /* elements fail right as the new segment begins */

    scenario_run_ticks(&g_plant, 16 * 60);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_ERROR, prog.status);
    TEST_ASSERT_EQUAL(FIRING_ERR_NOT_RISING, firing_engine_get_error_code());
}

/* START must reject a segment whose ramp sign contradicts the direction to its
 * target (#113). Here the kiln is at 400°C and the single segment ramps
 * *down* (-100°C/hr) toward 1200°C — the engine would label it COOLING and
 * disable the heating watchdogs while the clamped setpoint drives full power. */
static void test_start_rejects_wrong_sign_ramp(void)
{
    scenario_setup(&g_plant, 400.0f);

    firing_profile_t p = {0};
    strncpy(p.id, "wrong-sign", FIRING_ID_LEN - 1);
    strncpy(p.name, "Wrong Sign", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 1300.0f;
    p.estimated_duration = 60;
    p.segments[0].ramp_rate = -100.0f;
    p.segments[0].target_temp = 1200.0f;
    p.segments[0].hold_time = 0;

    scenario_start(&p, 0);
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_FALSE_MESSAGE(prog.is_active, "wrong-sign profile was allowed to start");
    TEST_ASSERT_EQUAL(FIRING_STATUS_IDLE, prog.status);
    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(0.0f, safety_test_last_duty(), "wrong-sign profile energized the SSR");
}

/* The #113 guard must not reject a legitimate cooling segment: a real descent
 * (negative ramp toward a lower target) still fires normally. */
static void test_start_allows_legitimate_cooling_segment(void)
{
    scenario_setup(&g_plant, 25.0f);

    firing_profile_t p = {0};
    strncpy(p.id, "heat-cool", FIRING_ID_LEN - 1);
    strncpy(p.name, "Heat then Cool", FIRING_NAME_LEN - 1);
    p.segment_count = 2;
    p.max_temp = 700.0f;
    p.estimated_duration = 30;
    p.segments[0].ramp_rate = 12000.0f;
    p.segments[0].target_temp = 600.0f;
    p.segments[0].hold_time = 0;
    p.segments[1].ramp_rate = -6000.0f;
    p.segments[1].target_temp = 300.0f;
    p.segments[1].hold_time = 0;

    scenario_start(&p, 0);
    scenario_run_ticks(&g_plant, 1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_TRUE_MESSAGE(prog.is_active, "legitimate heat-then-cool profile was wrongly rejected");
}

/* A delayed start must NOT be judged against the temperature at arm time — the
 * kiln is often still hot from a previous firing when the user queues an
 * overnight bisque, and will be cold by the time the delay expires. */
static void test_delayed_start_not_judged_by_arm_time_temperature(void)
{
    scenario_setup(&g_plant, 800.0f); /* still hot from a previous firing */

    firing_profile_t p = {0};
    strncpy(p.id, "delayed-heat", FIRING_ID_LEN - 1);
    strncpy(p.name, "Delayed Heat", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 900.0f;
    p.estimated_duration = 60;
    p.segments[0].ramp_rate = 100.0f;   /* heating… */
    p.segments[0].target_temp = 600.0f; /* …to a target below the *current* temp */
    p.segments[0].hold_time = 0;

    scenario_start(&p, 120); /* 2-hour delay */
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_TRUE_MESSAGE(prog.is_active, "delayed start rejected using the arm-time temperature");
    TEST_ASSERT_EQUAL(FIRING_STATUS_IDLE, prog.status); /* armed, counting down */
}

/* …but the check must still run when the delay expires, against the fresh
 * reading, since that is the temperature the first segment actually starts
 * from. */
static void test_delayed_start_rejects_wrong_sign_at_expiry(void)
{
    scenario_setup(&g_plant, 400.0f);

    firing_profile_t p = {0};
    strncpy(p.id, "delayed-bad", FIRING_ID_LEN - 1);
    strncpy(p.name, "Delayed Bad Sign", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 1300.0f;
    p.estimated_duration = 60;
    p.segments[0].ramp_rate = -100.0f;   /* cooling ramp… */
    p.segments[0].target_temp = 1200.0f; /* …toward a much higher target */
    p.segments[0].hold_time = 0;

    scenario_start(&p, 1); /* 1-minute delay */

    /* It must actually arm — otherwise this test would pass merely because the
       profile was rejected up front, never exercising the expiry path. */
    scenario_run_ticks(&g_plant, 5);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_TRUE_MESSAGE(prog.is_active, "delayed firing never armed; expiry path not exercised");

    scenario_run_ticks(&g_plant, 90); /* run past expiry */

    firing_engine_get_progress(&prog);
    TEST_ASSERT_NOT_EQUAL_MESSAGE(FIRING_STATUS_HEATING, prog.status,
                                  "wrong-sign profile began heating after the delay expired");
    TEST_ASSERT_NOT_EQUAL(FIRING_STATUS_COOLING, prog.status);
    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(0.0f, safety_test_last_duty(), "wrong-sign delayed firing energized the SSR");
}

/* SKIP re-enters the next segment from wherever the kiln actually is, which is
 * not the previous segment's target. A segment that is a valid descent from
 * that target can be an invalid one from an early skip point. */
static void test_skip_rejects_wrong_sign_next_segment(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "skip-sign", FIRING_ID_LEN - 1);
    strncpy(p.name, "Skip Sign", FIRING_NAME_LEN - 1);
    p.segment_count = 2;
    p.max_temp = 700.0f;
    p.estimated_duration = 60;
    p.segments[0].ramp_rate = 6000.0f;
    p.segments[0].target_temp = 600.0f;
    p.segments[0].hold_time = 0;
    /* Valid as a descent 600 -> 500, invalid from an early skip at ~25°C. */
    p.segments[1].ramp_rate = -100.0f;
    p.segments[1].target_temp = 500.0f;
    p.segments[1].hold_time = 0;

    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    /* Skip immediately, while the kiln is still far below segment 1's target. */
    scenario_skip();
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_UINT8_MESSAGE(0, prog.current_segment,
                                    "skip advanced into a segment whose ramp contradicts the current temperature");
    TEST_ASSERT_EQUAL(FIRING_STATUS_HEATING, prog.status);
}

/* Autotune measures its 60-minute timeout and its relay-cycle periods from
 * absolute esp_timer timestamps. A pause must shift them, or the run either
 * times out the instant it resumes or folds the pause into an oscillation
 * period and saves bad gains. */
static void test_autotune_resume_does_not_time_out_after_long_pause(void)
{
    scenario_autotune_start(500.0f, 5.0f);
    scenario_run_ticks(&g_plant, 1);
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_AUTOTUNE, prog.status);

    scenario_pause();
    /* 61 simulated minutes paused — longer than the whole autotune budget.
       The autotune branch does not run while PAUSED, so nothing advances. */
    scenario_run_ticks(&g_plant, 61 * 60);

    scenario_resume();
    scenario_run_ticks(&g_plant, 2);

    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_AUTOTUNE, prog.status,
                              "autotune timed out on resume — pause was counted against its budget");
}

/* ── Relay diagnostic test (#112, absorbing #82) ──────────────────────
 *
 * The old implementation energized the SSR and blocked the HTTP worker in a
 * single vTaskDelay. The safety task trips an emergency stop if 3 s pass with
 * duty > 0 and no fresh safety_set_ssr() call, so any test longer than 3 s
 * latched an emergency state instead of completing. Owning the pulse in the
 * engine tick re-asserts the duty every second, keeps a single writer for the
 * SSR, and frees the HTTP worker.
 */

static void test_relay_test_reasserts_ssr_every_tick(void)
{
    scenario_relay_test(5);

    /* The SSR heartbeat must be re-fed on every tick — asserting the last duty
       alone cannot show this, since a single set at t=0 would read the same. */
    unsigned before = safety_test_ssr_call_count();
    scenario_run_ticks(&g_plant, 4);
    unsigned calls = safety_test_ssr_call_count() - before;

    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(1.0f, safety_test_last_duty(), "relay test did not hold the SSR on");
    TEST_ASSERT_TRUE_MESSAGE(calls >= 4, "SSR not re-asserted each tick — the 3 s heartbeat would trip");
}

static void test_relay_test_releases_ssr_when_duration_elapses(void)
{
    scenario_relay_test(3);
    scenario_run_ticks(&g_plant, 2);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, safety_test_last_duty());

    scenario_run_ticks(&g_plant, 4); /* past the 3 s duration */
    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(0.0f, safety_test_last_duty(), "relay test left the SSR energized");
}

/* The busy state must be visible to callers (HTTP/display) so they can reject
 * conflicting operations up front instead of getting a false success. */
static void test_relay_test_active_is_observable(void)
{
    TEST_ASSERT_FALSE(firing_engine_relay_test_active());
    scenario_relay_test(3);
    TEST_ASSERT_TRUE_MESSAGE(firing_engine_relay_test_active(), "relay-test busy state not observable while running");

    scenario_run_ticks(&g_plant, 4); /* past the 3 s duration */
    TEST_ASSERT_FALSE_MESSAGE(firing_engine_relay_test_active(), "relay-test busy state stuck on after it finished");
}

/* A second relay request while one is active must be ignored, not allowed to
 * push the deadline out — otherwise repeated taps hold the SSR on past the
 * 10 s cap indefinitely. */
static void test_relay_test_does_not_extend_on_overlap(void)
{
    TEST_ASSERT_TRUE(scenario_relay_test(3));
    scenario_run_ticks(&g_plant, 2); /* 2 s in */

    /* A second request must be rejected outright, not extend the deadline. */
    TEST_ASSERT_FALSE_MESSAGE(scenario_relay_test(3), "overlapping relay request was accepted");
    scenario_run_ticks(&g_plant, 2); /* now 4 s total — past the original 3 s */

    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(0.0f, safety_test_last_duty(),
                                    "overlapping relay request extended the pulse past its original deadline");
    TEST_ASSERT_FALSE(firing_engine_relay_test_active());
}

/* STOP must halt an in-progress relay test — /api/v1/firing/stop queues STOP
 * unconditionally, so it is the operator's way to cut the pulse short. */
static void test_stop_cancels_relay_test(void)
{
    scenario_relay_test(5);
    scenario_run_ticks(&g_plant, 1);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, safety_test_last_duty());
    TEST_ASSERT_TRUE(firing_engine_relay_test_active());

    scenario_stop();
    scenario_run_ticks(&g_plant, 2);
    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(0.0f, safety_test_last_duty(), "STOP did not cancel the relay pulse");
    TEST_ASSERT_FALSE_MESSAGE(firing_engine_relay_test_active(), "relay test still active after STOP");
}

/* Single owner for the SSR: the test must not run against a live firing. */
static void test_relay_test_rejected_while_firing_active(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    scenario_relay_test(5);
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_HEATING, prog.status, "relay test disturbed a running firing");
    TEST_ASSERT_TRUE(prog.is_active);
}

/* …and the converse: a firing must not start on top of a running relay test. */
static void test_start_rejected_while_relay_test_running(void)
{
    scenario_relay_test(10);
    scenario_run_ticks(&g_plant, 2);

    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_FALSE_MESSAGE(prog.is_active, "firing started while the relay test held the SSR");
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

/* ── TC fault gate: a faulted reading holds the SSR off, no PID full-power ─ */

static void test_tc_fault_holds_ssr_off(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    /* The kiln is below target, so the engine is actively driving heat. */
    TEST_ASSERT_TRUE(safety_test_last_duty() > 0.0f);

    /* Inject a thermocouple fault and run one tick by hand — the scenario
     * helper would reset the fault flag at the end of each tick. A faulted
     * MAX31855 reports 0°C; without the gate the PID sees 0°C vs a hot setpoint
     * and commands full power. */
    thermocouple_test_set(0.0f, TC_FAULT_OPEN_CIRCUIT);
    host_clock_advance(HARNESS_TICK_US);
    firing_tick(esp_timer_get_time());

    TEST_ASSERT_EQUAL_FLOAT(0.0f, safety_test_last_duty());

    /* The engine itself does not emergency-stop on a fault — that's safety_task's
     * job after the persistence window — so the firing is still active. */
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_TRUE(prog.is_active);
}

/* ── Pause freeze: a long pause must not trip the not-rising safety check ── */

static void test_long_pause_does_not_trip_not_rising(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "pause-rise", FIRING_ID_LEN - 1);
    strncpy(p.name, "Pause Rise", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 600.0f;
    p.estimated_duration = 600;
    p.segments[0].ramp_rate = 60.0f; /* slow: ~1°C/min, so the rising window is tight */
    p.segments[0].target_temp = 600.0f;
    p.segments[0].hold_time = 0;

    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 5));

    /* Heat briefly, then pause for 16 simulated minutes — longer than the
     * 15-minute not-rising window. Without the resume-time anchor shift, the
     * window (started at segment begin) has aged past 15 min while the kiln
     * barely moved, so the first heating tick after resume trips NOT_RISING. */
    scenario_run_ticks(&g_plant, 100);
    scenario_pause();
    scenario_run_ticks(&g_plant, 16 * 60);
    scenario_resume();
    scenario_run_ticks(&g_plant, 5);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_MESSAGE(FIRING_STATUS_HEATING, prog.status, "spurious trip after long pause");
    TEST_ASSERT_EQUAL(FIRING_ERR_NONE, firing_engine_get_error_code());
}

/* ── Pause freeze: the ramp setpoint resumes where it left off, no jump ──── */

static void test_pause_does_not_jump_setpoint(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "pause-sp", FIRING_ID_LEN - 1);
    strncpy(p.name, "Pause Setpoint", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 1000.0f;
    p.estimated_duration = 600;
    p.segments[0].ramp_rate = 600.0f; /* 0.1667°C/s */
    p.segments[0].target_temp = 1000.0f;
    p.segments[0].hold_time = 0;

    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 5));
    scenario_run_ticks(&g_plant, 60);

    firing_progress_t before;
    firing_engine_get_progress(&before);

    /* Pause 5 minutes, resume, step a couple ticks. The dynamic setpoint should
     * have advanced only by those couple ticks, not by the whole pause (which
     * at 600°C/hr would be a ~50°C jump). */
    scenario_pause();
    scenario_run_ticks(&g_plant, 300);
    scenario_resume();
    scenario_run_ticks(&g_plant, 2);

    firing_progress_t after;
    firing_engine_get_progress(&after);

    float jump = after.target_temp - before.target_temp;
    TEST_ASSERT_TRUE_MESSAGE(jump >= 0.0f && jump < 5.0f, "setpoint jumped across the pause");
}

/* ── Element-hours: sub-second ticks are not truncated away ─────────────── */

static void test_element_hours_accumulate_subsecond_ticks(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    /* Drive 20 half-second ticks by hand (the scenario helper only does whole
     * seconds). The plant isn't stepped, so the kiln stays below the climbing
     * setpoint and the PID keeps commanding heat. The old code truncated each
     * (uint32_t)0.5 to 0 and accumulated nothing. */
    uint32_t before = firing_engine_get_element_hours_s();
    for (int i = 0; i < 20; i++) {
        host_clock_advance(HARNESS_TICK_US / 2);
        firing_tick(esp_timer_get_time());
    }
    uint32_t gained = firing_engine_get_element_hours_s() - before;
    TEST_ASSERT_TRUE_MESSAGE(gained >= 8, "element-on time lost to sub-second truncation");
}

/* ── Profile key collision: distinct IDs sharing a 15-char NVS key rejected ─ */

/* Saving past the profile limit used to write the blob, skip the index append,
 * and still return ESP_OK — the UI reported success while the profile never
 * appeared in the list and its ~2.5 KB blob was stranded in NVS, unreachable by
 * delete (which needs the index) forever. (#116) */
static void test_profile_save_rejected_when_index_full(void)
{
    firing_profile_t p = {0};
    strncpy(p.name, "Filler", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 500.0f;
    p.segments[0].ramp_rate = 100.0f;
    p.segments[0].target_temp = 500.0f;

    for (int i = 0; i < FIRING_MAX_PROFILES; i++) {
        snprintf(p.id, FIRING_ID_LEN, "filler%02d", i);
        TEST_ASSERT_EQUAL(ESP_OK, firing_engine_save_profile(&p));
    }

    snprintf(p.id, FIRING_ID_LEN, "overflow");
    TEST_ASSERT_NOT_EQUAL_MESSAGE(ESP_OK, firing_engine_save_profile(&p),
                                  "save past the profile limit reported success");

    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    TEST_ASSERT_EQUAL_INT(FIRING_MAX_PROFILES, firing_engine_list_profiles(ids, FIRING_MAX_PROFILES));

    /* load reads the blob by key, not via the index, so a written-but-unindexed
       blob would still load here — that is exactly the orphan. */
    firing_profile_t loaded;
    TEST_ASSERT_NOT_EQUAL_MESSAGE(ESP_OK, firing_engine_load_profile("overflow", &loaded),
                                  "profile blob was orphaned in NVS");
}

/* Re-saving an existing profile at the limit must still work — the guard is on
 * adding a new index entry, not on updates. */
static void test_profile_update_still_allowed_when_index_full(void)
{
    firing_profile_t p = {0};
    strncpy(p.name, "Filler", FIRING_NAME_LEN - 1);
    p.segment_count = 1;
    p.max_temp = 500.0f;
    p.segments[0].ramp_rate = 100.0f;
    p.segments[0].target_temp = 500.0f;

    for (int i = 0; i < FIRING_MAX_PROFILES; i++) {
        snprintf(p.id, FIRING_ID_LEN, "filler%02d", i);
        TEST_ASSERT_EQUAL(ESP_OK, firing_engine_save_profile(&p));
    }

    snprintf(p.id, FIRING_ID_LEN, "filler00");
    strncpy(p.name, "Updated", FIRING_NAME_LEN - 1);
    TEST_ASSERT_EQUAL_MESSAGE(ESP_OK, firing_engine_save_profile(&p), "update of an existing profile was refused");
}

static void test_profile_key_collision_rejected(void)
{
    firing_profile_t a = {0};
    strncpy(a.id, "verylongprofile-AAA", FIRING_ID_LEN - 1); /* first 15 chars: "verylongprofile" */
    strncpy(a.name, "Profile A", FIRING_NAME_LEN - 1);
    a.segment_count = 1;
    a.segments[0].ramp_rate = 100.0f;
    a.segments[0].target_temp = 500.0f;

    firing_profile_t b = a;
    strncpy(b.id, "verylongprofile-BBB", FIRING_ID_LEN - 1);
    strncpy(b.name, "Profile B", FIRING_NAME_LEN - 1);

    TEST_ASSERT_EQUAL(ESP_OK, firing_engine_save_profile(&a));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE, firing_engine_save_profile(&b));

    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    TEST_ASSERT_EQUAL_INT(1, firing_engine_list_profiles(ids, FIRING_MAX_PROFILES));

    /* A's blob must be intact — not silently overwritten by B. */
    firing_profile_t loaded;
    TEST_ASSERT_EQUAL(ESP_OK, firing_engine_load_profile("verylongprofile-AAA", &loaded));
    TEST_ASSERT_EQUAL_STRING("Profile A", loaded.name);

    /* A non-colliding ID still saves. */
    firing_profile_t c = a;
    strncpy(c.id, "shortid", FIRING_ID_LEN - 1);
    strncpy(c.name, "Profile C", FIRING_NAME_LEN - 1);
    TEST_ASSERT_EQUAL(ESP_OK, firing_engine_save_profile(&c));
    TEST_ASSERT_EQUAL_INT(2, firing_engine_list_profiles(ids, FIRING_MAX_PROFILES));
}

/* ── Trip cause maps to a specific firing error code (#72) ──────────────── */

static void test_tc_fault_cause_maps_to_tc_fault_error(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    safety_emergency_stop_cause(SAFETY_TRIP_TC_FAULT);
    scenario_run_ticks(&g_plant, 1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_ERROR, prog.status);
    TEST_ASSERT_EQUAL(FIRING_ERR_TC_FAULT, firing_engine_get_error_code());
}

static void test_over_temp_cause_maps_to_over_temp_error(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 30));

    safety_emergency_stop_cause(SAFETY_TRIP_OVER_TEMP);
    scenario_run_ticks(&g_plant, 1);

    TEST_ASSERT_EQUAL(FIRING_ERR_OVER_TEMP, firing_engine_get_error_code());
}

/* ── Completion event carries the true peak and the profile name (#73) ──── */

static void test_event_reports_true_peak_and_profile_name(void)
{
    firing_profile_t p = {0};
    strncpy(p.id, "peak-name", FIRING_ID_LEN - 1);
    strncpy(p.name, "Peak Name Test", FIRING_NAME_LEN - 1);
    p.segment_count = 2;
    p.max_temp = 250.0f;
    p.estimated_duration = 20;
    p.segments[0].ramp_rate = 12000.0f; /* heat to 250 */
    p.segments[0].target_temp = 250.0f;
    p.segments[0].hold_time = 0;
    p.segments[1].ramp_rate = -12000.0f; /* cool to 100 */
    p.segments[1].target_temp = 100.0f;
    p.segments[1].hold_time = 0;

    scenario_start(&p, 0);
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_COMPLETE, 15 * 60));

    firing_event_t evt;
    TEST_ASSERT_EQUAL(pdTRUE, xQueueReceive(firing_engine_get_event_queue(), &evt, 0));
    TEST_ASSERT_EQUAL(FIRING_EVENT_COMPLETE, evt.kind);
    TEST_ASSERT_EQUAL_STRING("Peak Name Test", evt.profile_name);
    /* Final temp is ~100°C (cool-down), but the peak reached ~250°C. */
    TEST_ASSERT_TRUE_MESSAGE(evt.peak_temp > 200.0f, "event peak should be the max reached, not the final temp");
}

/* ── Delay-start command guards (#74) ───────────────────────────────────── */

static void test_skip_ignored_during_delay(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 2); /* 2-minute delay */
    scenario_run_ticks(&g_plant, 30);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_IDLE, prog.status);
    TEST_ASSERT_TRUE(prog.is_active);

    scenario_skip(); /* must be ignored while the start is still armed */
    scenario_run_ticks(&g_plant, 1);
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_IDLE, prog.status);
    TEST_ASSERT_EQUAL_UINT8(0, prog.current_segment);

    /* Delay still expires and the firing starts cleanly from segment 0. */
    TEST_ASSERT_TRUE(scenario_run_until_status(&g_plant, FIRING_STATUS_HEATING, 90));
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL_UINT8(0, prog.current_segment);
}

static void test_emergency_during_delay_cancels_firing(void)
{
    firing_profile_t p = scenario_short_profile();
    scenario_start(&p, 2);
    scenario_run_ticks(&g_plant, 5);

    safety_emergency_stop();
    scenario_run_ticks(&g_plant, 1);

    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    TEST_ASSERT_EQUAL(FIRING_STATUS_ERROR, prog.status);
    TEST_ASSERT_FALSE(prog.is_active);

    /* Past the delay window, the cancelled firing must not start. */
    scenario_run_ticks(&g_plant, 3 * 60);
    firing_engine_get_progress(&prog);
    TEST_ASSERT_FALSE(prog.is_active);
    TEST_ASSERT_EQUAL(FIRING_STATUS_ERROR, prog.status);
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
    RUN_TEST(test_skip_while_paused_does_not_resume_heating);
    RUN_TEST(test_skip_after_resume_still_advances_segment);
    RUN_TEST(test_autotune_start_rejected_during_active_firing);
    RUN_TEST(test_autotune_rejects_nan_setpoint);
    RUN_TEST(test_autotune_rejects_over_max_setpoint);
    RUN_TEST(test_autotune_starts_when_no_firing_is_active);
    RUN_TEST(test_pause_resume_during_autotune_restores_autotune);
    RUN_TEST(test_pause_resume_during_cooling_restores_cooling);
    RUN_TEST(test_skip_out_of_long_hold_does_not_trip_not_rising);
    RUN_TEST(test_skip_out_of_hold_still_arms_not_rising);
    RUN_TEST(test_delayed_start_not_judged_by_arm_time_temperature);
    RUN_TEST(test_delayed_start_rejects_wrong_sign_at_expiry);
    RUN_TEST(test_skip_rejects_wrong_sign_next_segment);
    RUN_TEST(test_autotune_resume_does_not_time_out_after_long_pause);
    RUN_TEST(test_relay_test_reasserts_ssr_every_tick);
    RUN_TEST(test_relay_test_releases_ssr_when_duration_elapses);
    RUN_TEST(test_relay_test_active_is_observable);
    RUN_TEST(test_relay_test_does_not_extend_on_overlap);
    RUN_TEST(test_stop_cancels_relay_test);
    RUN_TEST(test_relay_test_rejected_while_firing_active);
    RUN_TEST(test_start_rejected_while_relay_test_running);
    RUN_TEST(test_start_rejects_wrong_sign_ramp);
    RUN_TEST(test_start_allows_legitimate_cooling_segment);
    RUN_TEST(test_tc_fault_triggers_emergency_stop);
    RUN_TEST(test_kiln_not_rising_trips_emergency_stop);
    RUN_TEST(test_runaway_trips_emergency_stop);
    RUN_TEST(test_tc_fault_holds_ssr_off);
    RUN_TEST(test_long_pause_does_not_trip_not_rising);
    RUN_TEST(test_pause_does_not_jump_setpoint);
    RUN_TEST(test_element_hours_accumulate_subsecond_ticks);
    RUN_TEST(test_profile_save_rejected_when_index_full);
    RUN_TEST(test_profile_update_still_allowed_when_index_full);
    RUN_TEST(test_profile_key_collision_rejected);
    RUN_TEST(test_tc_fault_cause_maps_to_tc_fault_error);
    RUN_TEST(test_over_temp_cause_maps_to_over_temp_error);
    RUN_TEST(test_event_reports_true_peak_and_profile_name);
    RUN_TEST(test_skip_ignored_during_delay);
    RUN_TEST(test_emergency_during_delay_cancels_firing);
    return UNITY_END();
}
