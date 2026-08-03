#include "pid_control.h"
#include "app_config.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "nvs.h"
#include <math.h>
#include <string.h>

static const char *TAG = "pid_control";

#define DEFAULT_KP APP_PID_KP_DEFAULT
#define DEFAULT_KI APP_PID_KI_DEFAULT
#define DEFAULT_KD APP_PID_KD_DEFAULT

/* Derivative low-pass filter time constant (seconds). At the 1 Hz control tick
 * this gives alpha = 1/(3+1) = 0.25, attenuating single-tick sensor-quantization
 * spikes to a quarter while preserving the multi-second ramp derivative. */
#define PID_D_FILTER_TAU_S 3.0f

#define NVS_NAMESPACE "pid"

/* PID gains live in NVS as int32 fixed-point at this scale. It bounds both the
   representable range (PID_GAIN_MAX keeps the product inside int32) and the
   resolution (see pid_quantize_gain). */
#define PID_GAIN_NVS_SCALE 10000.0f

#define AUTOTUNE_TIMEOUT_US (60LL * 60 * 1000000) /* 60 minutes */

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ── PID Controller ────────────────────────────────────────── */

void pid_init(pid_controller_t *pid, float kp, float ki, float kd, float output_min, float output_max)
{
    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;
    pid->output_min = output_min;
    pid->output_max = output_max;
    pid->integral = 0.0f;
    pid->prev_error = 0.0f;
    pid->prev_measured = 0.0f;
    pid->d_filtered = 0.0f;
    pid->first_run = true;
}

void pid_reset(pid_controller_t *pid)
{
    pid->integral = 0.0f;
    pid->prev_error = 0.0f;
    pid->prev_measured = 0.0f;
    pid->d_filtered = 0.0f;
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

    /* Derivative on measurement, low-pass filtered (skip first iteration).
       Taking the derivative of the measurement rather than the error avoids a
       kick when the setpoint steps (segment/skip transitions); the first-order
       filter attenuates the MAX31855's 0.25°C quantization noise, which with an
       unfiltered derivative and a large Kd swamped the P/I terms and drove the
       output bang-bang. alpha = dt / (tau + dt). */
    float d_term = 0.0f;
    if (!pid->first_run) {
        float d_meas = (measured - pid->prev_measured) / dt_s;
        float alpha = dt_s / (PID_D_FILTER_TAU_S + dt_s);
        pid->d_filtered += alpha * (d_meas - pid->d_filtered);
        d_term = -pid->kd * pid->d_filtered;
    }
    pid->first_run = false;
    pid->prev_error = error;
    pid->prev_measured = measured;

    float output = p_term + i_term + d_term;

    /* Clamp output */
    if (output > pid->output_max) {
        output = pid->output_max;
        /* Anti-windup: prevent integral from growing further */
        if (error > 0) {
            pid->integral -= error * dt_s;
        }
    } else if (output < pid->output_min) {
        output = pid->output_min;
        if (error < 0) {
            pid->integral -= error * dt_s;
        }
    }

    return output;
}

/* ── Auto-Tune ─────────────────────────────────────────────── */

esp_err_t pid_autotune_start(pid_autotune_t *at, float setpoint, float hysteresis)
{
    if (!isfinite(setpoint) || !isfinite(hysteresis) || setpoint <= 0.0f || hysteresis <= 0.0f) {
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
    if (at->state == AUTOTUNE_COMPLETE || at->state == AUTOTUNE_FAILED || at->state == AUTOTUNE_IDLE) {
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
            at->relay_on = false; /* Start by turning off at setpoint */
            at->above_setpoint = true;
            at->last_crossing_us = now;
            at->peak_high = current_temp;
            at->peak_low = current_temp;
            /* Restart the timeout budget for the cycling phase. Otherwise a long
               heat-up to a high setpoint eats into the same 60-minute window and
               the 5 relay cycles almost never finish in time. */
            at->start_time_us = now;
            ESP_LOGI(TAG, "Reached setpoint, starting relay cycling");
        }
        return false;

    case AUTOTUNE_RELAY_CYCLING: {
        /* Track peaks */
        if (current_temp > at->peak_high) {
            at->peak_high = current_temp;
        }
        if (current_temp < at->peak_low) {
            at->peak_low = current_temp;
        }

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

                ESP_LOGI(TAG, "Auto-tune cycle %d/%d: period=%.1fs, amplitude=%.1f°C", at->cycles_done,
                         at->cycles_needed, period_s, amplitude);

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

                    /* Ku = 4d / (pi * a), where d is the relay *half*-amplitude.
                       The relay swings between 0 and 1, so d = 0.5 and the
                       numerator is 4 * 0.5 = 2.0. (Using 4.0 here treated the
                       full 0..1 swing as the half-amplitude and doubled every
                       gain.) */
                    float ku = 2.0f / ((float)M_PI * avg_amplitude);
                    float pu = avg_period;

                    at->kp_result = 0.6f * ku;
                    at->ki_result = 1.2f * ku / pu;
                    at->kd_result = 0.075f * ku * pu;

                    at->state = AUTOTUNE_COMPLETE;
                    ESP_LOGI(TAG, "Auto-tune complete: Kp=%.4f, Ki=%.4f, Kd=%.4f", at->kp_result, at->ki_result,
                             at->kd_result);
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

void pid_autotune_shift_time(pid_autotune_t *at, int64_t delta_us)
{
    if (!at || delta_us <= 0 || at->state == AUTOTUNE_IDLE) {
        return;
    }
    at->start_time_us += delta_us;
    /* Zero means "no crossing recorded yet" — leave it alone so the first
       crossing after the resume still establishes the baseline. */
    if (at->last_crossing_us > 0) {
        at->last_crossing_us += delta_us;
    }
}

/* ── NVS Persistence ───────────────────────────────────────── */

bool pid_gains_valid(float kp, float ki, float kd)
{
    const float g[3] = {kp, ki, kd};
    for (int i = 0; i < 3; i++) {
        /* isfinite() first: NaN compares false against both bounds, so a range
           check alone would let it through. */
        if (!isfinite(g[i]) || g[i] < PID_GAIN_MIN || g[i] > PID_GAIN_MAX) {
            return false;
        }
    }
    /* A derivative-only controller drives the element from the rate of change of
       the measurement alone, so it has no term that grows with distance from the
       setpoint: the kiln stalls short of target instead of reporting anything. */
    return kp > 0.0f || ki > 0.0f;
}

void pid_default_gains(float *kp, float *ki, float *kd)
{
    *kp = DEFAULT_KP;
    *ki = DEFAULT_KI;
    *kd = DEFAULT_KD;
}

/* Encode one gain to its NVS fixed-point form.
 *
 * Round-to-nearest, not truncation, and both pid_quantize_gain() and
 * pid_save_gains() have to go through here or quantizing becomes lossy when
 * applied twice. Truncation is not idempotent across the float round trip: a Kp
 * of 0.00071 truncates to 0.0007, but the nearest float to 0.0007 is
 * 0.00069999..., so multiplying by 10000 again gives 6.9999 and truncates to
 * 0.0006 — a 14% shift between the gain a caller was told was stored and the one
 * the next boot loads. Rounding lands back on the same integer every time. */
static int32_t gain_to_fixed(float gain)
{
    return (int32_t)lroundf(gain * PID_GAIN_NVS_SCALE);
}

float pid_quantize_gain(float gain)
{
    return (float)gain_to_fixed(gain) / PID_GAIN_NVS_SCALE;
}

esp_err_t pid_save_gains(float kp, float ki, float kd)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }

    /* Store as integers (x10000 for precision).
     *
     * Every set is checked: a full or exhausted NVS partition fails the
     * individual write while nvs_commit() still reports ESP_OK, so ignoring
     * these returned success for a save that stored one gain, two, or none —
     * and the caller told the user the values would survive a reboot. */
    err = nvs_set_i32(handle, "kp", gain_to_fixed(kp));
    if (err == ESP_OK) {
        err = nvs_set_i32(handle, "ki", gain_to_fixed(ki));
    }
    if (err == ESP_OK) {
        err = nvs_set_i32(handle, "kd", gain_to_fixed(kd));
    }
    if (err != ESP_OK) {
        /* Commit anyway so the namespace is not left holding a partially
           written set from this call plus older values for the rest. Whatever
           it lands on, the caller is told the save failed. */
        nvs_commit(handle);
        nvs_close(handle);
        ESP_LOGE(TAG, "PID gains not saved: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_commit(handle);
    nvs_close(handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "PID gains not committed: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "PID gains saved: Kp=%.4f, Ki=%.4f, Kd=%.4f", kp, ki, kd);
    return ESP_OK;
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
    if (nvs_get_i32(handle, "kp", &val) == ESP_OK) {
        *kp = val / PID_GAIN_NVS_SCALE;
    } else {
        *kp = DEFAULT_KP;
    }

    if (nvs_get_i32(handle, "ki", &val) == ESP_OK) {
        *ki = val / PID_GAIN_NVS_SCALE;
    } else {
        *ki = DEFAULT_KI;
    }

    if (nvs_get_i32(handle, "kd", &val) == ESP_OK) {
        *kd = val / PID_GAIN_NVS_SCALE;
    } else {
        *kd = DEFAULT_KD;
    }

    nvs_close(handle);
    return ESP_OK;
}
