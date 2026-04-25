#include "status_led.h"
#include "app_config.h"
#include "wifi_manager.h"
#include "safety.h"
#include "firing_engine.h"
#include "led_strip.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

static const char *TAG = "status_led";

static led_strip_handle_t s_strip;

/* Dim brightness for debug indicator (0-255) */
#define LED_BRIGHTNESS 30

esp_err_t status_led_init(void)
{
    led_strip_config_t strip_cfg = {
        .strip_gpio_num = APP_PIN_STATUS_LED,
        .max_leds = 1,
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
        .flags.invert_out = false,
    };

    led_strip_rmt_config_t rmt_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000, /* 10 MHz */
        .flags.with_dma = false,
    };

    esp_err_t err = led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_strip);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to init LED strip: %s", esp_err_to_name(err));
        return err;
    }

    led_strip_clear(s_strip);
    ESP_LOGI(TAG, "Status LED initialized on GPIO %d", APP_PIN_STATUS_LED);
    return ESP_OK;
}

static void set_color(uint8_t r, uint8_t g, uint8_t b)
{
    led_strip_set_pixel(s_strip, 0, r, g, b);
    led_strip_refresh(s_strip);
}

static void set_off(void)
{
    led_strip_clear(s_strip);
}

void status_led_task(void *param)
{
    (void)param;
    uint32_t tick = 0;

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(250));
        tick++;

        bool blink_1hz = (tick % 4) < 2;  /* on 500ms, off 500ms */
        bool blink_2hz = (tick % 2) == 0; /* on 250ms, off 250ms */

        /* Priority 1: Safety emergency */
        if (safety_is_emergency()) {
            set_color(LED_BRIGHTNESS, 0, 0);
            continue;
        }

        /* Priority 2: Thermocouple fault */
        EventBits_t safety_bits = xEventGroupGetBits(safety_get_event_group());
        if (safety_bits & SAFETY_BIT_TEMP_FAULT) {
            if (blink_1hz)
                set_color(LED_BRIGHTNESS, 0, 0);
            else
                set_off();
            continue;
        }

        /* Priority 3: Firing error */
        firing_progress_t progress;
        firing_engine_get_progress(&progress);
        if (progress.status == FIRING_STATUS_ERROR) {
            if (blink_2hz)
                set_color(LED_BRIGHTNESS, 0, 0);
            else
                set_off();
            continue;
        }

        /* Priority 4: WiFi disconnected (not AP, not connected) */
        if (!wifi_manager_is_connected() && !wifi_manager_is_ap_mode()) {
            set_color(LED_BRIGHTNESS, LED_BRIGHTNESS / 2, 0);
            continue;
        }

        /* Priority 5: WiFi AP mode */
        if (wifi_manager_is_ap_mode()) {
            if (blink_1hz)
                set_color(LED_BRIGHTNESS, LED_BRIGHTNESS / 2, 0);
            else
                set_off();
            continue;
        }

        /* Priority 6: Firing active */
        if (progress.is_active) {
            set_color(0, 0, LED_BRIGHTNESS);
            continue;
        }

        /* Priority 7: All healthy */
        set_color(0, LED_BRIGHTNESS, 0);
    }
}
