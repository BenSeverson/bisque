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

static void test_pid_derivative_on_error_signs(void)
{
    pid_controller_t pid;
    pid_init(&pid, 0.0f, 0.0f, 1.0f, -10.0f, 10.0f); /* D-only, wide clamp */
    /* First call seeds prev_error; subsequent compute uses (e - prev_e)/dt. */
    pid_compute(&pid, 100.0f, 80.0f, 1.0f);             /* e=20, first run → out=0 */
    float out = pid_compute(&pid, 100.0f, 90.0f, 1.0f); /* e=10, de=-10 → out=-10 */
    TEST_ASSERT_FLOAT_WITHIN(0.001f, -10.0f, out);
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
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 50.0f, kd);
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
    RUN_TEST(test_pid_derivative_on_error_signs);
    RUN_TEST(test_pid_load_returns_defaults_when_no_nvs);
    RUN_TEST(test_pid_save_and_load_roundtrip);
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
