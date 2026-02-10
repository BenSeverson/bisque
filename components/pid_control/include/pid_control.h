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
    float prev_error;
    bool  first_run;
} pid_controller_t;

/**
 * Initialize a PID controller with the given gains and output limits.
 */
void pid_init(pid_controller_t *pid, float kp, float ki, float kd,
              float output_min, float output_max);

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
    float            setpoint;        /* Target temp for oscillation */
    float            hysteresis;      /* Relay band (default 5°C) */
    uint8_t          cycles_needed;   /* Min oscillation cycles (default 5) */
    uint8_t          cycles_done;
    float            kp_result;
    float            ki_result;
    float            kd_result;
    /* Internal tracking */
    bool             relay_on;        /* Current relay state */
    float            peak_high;       /* Max temp during current half-cycle */
    float            peak_low;        /* Min temp during current half-cycle */
    float            amplitude_sum;   /* Sum of amplitudes for averaging */
    float            period_sum_s;    /* Sum of periods for averaging */
    int64_t          last_crossing_us;/* Timestamp of last setpoint crossing */
    int64_t          start_time_us;   /* When auto-tune started */
    int64_t          timeout_us;      /* Max duration before failing */
    bool             above_setpoint;  /* Was above setpoint on last sample */
    uint8_t          half_cycles;     /* Count of half-cycles for period measurement */
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
