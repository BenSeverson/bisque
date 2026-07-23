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

/* ── firing_remaining_s ────────────────────────────────────────────────── */

/* Two-segment profile at 1°C/s ramps: seg0 → 100°C hold 1 min, seg1 → 200°C
   hold 0. Planned durations (from a 0°C start): seg0 100s ramp + 60s hold,
   seg1 100s ramp. */
static firing_profile_t two_seg_profile(void)
{
    firing_profile_t p = {0};
    p.segment_count = 2;
    p.segments[0].ramp_rate = 3600.0f; /* 1°C/s */
    p.segments[0].target_temp = 100.0f;
    p.segments[0].hold_time = 1; /* 60 s */
    p.segments[1].ramp_rate = 3600.0f;
    p.segments[1].target_temp = 200.0f;
    p.segments[1].hold_time = 0;
    return p;
}

static void test_remaining_ramping_first_segment(void)
{
    firing_profile_t p = two_seg_profile();
    /* Seg 0, at 0°C, ramping: 100s ramp + 60s hold + seg1 (100s ramp) = 260s. */
    TEST_ASSERT_EQUAL_UINT32(260, firing_remaining_s(&p, 0, 0.0f, false, 0.0f));
    /* Halfway up seg 0 (50°C): 50s ramp + 60 + 100 = 210s. */
    TEST_ASSERT_EQUAL_UINT32(210, firing_remaining_s(&p, 0, 50.0f, false, 0.0f));
}

static void test_remaining_holding_counts_only_hold_left(void)
{
    firing_profile_t p = two_seg_profile();
    /* Seg 0 holding, 20s into the 60s hold: 40s hold left + seg1 100s = 140s. */
    TEST_ASSERT_EQUAL_UINT32(140, firing_remaining_s(&p, 0, 100.0f, true, 20.0f));
}

static void test_remaining_does_not_go_blank_past_estimate(void)
{
    firing_profile_t p = two_seg_profile();
    /* Last segment, still 50°C below its 200°C target: 50s ramp remains — the
       old estimate − elapsed scheme would have pinned this to 0. */
    TEST_ASSERT_EQUAL_UINT32(50, firing_remaining_s(&p, 1, 150.0f, false, 0.0f));
}

static void test_remaining_cooling_segment(void)
{
    firing_profile_t p = {0};
    p.segment_count = 1;
    p.segments[0].ramp_rate = -3600.0f; /* -1°C/s */
    p.segments[0].target_temp = 100.0f;
    p.segments[0].hold_time = 0;
    /* From 200°C cooling to 100°C: 100s. */
    TEST_ASSERT_EQUAL_UINT32(100, firing_remaining_s(&p, 0, 200.0f, false, 0.0f));
    /* Overshoot below target adds no negative time. */
    TEST_ASSERT_EQUAL_UINT32(0, firing_remaining_s(&p, 0, 90.0f, false, 0.0f));
}

static void test_remaining_indefinite_hold_contributes_zero(void)
{
    firing_profile_t p = two_seg_profile();
    p.segments[0].hold_time = FIRING_HOLD_INDEFINITE;
    /* Seg 0 holding indefinitely: unknown duration → 0 for this segment, plus
       seg1's 100s ramp. */
    TEST_ASSERT_EQUAL_UINT32(100, firing_remaining_s(&p, 0, 100.0f, true, 5.0f));
}

static void test_remaining_handles_out_of_range_and_null(void)
{
    firing_profile_t p = two_seg_profile();
    TEST_ASSERT_EQUAL_UINT32(0, firing_remaining_s(NULL, 0, 0.0f, false, 0.0f));
    TEST_ASSERT_EQUAL_UINT32(0, firing_remaining_s(&p, 2, 0.0f, false, 0.0f));
    TEST_ASSERT_EQUAL_UINT32(0, firing_remaining_s(&p, -1, 0.0f, false, 0.0f));
}

/* ── firing_first_bad_ramp_sign (#113) ─────────────────────────────────── */

/* Build a profile from a list of {ramp_rate, target} pairs. */
static firing_profile_t sign_profile(int n, const float ramps[], const float targets[])
{
    firing_profile_t p = {0};
    p.segment_count = (uint8_t)n;
    for (int i = 0; i < n; i++) {
        p.segments[i].ramp_rate = ramps[i];
        p.segments[i].target_temp = targets[i];
    }
    return p;
}

static void test_bad_sign_all_consistent_returns_none(void)
{
    /* Heat 25→600, then cool 600→300: both signs match their direction. */
    float ramps[] = {300.0f, -200.0f};
    float targets[] = {600.0f, 300.0f};
    firing_profile_t p = sign_profile(2, ramps, targets);
    TEST_ASSERT_EQUAL_INT(-1, firing_first_bad_ramp_sign(&p, 25.0f));
}

/* The #113 repro: negative ramp toward a target above the start temperature. */
static void test_bad_sign_negative_ramp_toward_higher_target(void)
{
    float ramps[] = {-100.0f};
    float targets[] = {1200.0f};
    firing_profile_t p = sign_profile(1, ramps, targets);
    TEST_ASSERT_EQUAL_INT(0, firing_first_bad_ramp_sign(&p, 400.0f));
}

/* Mirror image: positive ramp toward a target below the start temperature. */
static void test_bad_sign_positive_ramp_toward_lower_target(void)
{
    float ramps[] = {100.0f};
    float targets[] = {300.0f};
    firing_profile_t p = sign_profile(1, ramps, targets);
    TEST_ASSERT_EQUAL_INT(0, firing_first_bad_ramp_sign(&p, 600.0f));
}

/* Segment 0 is fine, but segment 1 cools toward a higher target. Its start is
 * segment 0's target (600), not the kiln's 25°C. */
static void test_bad_sign_intersegment_inconsistency(void)
{
    float ramps[] = {300.0f, -100.0f};
    float targets[] = {600.0f, 900.0f};
    firing_profile_t p = sign_profile(2, ramps, targets);
    TEST_ASSERT_EQUAL_INT(1, firing_first_bad_ramp_sign(&p, 25.0f));
}

/* Non-finite start_temp skips segment 0's own check (save-time use) but still
 * validates later segments against their prior target. */
static void test_bad_sign_nan_start_skips_segment0_only(void)
{
    float ramps1[] = {-100.0f};
    float targets1[] = {1200.0f};
    firing_profile_t p1 = sign_profile(1, ramps1, targets1);
    TEST_ASSERT_EQUAL_INT(-1, firing_first_bad_ramp_sign(&p1, NAN));

    float ramps2[] = {300.0f, -100.0f};
    float targets2[] = {600.0f, 900.0f};
    firing_profile_t p2 = sign_profile(2, ramps2, targets2);
    TEST_ASSERT_EQUAL_INT(1, firing_first_bad_ramp_sign(&p2, NAN));
}

/* A segment whose target equals its start imposes no direction — a nonzero
 * ramp of either sign is a harmless instant-clamp, not a violation. */
static void test_bad_sign_equal_target_not_flagged(void)
{
    float ramps[] = {-100.0f};
    float targets[] = {600.0f};
    firing_profile_t p = sign_profile(1, ramps, targets);
    TEST_ASSERT_EQUAL_INT(-1, firing_first_bad_ramp_sign(&p, 600.0f));
}

static void test_bad_sign_null_and_empty(void)
{
    TEST_ASSERT_EQUAL_INT(-1, firing_first_bad_ramp_sign(NULL, 25.0f));
    firing_profile_t empty = {0};
    TEST_ASSERT_EQUAL_INT(-1, firing_first_bad_ramp_sign(&empty, 25.0f));
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
    RUN_TEST(test_remaining_ramping_first_segment);
    RUN_TEST(test_remaining_holding_counts_only_hold_left);
    RUN_TEST(test_remaining_does_not_go_blank_past_estimate);
    RUN_TEST(test_remaining_cooling_segment);
    RUN_TEST(test_remaining_indefinite_hold_contributes_zero);
    RUN_TEST(test_remaining_handles_out_of_range_and_null);
    RUN_TEST(test_bad_sign_all_consistent_returns_none);
    RUN_TEST(test_bad_sign_negative_ramp_toward_higher_target);
    RUN_TEST(test_bad_sign_positive_ramp_toward_lower_target);
    RUN_TEST(test_bad_sign_intersegment_inconsistency);
    RUN_TEST(test_bad_sign_nan_start_skips_segment0_only);
    RUN_TEST(test_bad_sign_equal_target_not_flagged);
    RUN_TEST(test_bad_sign_null_and_empty);
    return UNITY_END();
}
