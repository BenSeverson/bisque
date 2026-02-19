#include "safety.h"
#include "thermocouple.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include <math.h>

static const char *TAG = "safety";

/* Hardware absolute maximum — cannot be overridden */
#define HARDWARE_MAX_TEMP_C 1400.0f

/* No valid reading for this long → emergency stop */
#define TEMP_FAULT_TIMEOUT_US (5 * 1000 * 1000LL)

/* Vent active below this temperature during firing */
#define VENT_MAX_TEMP_C 700.0f

static int s_ssr_pin   = -1;
static int s_alarm_gpio = -1;
static int s_vent_gpio  = -1;
static float s_max_safe_temp = 1300.0f;
static EventGroupHandle_t s_event_group;
static portMUX_TYPE s_safety_mux = portMUX_INITIALIZER_UNLOCKED;

/* Time-proportional SSR state */
static float s_ssr_duty = 0.0f;
static int64_t s_ssr_window_start_us = 0;
#define SSR_WINDOW_US (2000 * 1000LL)  /* 2 second window */

void safety_init_io(int alarm_gpio, int vent_gpio)
{
    s_alarm_gpio = alarm_gpio;
    s_vent_gpio  = vent_gpio;

    if (alarm_gpio >= 0) {
        gpio_config_t io = {
            .pin_bit_mask = (1ULL << alarm_gpio),
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_ENABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&io);
        gpio_set_level(alarm_gpio, 0);
        ESP_LOGI(TAG, "Alarm GPIO %d configured", alarm_gpio);
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
    if (s_alarm_gpio < 0) return;

    /* Simple patterns: drive GPIO high for a duration */
    switch (pattern) {
    case 0: /* short beep */
        gpio_set_level(s_alarm_gpio, 1);
        vTaskDelay(pdMS_TO_TICKS(200));
        gpio_set_level(s_alarm_gpio, 0);
        break;
    case 1: /* long beep (completion) */
        for (int i = 0; i < 3; i++) {
            gpio_set_level(s_alarm_gpio, 1);
            vTaskDelay(pdMS_TO_TICKS(500));
            gpio_set_level(s_alarm_gpio, 0);
            vTaskDelay(pdMS_TO_TICKS(200));
        }
        break;
    case 2: /* error pattern */
        for (int i = 0; i < 5; i++) {
            gpio_set_level(s_alarm_gpio, 1);
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(s_alarm_gpio, 0);
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        break;
    default:
        gpio_set_level(s_alarm_gpio, 1);
        vTaskDelay(pdMS_TO_TICKS(300));
        gpio_set_level(s_alarm_gpio, 0);
        break;
    }
}

void safety_update_vent(bool is_firing, float current_temp_c)
{
    if (s_vent_gpio < 0) return;
    /* Vent relay on during firing at temperatures below 700°C */
    int level = (is_firing && current_temp_c < VENT_MAX_TEMP_C) ? 1 : 0;
    gpio_set_level(s_vent_gpio, level);
}

esp_err_t safety_init(int ssr_pin, float max_safe_temp)
{
    s_ssr_pin = ssr_pin;
    s_max_safe_temp = (max_safe_temp < HARDWARE_MAX_TEMP_C) ? max_safe_temp : HARDWARE_MAX_TEMP_C;

    /* Configure SSR GPIO as output, start LOW (off) */
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << ssr_pin),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t ret = gpio_config(&io_conf);
    if (ret != ESP_OK) return ret;

    gpio_set_level(ssr_pin, 0);

    s_event_group = xEventGroupCreate();
    if (!s_event_group) return ESP_ERR_NO_MEM;

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
    s_max_safe_temp = (max_safe_temp < HARDWARE_MAX_TEMP_C) ? max_safe_temp : HARDWARE_MAX_TEMP_C;
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

void safety_set_ssr(float duty)
{
    if (safety_is_emergency()) {
        gpio_set_level(s_ssr_pin, 0);
        return;
    }

    if (duty < 0.0f) duty = 0.0f;
    if (duty > 1.0f) duty = 1.0f;

    portENTER_CRITICAL(&s_safety_mux);
    s_ssr_duty = duty;
    portEXIT_CRITICAL(&s_safety_mux);

    /* Time-proportional output: within a 2-second window, SSR is on for (duty * window) */
    int64_t now = esp_timer_get_time();
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

            /* Over-temperature check */
            float max_temp;
            portENTER_CRITICAL(&s_safety_mux);
            max_temp = s_max_safe_temp;
            portEXIT_CRITICAL(&s_safety_mux);

            if (reading.temperature_c > max_temp || reading.temperature_c > HARDWARE_MAX_TEMP_C) {
                ESP_LOGE(TAG, "Over-temp: %.1f°C exceeds limit %.1f°C",
                         reading.temperature_c, max_temp);
                safety_emergency_stop();
            }
        }

        /* Check for stale reading (no new data for >5 seconds) */
        if (reading.timestamp_us > 0 && (now - reading.timestamp_us) > TEMP_FAULT_TIMEOUT_US) {
            ESP_LOGE(TAG, "No thermocouple data for >5s, emergency stop");
            xEventGroupSetBits(s_event_group, SAFETY_BIT_TEMP_FAULT);
            safety_emergency_stop();
        }

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(500));
    }
}
