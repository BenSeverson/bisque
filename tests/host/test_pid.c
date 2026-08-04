#include "esp_timer.h"
#include "nvs.h"
#include "pid_control.h"
#include "unity.h"

#include <math.h>

void setUp(void)
{
    nvs_reset_for_test();
    host_clock_set(0);
}
void tearDown(void)
{
}

/* ── pid_compute ────────────────────────────────────────────────────────── */

static void test_pid_first_run_skips_derivative_term(void)
{
    pid_controller_t pid;
    pid_init(&pid, /*kp*/ 1.0f, /*ki*/ 0.0f, /*kd*/ 100.0f, 0.0f, 1.0f);
    /* First call: D term is zero regardless of error, so output is just kp*error. */
    float out = pid_compute(&pid, 100.0f, 90.0f, 1.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 1.0f, out); /* clamped, kp*10=10 → 1.0 */
}

static void test_pid_clamps_to_output_max(void)
{
    pid_controller_t pid;
    pid_init(&pid, 10.0f, 0.0f, 0.0f, 0.0f, 1.0f);
    float out = pid_compute(&pid, 100.0f, 0.0f, 1.0f); /* kp*100 = 1000 → clamp 1.0 */
    TEST_ASSERT_EQUAL_FLOAT(1.0f, out);
}

static void test_pid_clamps_to_output_min(void)
{
    pid_controller_t pid;
    pid_init(&pid, 10.0f, 0.0f, 0.0f, 0.0f, 1.0f);
    /* Overshoot: measured way above setpoint → negative error → clamp to 0. */
    float out = pid_compute(&pid, 50.0f, 150.0f, 1.0f);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, out);
}

static void test_pid_returns_min_for_nonpositive_dt(void)
{
    pid_controller_t pid;
    pid_init(&pid, 1.0f, 0.5f, 0.0f, 0.0f, 1.0f);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, pid_compute(&pid, 100.0f, 0.0f, 0.0f));
    TEST_ASSERT_EQUAL_FLOAT(0.0f, pid_compute(&pid, 100.0f, 0.0f, -0.5f));
}

static void test_pid_integral_accumulates(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.1f, 0.0f, 0.0f, 1.0f); /* I-only */
    /* Each tick of error=5 at dt=1s adds integral += 5; output = 0.1 * integral. */
    float out1 = pid_compute(&pid, 10.0f, 5.0f, 1.0f); /* integral=5 → out 0.5 */
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.5f, out1);
    float out2 = pid_compute(&pid, 10.0f, 5.0f, 1.0f); /* integral=10 → clamp 1.0 */
    TEST_ASSERT_EQUAL_FLOAT(1.0f, out2);
}

static void test_pid_anti_windup_holds_integral_at_clamp(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.1f, 0.0f, 0.0f, 1.0f);
    /* Drive output to the max clamp and keep error positive for many ticks. */
    for (int i = 0; i < 20; i++) {
        pid_compute(&pid, 10.0f, 5.0f, 1.0f);
    }
    /* If anti-windup works, a single tick of opposite error should immediately
       reduce output below max; without it, the integral would be huge and
       output would stay clamped for many ticks. */
    float out = pid_compute(&pid, 10.0f, 11.0f, 1.0f);
    TEST_ASSERT_TRUE(out < 1.0f);
}

static void test_pid_reset_clears_integral_and_derivative(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.1f, 0.0f, 0.0f, 1.0f);
    pid_compute(&pid, 10.0f, 5.0f, 1.0f); /* integral now 5 */
    pid_compute(&pid, 10.0f, 5.0f, 1.0f); /* integral now 10 */
    pid_reset(&pid);
    /* After reset, the first call behaves as first_run (no derivative) and
       integral starts from zero. */
    float out = pid_compute(&pid, 10.0f, 5.0f, 1.0f); /* integral=5 → out 0.5 */
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.5f, out);
}

/* Derivative acts on the *measurement* (not the error) and is low-pass
   filtered. For a rising measurement the term is negative (damping); its
   magnitude is the filtered rate, so a single step is attenuated by the filter
   rather than applied in full. */
static void test_pid_derivative_on_measurement_signs(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.0f, 1.0f, -10.0f, 10.0f);    /* D-only, wide clamp */
    pid_compute(&pid, 100.0f, 80.0f, 1.0f);             /* first run seeds prev_measured, out=0 */
    float out = pid_compute(&pid, 100.0f, 90.0f, 1.0f); /* meas +10/s, filtered → damping */
    /* d_meas=10, filter alpha at dt=1 is 0.25 → d_filtered=2.5 → -kd*2.5. */
    TEST_ASSERT_FLOAT_WITHIN(0.01f, -2.5f, out);
}

/* Derivative-on-measurement means a setpoint step produces no derivative kick —
   the old derivative-on-error would spike here at every segment/skip
   transition. */
static void test_pid_derivative_ignores_setpoint_step(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.0f, 1.0f, -10.0f, 10.0f);
    pid_compute(&pid, 50.0f, 50.0f, 1.0f);              /* seed at steady measurement */
    pid_compute(&pid, 50.0f, 50.0f, 1.0f);              /* still steady */
    float out = pid_compute(&pid, 100.0f, 50.0f, 1.0f); /* setpoint jumps, measurement flat */
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, out);
}

/* One 0.25°C sensor LSB must not swing the derivative term across the output
   range. With the old Kd=50, unfiltered, this produced 12.5 (12.5× the whole
   [0,1] range); filtered and with a sane gain it stays a small fraction. */
static void test_pid_derivative_filter_attenuates_sensor_lsb(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.0f, 10.0f, -100.0f, 100.0f);  /* D-only, wide clamp, no saturation */
    pid_compute(&pid, 100.0f, 50.0f, 1.0f);              /* seed */
    float out = pid_compute(&pid, 100.0f, 50.25f, 1.0f); /* +1 LSB blip */
    TEST_ASSERT_TRUE_MESSAGE(out < 0.0f, "rising measurement should damp (negative D term)");
    TEST_ASSERT_TRUE_MESSAGE(fabsf(out) < 1.0f, "single-LSB derivative term swung most of the output range");
}

/* Reset must clear the new derivative-filter state (prev_measured, d_filtered),
   not just first_run — otherwise a stale filtered rate leaks into the next
   firing on the second post-reset tick. */
static void test_pid_reset_clears_derivative_filter(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.0f, 1.0f, -10.0f, 10.0f);
    pid_compute(&pid, 100.0f, 50.0f, 1.0f);
    pid_compute(&pid, 100.0f, 90.0f, 1.0f); /* d_filtered now well above zero */
    pid_reset(&pid);
    pid_compute(&pid, 100.0f, 50.0f, 1.0f);             /* post-reset first call: derivative skipped */
    float out = pid_compute(&pid, 100.0f, 50.0f, 1.0f); /* steady → term must be ~0, not the stale rate */
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, out);
}

/* ── pid_load_gains defaults / save & reload roundtrip ──────────────────── */

static void test_pid_load_returns_defaults_when_no_nvs(void)
{
    float kp = 0, ki = 0, kd = 0;
    esp_err_t err = pid_load_gains(&kp, &ki, &kd);
    TEST_ASSERT_EQUAL(ESP_ERR_NVS_NOT_FOUND, err);
    /* Defaults are set even on the not-found path. */
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 2.0f, kp);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.01f, ki);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 5.0f, kd);
}

static void test_pid_save_and_load_roundtrip(void)
{
    TEST_ASSERT_EQUAL(ESP_OK, pid_save_gains(1.2345f, 0.6789f, 12.34f));
    float kp = 0, ki = 0, kd = 0;
    TEST_ASSERT_EQUAL(ESP_OK, pid_load_gains(&kp, &ki, &kd));
    /* Persisted as int32 × 10000, so ~1e-4 precision. */
    TEST_ASSERT_FLOAT_WITHIN(0.0001f, 1.2345f, kp);
    TEST_ASSERT_FLOAT_WITHIN(0.0001f, 0.6789f, ki);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 12.34f, kd);
}

/* ── manual gain entry (#182) ───────────────────────────────────────────── */

static void test_gains_valid_accepts_defaults_and_bounds(void)
{
    float kp, ki, kd;
    pid_default_gains(&kp, &ki, &kd);
    TEST_ASSERT_TRUE(pid_gains_valid(kp, ki, kd));

    /* Both ends of the published range, and a plausible hand-entered set from
       another controller. */
    TEST_ASSERT_TRUE(pid_gains_valid(PID_GAIN_MAX, PID_GAIN_MAX, PID_GAIN_MAX));
    TEST_ASSERT_TRUE(pid_gains_valid(0.0f, PID_GAIN_MIN + 0.0001f, 0.0f));
    TEST_ASSERT_TRUE(pid_gains_valid(18.0f, 0.12f, 240.0f));
}

static void test_gains_valid_rejects_out_of_range_and_nonfinite(void)
{
    TEST_ASSERT_FALSE(pid_gains_valid(-1.0f, 0.01f, 5.0f));
    TEST_ASSERT_FALSE(pid_gains_valid(2.0f, -0.01f, 5.0f));
    TEST_ASSERT_FALSE(pid_gains_valid(2.0f, 0.01f, -5.0f));
    TEST_ASSERT_FALSE(pid_gains_valid(PID_GAIN_MAX + 1.0f, 0.01f, 5.0f));

    /* NaN compares false against both bounds, so a range check alone lets it
       through — the isfinite() screen is what catches it. */
    TEST_ASSERT_FALSE(pid_gains_valid(NAN, 0.01f, 5.0f));
    TEST_ASSERT_FALSE(pid_gains_valid(2.0f, INFINITY, 5.0f));
    TEST_ASSERT_FALSE(pid_gains_valid(2.0f, 0.01f, -INFINITY));
}

static void test_gains_valid_rejects_controller_that_cannot_heat(void)
{
    /* Derivative-only: no term grows with distance from the setpoint, so the
       kiln stalls short of target and looks like broken hardware. */
    TEST_ASSERT_FALSE(pid_gains_valid(0.0f, 0.0f, 5.0f));
    TEST_ASSERT_FALSE(pid_gains_valid(0.0f, 0.0f, 0.0f));

    /* Either one alone is a legitimate (if unusual) controller. */
    TEST_ASSERT_TRUE(pid_gains_valid(2.0f, 0.0f, 0.0f));
    TEST_ASSERT_TRUE(pid_gains_valid(0.0f, 0.01f, 0.0f));
}

static void test_quantize_matches_what_nvs_stores(void)
{
    /* The point of pid_quantize_gain: applying it before pid_init() is what
       makes the live controller and the next boot agree. */
    const float entered[] = {1.23456f, 0.000049f, 987.65432f, 0.0f};
    for (unsigned i = 0; i < sizeof(entered) / sizeof(entered[0]); i++) {
        float q = pid_quantize_gain(entered[i]);
        TEST_ASSERT_EQUAL(ESP_OK, pid_save_gains(q, q, q));
        float kp = -1, ki = -1, kd = -1;
        TEST_ASSERT_EQUAL(ESP_OK, pid_load_gains(&kp, &ki, &kd));
        TEST_ASSERT_EQUAL_FLOAT(q, kp);
        TEST_ASSERT_EQUAL_FLOAT(q, ki);
        TEST_ASSERT_EQUAL_FLOAT(q, kd);
    }
}

static void test_quantize_is_idempotent_across_the_float_round_trip(void)
{
    /* The bug this guards: with truncation, 0.00071 quantized to 0.0007, whose
       nearest float is 0.00069999…, so pid_save_gains multiplying by 10000
       again yielded 6.9999 and stored 0.0006 — 14% off the gain the caller was
       told was kept. Quantizing twice must be the same as quantizing once, and
       saving a quantized gain must load back unchanged. */
    const float entered[] = {0.00071f, 0.03821f, 0.1234f, 7.7777f, 1234.5678f};
    for (unsigned i = 0; i < sizeof(entered) / sizeof(entered[0]); i++) {
        float once = pid_quantize_gain(entered[i]);
        TEST_ASSERT_EQUAL_FLOAT(once, pid_quantize_gain(once));

        TEST_ASSERT_EQUAL(ESP_OK, pid_save_gains(once, once, once));
        float kp = -1, ki = -1, kd = -1;
        TEST_ASSERT_EQUAL(ESP_OK, pid_load_gains(&kp, &ki, &kd));
        TEST_ASSERT_EQUAL_FLOAT(once, kp);
        TEST_ASSERT_EQUAL_FLOAT(once, ki);
        TEST_ASSERT_EQUAL_FLOAT(once, kd);
    }
}

static void test_quantize_can_zero_a_gain_below_nvs_resolution(void)
{
    /* Why callers re-validate after quantizing: 4e-5 is a positive Kp on entry
       and a zero once stored (it rounds to nothing at 1e-4 resolution), which
       with Ki at zero is the dead controller pid_gains_valid() exists to
       reject. */
    float kp = pid_quantize_gain(0.00004f);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, kp);
    TEST_ASSERT_TRUE(pid_gains_valid(0.00004f, 0.0f, 5.0f));
    TEST_ASSERT_FALSE(pid_gains_valid(kp, 0.0f, 5.0f));

    /* Just above the halfway point it survives, because the encoding rounds to
       nearest rather than truncating. */
    TEST_ASSERT_EQUAL_FLOAT(0.0001f, pid_quantize_gain(0.00006f));
}

/* ── autotune ───────────────────────────────────────────────────────────── */

static void test_autotune_rejects_invalid_args(void)
{
    pid_autotune_t at;
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, pid_autotune_start(&at, 0.0f, 1.0f));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, pid_autotune_start(&at, 100.0f, 0.0f));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, pid_autotune_start(&at, -10.0f, 5.0f));
    /* NaN slips past a bare `<= 0` check (every comparison with NaN is false),
       so it must be rejected explicitly. */
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, pid_autotune_start(&at, NAN, 5.0f));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, pid_autotune_start(&at, 500.0f, NAN));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, pid_autotune_start(&at, INFINITY, 5.0f));
}

static void test_autotune_starts_in_heating_state(void)
{
    pid_autotune_t at;
    TEST_ASSERT_EQUAL(ESP_OK, pid_autotune_start(&at, 100.0f, 5.0f));
    TEST_ASSERT_EQUAL(AUTOTUNE_HEATING_TO_SETPOINT, at.state);
    TEST_ASSERT_FALSE(pid_autotune_is_complete(&at));
    /* Initial output is full-on while heating. */
    float out = 0.0f;
    pid_autotune_update(&at, 20.0f, &out);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, out);
}

static void test_autotune_transitions_to_relay_cycling_at_setpoint(void)
{
    pid_autotune_t at;
    pid_autotune_start(&at, 100.0f, 5.0f);
    float out = 0.0f;
    pid_autotune_update(&at, 96.0f, &out); /* reached setpoint - hysteresis */
    TEST_ASSERT_EQUAL(AUTOTUNE_RELAY_CYCLING, at.state);
}

static void test_autotune_completes_with_sane_gains_under_synthetic_oscillation(void)
{
    pid_autotune_t at;
    pid_autotune_start(&at, 100.0f, 5.0f);
    float out = 0.0f;
    /* Push state machine into RELAY_CYCLING. */
    pid_autotune_update(&at, 96.0f, &out);

    /* Simulate symmetric oscillation around the setpoint at a fixed period.
       Each "half cycle" is 30 s of virtual time, peak amplitude 10°C. */
    const int total_half_cycles = 12; /* 5 full cycles → completion */
    for (int hc = 0; hc < total_half_cycles && at.state == AUTOTUNE_RELAY_CYCLING; hc++) {
        bool above = (hc % 2) == 0;
        float peak_temp = above ? 110.0f : 90.0f;
        /* Snap to the peak then walk back across the setpoint over 30 s. */
        for (int s = 0; s < 30 && at.state == AUTOTUNE_RELAY_CYCLING; s++) {
            host_clock_advance(1000000); /* +1 s */
            float t = above ? (110.0f - 0.667f * s) : (90.0f + 0.667f * s);
            (void)peak_temp;
            pid_autotune_update(&at, t, &out);
        }
    }

    TEST_ASSERT_EQUAL(AUTOTUNE_COMPLETE, at.state);
    TEST_ASSERT_TRUE(pid_autotune_is_complete(&at));
    TEST_ASSERT_TRUE(at.kp_result > 0.0f);
    TEST_ASSERT_TRUE(at.ki_result > 0.0f);
    TEST_ASSERT_TRUE(at.kd_result > 0.0f);
    TEST_ASSERT_TRUE(isfinite(at.kp_result));
    TEST_ASSERT_TRUE(isfinite(at.ki_result));
    TEST_ASSERT_TRUE(isfinite(at.kd_result));
}

static void test_autotune_ku_uses_relay_half_amplitude(void)
{
    pid_autotune_t at;
    pid_autotune_start(&at, 100.0f, 5.0f);
    float out = 0.0f;
    pid_autotune_update(&at, 95.0f, &out); /* enter relay cycling */

    /* Drive a clean square oscillation: 110°C for 20 s, 90°C for 20 s, so every
       measured cycle has amplitude exactly 10°C. */
    for (int s = 1; s <= 400 && at.state == AUTOTUNE_RELAY_CYCLING; s++) {
        host_clock_advance(1000000);
        float t = (((s - 1) / 20) % 2 == 0) ? 110.0f : 90.0f;
        pid_autotune_update(&at, t, &out);
    }

    TEST_ASSERT_EQUAL(AUTOTUNE_COMPLETE, at.state);
    /* Ku = 4d/(πa) with relay half-amplitude d = 0.5 → Ku = 2/(π·10) = 0.063662,
       so kp = 0.6·Ku = 0.038197. The pre-fix numerator of 4.0 would double this
       to ~0.0764. kp depends only on amplitude, so the assertion is tight. */
    TEST_ASSERT_FLOAT_WITHIN(0.0005f, 0.038197f, at.kp_result);
}

static void test_autotune_timeout_resets_when_cycling_starts(void)
{
    pid_autotune_t at;
    pid_autotune_start(&at, 100.0f, 5.0f);
    float out = 0.0f;

    /* Spend 50 min heating to setpoint (under the 60-min heat-up budget). */
    host_clock_advance(50LL * 60 * 1000000);
    pid_autotune_update(&at, 20.0f, &out);
    TEST_ASSERT_EQUAL(AUTOTUNE_HEATING_TO_SETPOINT, at.state);

    /* Reach setpoint → cycling. The cycling timeout must start fresh; if it
       inherited the 50 min already elapsed, 30 more min would trip the 60-min
       cap and fail. */
    pid_autotune_update(&at, 96.0f, &out);
    TEST_ASSERT_EQUAL(AUTOTUNE_RELAY_CYCLING, at.state);

    host_clock_advance(30LL * 60 * 1000000);
    bool done = pid_autotune_update(&at, 101.0f, &out);
    TEST_ASSERT_FALSE(done);
    TEST_ASSERT_EQUAL(AUTOTUNE_RELAY_CYCLING, at.state);
}

static void test_autotune_times_out_after_60_minutes(void)
{
    pid_autotune_t at;
    pid_autotune_start(&at, 100.0f, 5.0f);
    float out = 0.0f;
    /* Advance virtual time past the timeout (60 min). Use a temp below the
       hysteresis band so we never leave HEATING_TO_SETPOINT on our own. */
    host_clock_advance(61LL * 60 * 1000000);
    bool done = pid_autotune_update(&at, 20.0f, &out);
    TEST_ASSERT_TRUE(done);
    TEST_ASSERT_EQUAL(AUTOTUNE_FAILED, at.state);
}

static void test_autotune_cancel_returns_to_idle(void)
{
    pid_autotune_t at;
    pid_autotune_start(&at, 100.0f, 5.0f);
    pid_autotune_cancel(&at);
    TEST_ASSERT_EQUAL(AUTOTUNE_IDLE, at.state);
    /* Update on an idle controller returns done=true with output 0. */
    float out = 0.5f;
    bool done = pid_autotune_update(&at, 50.0f, &out);
    TEST_ASSERT_TRUE(done);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, out);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_pid_first_run_skips_derivative_term);
    RUN_TEST(test_pid_clamps_to_output_max);
    RUN_TEST(test_pid_clamps_to_output_min);
    RUN_TEST(test_pid_returns_min_for_nonpositive_dt);
    RUN_TEST(test_pid_integral_accumulates);
    RUN_TEST(test_pid_anti_windup_holds_integral_at_clamp);
    RUN_TEST(test_pid_reset_clears_integral_and_derivative);
    RUN_TEST(test_pid_derivative_on_measurement_signs);
    RUN_TEST(test_pid_derivative_ignores_setpoint_step);
    RUN_TEST(test_pid_derivative_filter_attenuates_sensor_lsb);
    RUN_TEST(test_pid_reset_clears_derivative_filter);
    RUN_TEST(test_pid_load_returns_defaults_when_no_nvs);
    RUN_TEST(test_pid_save_and_load_roundtrip);
    RUN_TEST(test_gains_valid_accepts_defaults_and_bounds);
    RUN_TEST(test_gains_valid_rejects_out_of_range_and_nonfinite);
    RUN_TEST(test_gains_valid_rejects_controller_that_cannot_heat);
    RUN_TEST(test_quantize_matches_what_nvs_stores);
    RUN_TEST(test_quantize_is_idempotent_across_the_float_round_trip);
    RUN_TEST(test_quantize_can_zero_a_gain_below_nvs_resolution);
    RUN_TEST(test_autotune_rejects_invalid_args);
    RUN_TEST(test_autotune_starts_in_heating_state);
    RUN_TEST(test_autotune_transitions_to_relay_cycling_at_setpoint);
    RUN_TEST(test_autotune_completes_with_sane_gains_under_synthetic_oscillation);
    RUN_TEST(test_autotune_ku_uses_relay_half_amplitude);
    RUN_TEST(test_autotune_timeout_resets_when_cycling_starts);
    RUN_TEST(test_autotune_times_out_after_60_minutes);
    RUN_TEST(test_autotune_cancel_returns_to_idle);
    return UNITY_END();
}
