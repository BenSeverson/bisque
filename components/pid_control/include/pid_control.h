#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* --- PID Controller --- */

typedef struct {
    float kp;
    float ki;
    float kd;
    float output_min;
    float output_max;
    /* Internal state */
    float integral;
    float prev_error;    /* retained for compatibility; no longer used by the D term */
    float prev_measured; /* derivative is taken on the measurement, not the error */
    float d_filtered;    /* low-pass-filtered measurement derivative */
    bool first_run;
} pid_controller_t;

/**
 * Initialize a PID controller with the given gains and output limits.
 */
void pid_init(pid_controller_t *pid, float kp, float ki, float kd, float output_min, float output_max);

/**
 * Reset internal state (integral, derivative memory).
 */
void pid_reset(pid_controller_t *pid);

/**
 * Compute one PID iteration.
 *
 * @param pid       Controller state
 * @param setpoint  Desired value
 * @param measured  Current measured value
 * @param dt_s      Time since last call in seconds
 * @return Output value clamped to [output_min, output_max]
 */
float pid_compute(pid_controller_t *pid, float setpoint, float measured, float dt_s);

/* --- PID Auto-Tune (Ziegler-Nichols relay method) --- */

typedef enum {
    AUTOTUNE_IDLE,
    AUTOTUNE_HEATING_TO_SETPOINT,
    AUTOTUNE_RELAY_CYCLING,
    AUTOTUNE_COMPLETE,
    AUTOTUNE_FAILED,
} autotune_state_t;

typedef struct {
    autotune_state_t state;
    float setpoint;        /* Target temp for oscillation */
    float hysteresis;      /* Relay band (default 5°C) */
    uint8_t cycles_needed; /* Min oscillation cycles (default 5) */
    uint8_t cycles_done;
    float kp_result;
    float ki_result;
    float kd_result;
    /* Internal tracking */
    bool relay_on;            /* Current relay state */
    float peak_high;          /* Max temp during current half-cycle */
    float peak_low;           /* Min temp during current half-cycle */
    float amplitude_sum;      /* Sum of amplitudes for averaging */
    float period_sum_s;       /* Sum of periods for averaging */
    int64_t last_crossing_us; /* Timestamp of last setpoint crossing */
    int64_t start_time_us;    /* When auto-tune started */
    int64_t timeout_us;       /* Max duration before failing */
    bool above_setpoint;      /* Was above setpoint on last sample */
    uint8_t half_cycles;      /* Count of half-cycles for period measurement */
} pid_autotune_t;

/**
 * Start auto-tune. Sets state to AUTOTUNE_HEATING_TO_SETPOINT.
 */
esp_err_t pid_autotune_start(pid_autotune_t *at, float setpoint, float hysteresis);

/**
 * Call once per control loop iteration (1 Hz).
 *
 * @param at           Auto-tune state
 * @param current_temp Current thermocouple reading
 * @param output       Receives relay output: 0.0 (off) or 1.0 (on)
 * @return true when tuning is complete or failed
 */
bool pid_autotune_update(pid_autotune_t *at, float current_temp, float *output);

/**
 * Check if auto-tune completed successfully.
 */
bool pid_autotune_is_complete(const pid_autotune_t *at);

/**
 * Cancel a running auto-tune.
 */
void pid_autotune_cancel(pid_autotune_t *at);

/**
 * Shift every absolute timestamp held by a running auto-tune forward by
 * `delta_us`, so that time the run spent suspended is not charged against it.
 *
 * Auto-tune measures its overall timeout and each relay half-cycle period
 * against `esp_timer_get_time()`. Without this, a paused run either trips the
 * timeout the moment it resumes or folds the pause into an oscillation period
 * and derives PID gains from it. Call on resume with the paused duration.
 */
void pid_autotune_shift_time(pid_autotune_t *at, int64_t delta_us);

/* --- Manual gain entry --- */

/**
 * Bounds a manually entered gain has to satisfy.
 *
 * These are typo and overflow guards, not a stability criterion: no fixed range
 * can tell a workable gain for one kiln from a useless one for another, and the
 * users this exists for arrive with gains derived on their own hardware. The
 * ceiling is what keeps the NVS encoding honest — pid_save_gains() stores each
 * gain as `(int32_t)(gain * 10000)`, which overflows above ~214748 and would
 * read back as a wildly different (possibly negative) number.
 */
#define PID_GAIN_MIN 0.0f
#define PID_GAIN_MAX 10000.0f

/**
 * True when (kp, ki, kd) is a gain set the controller will accept.
 *
 * Rejects non-finite values, anything outside [PID_GAIN_MIN, PID_GAIN_MAX], and
 * the set with both kp and ki zero: the output would then depend only on the
 * rate of change of the measurement, so the loop can never hold a setpoint and
 * the kiln simply never heats — a failure that presents as broken hardware
 * rather than as a bad number someone typed.
 */
bool pid_gains_valid(float kp, float ki, float kd);

/**
 * The compile-time default gains — what pid_load_gains() falls back to when NVS
 * holds nothing, and what a "restore defaults" affordance should offer.
 */
void pid_default_gains(float *kp, float *ki, float *kd);

/**
 * Round a gain to the resolution NVS can hold (1e-4; see pid_save_gains).
 *
 * Apply this before handing a gain to pid_init() so the running controller and
 * the value the next boot loads are the same number — otherwise a gain entered
 * with more digits than the encoding carries changes, very slightly, at reboot.
 *
 * Only defined for gains already inside [PID_GAIN_MIN, PID_GAIN_MAX]: the
 * int32 conversion is undefined on a non-finite or far out-of-range value, so
 * screen with pid_gains_valid() first. Rounding can zero a gain small enough,
 * which is why the result is worth re-checking.
 */
float pid_quantize_gain(float gain);

/* --- NVS Persistence --- */

/**
 * Save PID gains to NVS under namespace "pid".
 */
esp_err_t pid_save_gains(float kp, float ki, float kd);

/**
 * Load PID gains from NVS. Returns defaults if not found.
 */
esp_err_t pid_load_gains(float *kp, float *ki, float *kd);

#ifdef __cplusplus
}
#endif
