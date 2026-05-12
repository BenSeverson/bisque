#include "firing_engine_internal.h"
#include "firing_types.h"
#include "unity.h"

#include <math.h>

void setUp(void)
{
}
void tearDown(void)
{
}

/* ── compute_dynamic_setpoint ──────────────────────────────────────────── */

static firing_segment_t heating_seg(float target, float ramp_per_hr)
{
    firing_segment_t s = {0};
    s.target_temp = target;
    s.ramp_rate = ramp_per_hr;
    return s;
}

static void test_holding_returns_target_temp(void)
{
    firing_segment_t seg = heating_seg(1222.0f, 100.0f);
    /* now_us irrelevant when holding */
    TEST_ASSERT_EQUAL_FLOAT(1222.0f, compute_dynamic_setpoint(&seg, 200.0f, 0, 9999999, true));
}

static void test_heating_setpoint_advances_at_ramp_rate(void)
{
    firing_segment_t seg = heating_seg(1000.0f, 360.0f); /* 360°C/hr = 0.1°C/s */
    /* 30 s into segment from 200°C: expected 203°C */
    float sp = compute_dynamic_setpoint(&seg, 200.0f, 0, 30LL * 1000000, false);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 203.0f, sp);
}

static void test_heating_setpoint_clamps_to_target(void)
{
    firing_segment_t seg = heating_seg(250.0f, 360.0f);                             /* would reach target at ~500 s */
    float sp = compute_dynamic_setpoint(&seg, 200.0f, 0, 10000LL * 1000000, false); /* way past */
    TEST_ASSERT_EQUAL_FLOAT(250.0f, sp);
}

static void test_cooling_setpoint_advances_downward(void)
{
    firing_segment_t seg = heating_seg(500.0f, -180.0f); /* -180°C/hr = -0.05°C/s */
    /* 60 s into segment from 800°C: expected 797°C */
    float sp = compute_dynamic_setpoint(&seg, 800.0f, 0, 60LL * 1000000, false);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 797.0f, sp);
}

static void test_cooling_setpoint_clamps_to_target(void)
{
    firing_segment_t seg = heating_seg(400.0f, -360.0f);
    /* would reach target after ~2000 s; supply 10000 s elapsed */
    float sp = compute_dynamic_setpoint(&seg, 800.0f, 0, 10000LL * 1000000, false);
    TEST_ASSERT_EQUAL_FLOAT(400.0f, sp);
}

static void test_setpoint_uses_seg_start_us_not_absolute(void)
{
    firing_segment_t seg = heating_seg(1000.0f, 3600.0f); /* 1°C/s */
    /* Segment started at t=1000s; current t=1010s → 10s elapsed → +10°C */
    float sp = compute_dynamic_setpoint(&seg, 500.0f, 1000LL * 1000000, 1010LL * 1000000, false);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 510.0f, sp);
}

/* ── at_target_predicate ───────────────────────────────────────────────── */

static void test_at_target_true_when_both_within_band(void)
{
    /* current within 2°C and setpoint within 0.5°C of target */
    TEST_ASSERT_TRUE(at_target_predicate(1221.0f, 1222.3f, 1222.0f));
}

static void test_at_target_false_when_current_too_far(void)
{
    /* current 4°C below target — should NOT signal at-target */
    TEST_ASSERT_FALSE(at_target_predicate(1218.0f, 1222.0f, 1222.0f));
}

static void test_at_target_false_when_setpoint_still_ramping(void)
{
    /* current happens to be at target by chance, but setpoint is still 1°C
       short — the planned curve hasn't arrived yet, so don't fire-and-hold. */
    TEST_ASSERT_FALSE(at_target_predicate(1222.0f, 1221.0f, 1222.0f));
}

static void test_at_target_symmetric_above_and_below(void)
{
    /* current 1°C above target, setpoint 0.3°C above — within both bands */
    TEST_ASSERT_TRUE(at_target_predicate(1223.0f, 1222.3f, 1222.0f));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_holding_returns_target_temp);
    RUN_TEST(test_heating_setpoint_advances_at_ramp_rate);
    RUN_TEST(test_heating_setpoint_clamps_to_target);
    RUN_TEST(test_cooling_setpoint_advances_downward);
    RUN_TEST(test_cooling_setpoint_clamps_to_target);
    RUN_TEST(test_setpoint_uses_seg_start_us_not_absolute);
    RUN_TEST(test_at_target_true_when_both_within_band);
    RUN_TEST(test_at_target_false_when_current_too_far);
    RUN_TEST(test_at_target_false_when_setpoint_still_ramping);
    RUN_TEST(test_at_target_symmetric_above_and_below);
    return UNITY_END();
}
