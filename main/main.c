#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "driver/spi_master.h"

#include "app_config.h"
#include "thermocouple.h"
#include "pid_control.h"
#include "firing_engine.h"
#include "safety.h"
#include "wifi_manager.h"
#include "web_server.h"
#include "display.h"

static const char *TAG = "main";

static void ws_broadcast_timer_cb(void *arg)
{
    (void)arg;
    ws_broadcast_status();
}

void app_main(void)
{
    ESP_LOGI(TAG, "=== Bisque v%s ===", APP_FIRMWARE_VERSION);

    /* ── NVS Init ──────────────────────────────────── */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /* ── SPI Bus Init (shared by thermocouple + display) ── */
    spi_bus_config_t spi_bus_cfg = {
        .mosi_io_num = APP_PIN_SPI_MOSI,
        .miso_io_num = APP_PIN_SPI_MISO,
        .sclk_io_num = APP_PIN_SPI_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 4096,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(APP_SPI_HOST, &spi_bus_cfg, SPI_DMA_CH_AUTO));
    ESP_LOGI(TAG, "SPI bus initialized");

    /* ── Thermocouple Init ─────────────────────────── */
    ESP_ERROR_CHECK(thermocouple_init(APP_SPI_HOST, APP_PIN_TC_CS));

    /* ── Safety Init ───────────────────────────────── */
    ESP_ERROR_CHECK(safety_init(APP_PIN_SSR, APP_DEFAULT_MAX_SAFE_TEMP));

    /* ── Firing Engine Init ────────────────────────── */
    ESP_ERROR_CHECK(firing_engine_init());

    /* Update safety max temp from loaded settings */
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);
    safety_set_max_temp(settings.max_safe_temp);

    /* ── Display Init ──────────────────────────────── */
    ret = display_init(APP_SPI_HOST, APP_PIN_LCD_CS, APP_PIN_LCD_DC,
                       APP_PIN_LCD_RST, APP_PIN_LCD_BL);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Display init failed (non-fatal): %s", esp_err_to_name(ret));
    }

    /* ── Wi-Fi Init ────────────────────────────────── */
#ifdef CONFIG_KILN_WIFI_STA_SSID
    const char *sta_ssid = CONFIG_KILN_WIFI_STA_SSID;
    const char *sta_pass = CONFIG_KILN_WIFI_STA_PASS;
#else
    const char *sta_ssid = "";
    const char *sta_pass = "";
#endif
    ESP_ERROR_CHECK(wifi_manager_init(sta_ssid, sta_pass,
                                       APP_WIFI_AP_SSID, APP_WIFI_AP_PASS));

    /* Wait for Wi-Fi (30s timeout) */
    if (wifi_manager_wait_connected(30000) == ESP_OK) {
        ESP_LOGI(TAG, "Wi-Fi ready: %s (AP mode: %s)",
                 wifi_manager_get_ip(),
                 wifi_manager_is_ap_mode() ? "yes" : "no");
    } else {
        ESP_LOGW(TAG, "Wi-Fi connection timed out");
    }

    /* ── Web Server Init ───────────────────────────── */
    ESP_ERROR_CHECK(web_server_start());
    ESP_LOGI(TAG, "Web server started at http://%s/", wifi_manager_get_ip());

    /* ── Create FreeRTOS Tasks ─────────────────────── */

    /* Core 1: Real-time control tasks */
    xTaskCreatePinnedToCore(safety_task, "safety", APP_TASK_SAFETY_STACK,
                            NULL, APP_TASK_SAFETY_PRIO, NULL, 1);

    xTaskCreatePinnedToCore(temp_read_task, "temp_read", APP_TASK_TEMP_READ_STACK,
                            NULL, APP_TASK_TEMP_READ_PRIO, NULL, 1);

    xTaskCreatePinnedToCore(firing_task, "firing", APP_TASK_FIRING_STACK,
                            NULL, APP_TASK_FIRING_PRIO, NULL, 1);

    /* Core 0: UI + network tasks */
    xTaskCreatePinnedToCore(display_task, "display", APP_TASK_DISPLAY_STACK,
                            NULL, APP_TASK_DISPLAY_PRIO, NULL, 0);

    /* ── WebSocket broadcast timer ─────────────────── */
    const esp_timer_create_args_t ws_timer_args = {
        .callback = ws_broadcast_timer_cb,
        .name = "ws_broadcast",
    };
    esp_timer_handle_t ws_timer;
    ESP_ERROR_CHECK(esp_timer_create(&ws_timer_args, &ws_timer));
    /* 1s interval during firing, but we use 1s always and let the client manage */
    ESP_ERROR_CHECK(esp_timer_start_periodic(ws_timer, 1000000));  /* 1 second */

    ESP_LOGI(TAG, "=== Bisque started successfully ===");
    ESP_LOGI(TAG, "Free heap: %lu bytes", (unsigned long)esp_get_free_heap_size());
}
