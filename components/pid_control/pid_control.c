#include "pid_control.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "nvs.h"
#include <math.h>
#include <string.h>

static const char *TAG = "pid_control";

/* Default gains (used when NVS has no stored values) */
#define DEFAULT_KP 2.0f
#define DEFAULT_KI 0.01f
#define DEFAULT_KD 50.0f

#define NVS_NAMESPACE "pid"
#define AUTOTUNE_TIMEOUT_US (60LL * 60 * 1000000)  /* 60 minutes */

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ── PID Controller ────────────────────────────────────────── */

void pid_init(pid_controller_t *pid, float kp, float ki, float kd,
              float output_min, float output_max)
{
    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;
    pid->output_min = output_min;
    pid->output_max = output_max;
    pid->integral = 0.0f;
    pid->prev_error = 0.0f;
    pid->first_run = true;
}

void pid_reset(pid_controller_t *pid)
{
    pid->integral = 0.0f;
    pid->prev_error = 0.0f;
    pid->first_run = true;
}

float pid_compute(pid_controller_t *pid, float setpoint, float measured, float dt_s)
{
    if (dt_s <= 0.0f) {
        return pid->output_min;
    }

    float error = setpoint - measured;

    /* Proportional */
    float p_term = pid->kp * error;

    /* Integral with anti-windup clamping */
    pid->integral += error * dt_s;
    float i_term = pid->ki * pid->integral;

    /* Derivative (on error; skip first iteration) */
    float d_term = 0.0f;
    if (!pid->first_run) {
        d_term = pid->kd * (error - pid->prev_error) / dt_s;
    }
    pid->first_run = false;
    pid->prev_error = error;

    float output = p_term + i_term + d_term;

    /* Clamp output */
    if (output > pid->output_max) {
        output = pid->output_max;
        /* Anti-windup: prevent integral from growing further */
        if (error > 0) pid->integral -= error * dt_s;
    } else if (output < pid->output_min) {
        output = pid->output_min;
        if (error < 0) pid->integral -= error * dt_s;
    }

    return output;
}

/* ── Auto-Tune ─────────────────────────────────────────────── */

esp_err_t pid_autotune_start(pid_autotune_t *at, float setpoint, float hysteresis)
{
    if (setpoint <= 0.0f || hysteresis <= 0.0f) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(at, 0, sizeof(*at));
    at->state = AUTOTUNE_HEATING_TO_SETPOINT;
    at->setpoint = setpoint;
    at->hysteresis = hysteresis;
    at->cycles_needed = 5;
    at->cycles_done = 0;
    at->relay_on = true;
    at->peak_high = -1000.0f;
    at->peak_low = 10000.0f;
    at->amplitude_sum = 0.0f;
    at->period_sum_s = 0.0f;
    at->last_crossing_us = 0;
    at->start_time_us = esp_timer_get_time();
    at->timeout_us = AUTOTUNE_TIMEOUT_US;
    at->above_setpoint = false;
    at->half_cycles = 0;

    ESP_LOGI(TAG, "Auto-tune started: setpoint=%.1f, hysteresis=%.1f", setpoint, hysteresis);
    return ESP_OK;
}

bool pid_autotune_update(pid_autotune_t *at, float current_temp, float *output)
{
    if (at->state == AUTOTUNE_COMPLETE || at->state == AUTOTUNE_FAILED ||
        at->state == AUTOTUNE_IDLE) {
        *output = 0.0f;
        return true;
    }

    int64_t now = esp_timer_get_time();

    /* Timeout check */
    if ((now - at->start_time_us) > at->timeout_us) {
        ESP_LOGW(TAG, "Auto-tune timed out");
        at->state = AUTOTUNE_FAILED;
        *output = 0.0f;
        return true;
    }

    switch (at->state) {
    case AUTOTUNE_HEATING_TO_SETPOINT:
        /* Heat to near setpoint before starting relay cycling */
        *output = 1.0f;
        if (current_temp >= at->setpoint - at->hysteresis) {
            at->state = AUTOTUNE_RELAY_CYCLING;
            at->relay_on = false;  /* Start by turning off at setpoint */
            at->above_setpoint = true;
            at->last_crossing_us = now;
            at->peak_high = current_temp;
            at->peak_low = current_temp;
            ESP_LOGI(TAG, "Reached setpoint, starting relay cycling");
        }
        return false;

    case AUTOTUNE_RELAY_CYCLING: {
        /* Track peaks */
        if (current_temp > at->peak_high) at->peak_high = current_temp;
        if (current_temp < at->peak_low)  at->peak_low = current_temp;

        bool now_above = current_temp > at->setpoint;

        /* Detect setpoint crossing */
        if (now_above != at->above_setpoint) {
            at->half_cycles++;
            at->above_setpoint = now_above;

            /* Every two half-cycles = one full cycle */
            if (at->half_cycles >= 2) {
                int64_t period_us = now - at->last_crossing_us;
                float period_s = (float)period_us / 1000000.0f;
                float amplitude = (at->peak_high - at->peak_low) / 2.0f;

                at->period_sum_s += period_s;
                at->amplitude_sum += amplitude;
                at->cycles_done++;
                at->half_cycles = 0;
                at->last_crossing_us = now;

                /* Reset peaks for next cycle */
                at->peak_high = current_temp;
                at->peak_low = current_temp;

                ESP_LOGI(TAG, "Auto-tune cycle %d/%d: period=%.1fs, amplitude=%.1f°C",
                         at->cycles_done, at->cycles_needed, period_s, amplitude);

                if (at->cycles_done >= at->cycles_needed) {
                    /* Compute PID gains using Ziegler-Nichols */
                    float avg_period = at->period_sum_s / at->cycles_done;
                    float avg_amplitude = at->amplitude_sum / at->cycles_done;

                    if (avg_amplitude < 0.1f) {
                        ESP_LOGW(TAG, "Auto-tune failed: amplitude too small");
                        at->state = AUTOTUNE_FAILED;
                        *output = 0.0f;
                        return true;
                    }

                    /* Ku = 4d / (pi * a), where d = 1.0 (full relay amplitude) */
                    float ku = 4.0f / ((float)M_PI * avg_amplitude);
                    float pu = avg_period;

                    at->kp_result = 0.6f * ku;
                    at->ki_result = 1.2f * ku / pu;
                    at->kd_result = 0.075f * ku * pu;

                    at->state = AUTOTUNE_COMPLETE;
                    ESP_LOGI(TAG, "Auto-tune complete: Kp=%.4f, Ki=%.4f, Kd=%.4f",
                             at->kp_result, at->ki_result, at->kd_result);
                    *output = 0.0f;
                    return true;
                }
            }
        }

        /* Relay output: ON below (setpoint - hysteresis), OFF above (setpoint + hysteresis) */
        if (current_temp < at->setpoint - at->hysteresis) {
            at->relay_on = true;
        } else if (current_temp > at->setpoint + at->hysteresis) {
            at->relay_on = false;
        }
        *output = at->relay_on ? 1.0f : 0.0f;
        return false;
    }

    default:
        *output = 0.0f;
        return true;
    }
}

bool pid_autotune_is_complete(const pid_autotune_t *at)
{
    return at->state == AUTOTUNE_COMPLETE;
}

void pid_autotune_cancel(pid_autotune_t *at)
{
    at->state = AUTOTUNE_IDLE;
    ESP_LOGI(TAG, "Auto-tune cancelled");
}

/* ── NVS Persistence ───────────────────────────────────────── */

esp_err_t pid_save_gains(float kp, float ki, float kd)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    /* Store as integers (x10000 for precision) */
    int32_t kp_i = (int32_t)(kp * 10000.0f);
    int32_t ki_i = (int32_t)(ki * 10000.0f);
    int32_t kd_i = (int32_t)(kd * 10000.0f);

    nvs_set_i32(handle, "kp", kp_i);
    nvs_set_i32(handle, "ki", ki_i);
    nvs_set_i32(handle, "kd", kd_i);
    err = nvs_commit(handle);
    nvs_close(handle);

    ESP_LOGI(TAG, "PID gains saved: Kp=%.4f, Ki=%.4f, Kd=%.4f", kp, ki, kd);
    return err;
}

esp_err_t pid_load_gains(float *kp, float *ki, float *kd)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        *kp = DEFAULT_KP;
        *ki = DEFAULT_KI;
        *kd = DEFAULT_KD;
        return ESP_ERR_NVS_NOT_FOUND;
    }

    int32_t val;
    if (nvs_get_i32(handle, "kp", &val) == ESP_OK) *kp = val / 10000.0f;
    else *kp = DEFAULT_KP;

    if (nvs_get_i32(handle, "ki", &val) == ESP_OK) *ki = val / 10000.0f;
    else *ki = DEFAULT_KI;

    if (nvs_get_i32(handle, "kd", &val) == ESP_OK) *kd = val / 10000.0f;
    else *kd = DEFAULT_KD;

    nvs_close(handle);
    return ESP_OK;
}
