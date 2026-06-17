#include "safety.h"
#include "thermocouple.h"
#include "app_config.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include <math.h>

static const char *TAG = "safety";

#define TEMP_FAULT_TIMEOUT_US ((int64_t)APP_TEMP_FAULT_TIMEOUT_MS * 1000LL)

/* Vent active below this temperature during firing */
#define VENT_MAX_TEMP_C 700.0f

/* Piezo buzzer tone driven via LEDC. The buzzer needs an AC waveform to
   produce sound; static GPIO levels won't work. 4 kHz matched the resonance
   peak of the buzzer used during bench testing — adjust if a different
   buzzer is fitted. */
#define ALARM_TONE_FREQ_HZ    4000
#define ALARM_TONE_DUTY_RES   LEDC_TIMER_10_BIT
#define ALARM_TONE_DUTY_50PCT (1U << (ALARM_TONE_DUTY_RES - 1))
#define ALARM_LEDC_TIMER      LEDC_TIMER_0
#define ALARM_LEDC_CHANNEL    LEDC_CHANNEL_0
#define ALARM_LEDC_MODE       LEDC_LOW_SPEED_MODE

static int s_ssr_pin = -1;
static int s_alarm_gpio = -1;
static int s_vent_gpio = -1;
static float s_max_safe_temp = 1300.0f;
static float s_tc_offset_c = 0.0f;
static EventGroupHandle_t s_event_group;
static portMUX_TYPE s_safety_mux = portMUX_INITIALIZER_UNLOCKED;

/* Time-proportional SSR state */
static float s_ssr_duty = 0.0f;
static int64_t s_ssr_window_start_us = 0;
#define SSR_WINDOW_US ((int64_t)APP_SSR_WINDOW_MS * 1000LL)

/* Control-loop heartbeat: safety_set_ssr() is called every firing tick (1 Hz).
 * If it goes silent while the element is commanded on, the firing task has
 * wedged with the SSR latched — safety_task forces the output off (and trips an
 * emergency stop). 3 s ≈ three missed control ticks. */
static int64_t s_last_ssr_cmd_us = 0;
#define SSR_HEARTBEAT_TIMEOUT_US (3LL * 1000000)

static void alarm_tone_on(void)
{
    ledc_set_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL, ALARM_TONE_DUTY_50PCT);
    ledc_update_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL);
}

static void alarm_tone_off(void)
{
    ledc_set_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL, 0);
    ledc_update_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL);
}

void safety_init_io(int alarm_gpio, int vent_gpio)
{
    s_alarm_gpio = alarm_gpio;
    s_vent_gpio = vent_gpio;

    if (alarm_gpio >= 0) {
        const ledc_timer_config_t timer = {
            .speed_mode = ALARM_LEDC_MODE,
            .timer_num = ALARM_LEDC_TIMER,
            .duty_resolution = ALARM_TONE_DUTY_RES,
            .freq_hz = ALARM_TONE_FREQ_HZ,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        const ledc_channel_config_t channel = {
            .speed_mode = ALARM_LEDC_MODE,
            .channel = ALARM_LEDC_CHANNEL,
            .timer_sel = ALARM_LEDC_TIMER,
            .intr_type = LEDC_INTR_DISABLE,
            .gpio_num = alarm_gpio,
            .duty = 0,
            .hpoint = 0,
        };
        ESP_ERROR_CHECK(ledc_timer_config(&timer));
        ESP_ERROR_CHECK(ledc_channel_config(&channel));
        ESP_LOGI(TAG, "Alarm GPIO %d configured (LEDC %d Hz tone)", alarm_gpio, ALARM_TONE_FREQ_HZ);
    }

    if (vent_gpio >= 0) {
        gpio_config_t io = {
            .pin_bit_mask = (1ULL << vent_gpio),
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_ENABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&io);
        gpio_set_level(vent_gpio, 0);
        ESP_LOGI(TAG, "Vent GPIO %d configured", vent_gpio);
    }
}

void safety_trigger_alarm(int pattern)
{
    if (s_alarm_gpio < 0) {
        return;
    }

    switch (pattern) {
    case 0: /* short beep */
        alarm_tone_on();
        vTaskDelay(pdMS_TO_TICKS(200));
        alarm_tone_off();
        break;
    case 1: /* long beep (completion) */
        for (int i = 0; i < 3; i++) {
            alarm_tone_on();
            vTaskDelay(pdMS_TO_TICKS(500));
            alarm_tone_off();
            vTaskDelay(pdMS_TO_TICKS(200));
        }
        break;
    case 2: /* error pattern */
        for (int i = 0; i < 5; i++) {
            alarm_tone_on();
            vTaskDelay(pdMS_TO_TICKS(100));
            alarm_tone_off();
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        break;
    default:
        alarm_tone_on();
        vTaskDelay(pdMS_TO_TICKS(300));
        alarm_tone_off();
        break;
    }
}

void safety_update_vent(bool is_firing, float current_temp_c)
{
    if (s_vent_gpio < 0) {
        return;
    }
    /* Vent relay on during firing at temperatures below 700°C */
    int level = (is_firing && current_temp_c < VENT_MAX_TEMP_C) ? 1 : 0;
    gpio_set_level(s_vent_gpio, level);
}

esp_err_t safety_init(int ssr_pin, float max_safe_temp)
{
    s_ssr_pin = ssr_pin;
    s_max_safe_temp = (max_safe_temp < APP_HARDWARE_MAX_TEMP_C) ? max_safe_temp : APP_HARDWARE_MAX_TEMP_C;

    /* Configure SSR GPIO as output, start LOW (off) */
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << ssr_pin),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t ret = gpio_config(&io_conf);
    if (ret != ESP_OK) {
        return ret;
    }

    gpio_set_level(ssr_pin, 0);

    s_event_group = xEventGroupCreate();
    if (!s_event_group) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Safety initialized: SSR pin=%d, max_safe_temp=%.0f°C", ssr_pin, s_max_safe_temp);
    return ESP_OK;
}

EventGroupHandle_t safety_get_event_group(void)
{
    return s_event_group;
}

void safety_emergency_stop(void)
{
    if (s_ssr_pin >= 0) {
        gpio_set_level(s_ssr_pin, 0);
    }
    /* Turn off vent on emergency stop */
    if (s_vent_gpio >= 0) {
        gpio_set_level(s_vent_gpio, 0);
    }
    portENTER_CRITICAL(&s_safety_mux);
    s_ssr_duty = 0.0f;
    portEXIT_CRITICAL(&s_safety_mux);

    xEventGroupSetBits(s_event_group, SAFETY_BIT_EMERGENCY_STOP);
    ESP_LOGE(TAG, "EMERGENCY STOP activated");
}

void safety_clear_emergency(void)
{
    xEventGroupClearBits(s_event_group, SAFETY_BIT_EMERGENCY_STOP);
    ESP_LOGI(TAG, "Emergency stop cleared");
}

bool safety_is_emergency(void)
{
    EventBits_t bits = xEventGroupGetBits(s_event_group);
    return (bits & SAFETY_BIT_EMERGENCY_STOP) != 0;
}

void safety_set_max_temp(float max_safe_temp)
{
    portENTER_CRITICAL(&s_safety_mux);
    s_max_safe_temp = (max_safe_temp < APP_HARDWARE_MAX_TEMP_C) ? max_safe_temp : APP_HARDWARE_MAX_TEMP_C;
    portEXIT_CRITICAL(&s_safety_mux);
}

float safety_get_max_temp(void)
{
    float val;
    portENTER_CRITICAL(&s_safety_mux);
    val = s_max_safe_temp;
    portEXIT_CRITICAL(&s_safety_mux);
    return val;
}

void safety_set_tc_offset(float offset_c)
{
    portENTER_CRITICAL(&s_safety_mux);
    s_tc_offset_c = offset_c;
    portEXIT_CRITICAL(&s_safety_mux);
}

void safety_set_ssr(float duty)
{
    if (safety_is_emergency()) {
        gpio_set_level(s_ssr_pin, 0);
        return;
    }

    if (duty < 0.0f) {
        duty = 0.0f;
    }
    if (duty > 1.0f) {
        duty = 1.0f;
    }

    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&s_safety_mux);
    s_ssr_duty = duty;
    s_last_ssr_cmd_us = now; /* feed the control-loop heartbeat */
    portEXIT_CRITICAL(&s_safety_mux);

    /* Time-proportional output: within a 2-second window, SSR is on for (duty * window) */
    int64_t elapsed = now - s_ssr_window_start_us;
    if (elapsed >= SSR_WINDOW_US) {
        s_ssr_window_start_us = now;
        elapsed = 0;
    }

    int64_t on_time = (int64_t)(duty * SSR_WINDOW_US);
    gpio_set_level(s_ssr_pin, (elapsed < on_time) ? 1 : 0);
}

void safety_task(void *param)
{
    (void)param;
    TickType_t last_wake = xTaskGetTickCount();
    int64_t last_valid_reading_us = esp_timer_get_time();

    ESP_LOGI(TAG, "safety_task started");

    for (;;) {
        thermocouple_reading_t reading;
        thermocouple_get_latest(&reading);

        int64_t now = esp_timer_get_time();

        if (reading.fault != 0) {
            /* Thermocouple fault detected */
            if ((now - last_valid_reading_us) > TEMP_FAULT_TIMEOUT_US) {
                ESP_LOGE(TAG, "Thermocouple fault persisted >5s, emergency stop");
                xEventGroupSetBits(s_event_group, SAFETY_BIT_TEMP_FAULT);
                safety_emergency_stop();
            }
        } else {
            last_valid_reading_us = reading.timestamp_us;
            xEventGroupClearBits(s_event_group, SAFETY_BIT_TEMP_FAULT);

            /* Over-temperature check. Compare the calibration-corrected
             * temperature against the user limit — the control loop acts on the
             * corrected value, so safety must too or a nonzero offset lets the
             * kiln run hotter than max_safe_temp before tripping. The absolute
             * hardware ceiling stays on the raw reading as a backstop. */
            float max_temp, offset;
            portENTER_CRITICAL(&s_safety_mux);
            max_temp = s_max_safe_temp;
            offset = s_tc_offset_c;
            portEXIT_CRITICAL(&s_safety_mux);

            float corrected = reading.temperature_c + offset;
            if (corrected > max_temp || reading.temperature_c > APP_HARDWARE_MAX_TEMP_C) {
                ESP_LOGE(TAG, "Over-temp: %.1f°C (corrected %.1f°C) exceeds limit %.1f°C", reading.temperature_c,
                         corrected, max_temp);
                safety_emergency_stop();
            }
        }

        /* Check for stale reading (no new data for >5 seconds) */
        if (reading.timestamp_us > 0 && (now - reading.timestamp_us) > TEMP_FAULT_TIMEOUT_US) {
            ESP_LOGE(TAG, "No thermocouple data for >5s, emergency stop");
            xEventGroupSetBits(s_event_group, SAFETY_BIT_TEMP_FAULT);
            safety_emergency_stop();
        }

        /* Control-loop heartbeat. safety_set_ssr() runs every firing tick; if it
         * stops while the element is commanded on, the firing task has wedged
         * with the SSR latched. Force the output off and escalate. A stale
         * heartbeat with the last duty at 0 (idle/paused) is harmless, so only
         * trip the emergency stop when heat was actually being commanded. */
        float last_duty;
        int64_t last_cmd_us;
        portENTER_CRITICAL(&s_safety_mux);
        last_duty = s_ssr_duty;
        last_cmd_us = s_last_ssr_cmd_us;
        portEXIT_CRITICAL(&s_safety_mux);
        if (last_cmd_us != 0 && (now - last_cmd_us) > SSR_HEARTBEAT_TIMEOUT_US) {
            if (s_ssr_pin >= 0) {
                gpio_set_level(s_ssr_pin, 0);
            }
            if (last_duty > 0.0f && !safety_is_emergency()) {
                ESP_LOGE(TAG, "Control loop stalled (%lldms since last SSR command, duty=%.2f), emergency stop",
                         (long long)((now - last_cmd_us) / 1000), last_duty);
                safety_emergency_stop();
            }
        }

        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(500));
    }
}
