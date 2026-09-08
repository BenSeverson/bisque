#include <stdbool.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "nvs_flash.h"
#include "esp_app_desc.h"
#include "ota_manager.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "mdns.h"
#include "esp_sntp.h"

#include "app_config.h"
#include "thermocouple.h"
#include "firing_engine.h"
#include "safety.h"
#include "wifi_manager.h"
#include "web_server.h"
#include "display.h"
#include "boot_status.h"
#include "firing_history.h"
#include "status_led.h"
#include "device_log.h"

static const char *TAG = "main";

/* Create a Core 1 control task, turning FreeRTOS's silent errCOULD_NOT_ALLOCATE
   into an esp_err_t the caller can ESP_ERROR_CHECK. A control task that never
   starts is not a degraded mode: without safety_task there is no over-temp
   check, no SSR heartbeat, and no thermocouple-fault watchdog. Fail loudly. */
static esp_err_t start_control_task(TaskFunction_t fn, const char *name, uint32_t stack, UBaseType_t prio)
{
    if (xTaskCreatePinnedToCore(fn, name, stack, NULL, prio, NULL, 1) != pdPASS) {
        ESP_LOGE(TAG, "Failed to create %s task — out of internal RAM?", name);
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

static void ws_broadcast_timer_cb(void *arg)
{
    (void)arg;
    /* Wake the broadcast worker; never block here — esp_timer callbacks run on
       a single shared task and any blocking work would stall every other timer. */
    ws_broadcast_notify();
}

void app_main(void)
{
    /* Before the first line worth keeping: the log hook only sees what is
       logged after it is installed, so this goes ahead of the banner. A failure
       here is not fatal — it costs the diagnostics bundle its log section and
       nothing else. */
    if (device_log_init() != ESP_OK) {
        ESP_LOGW(TAG, "Device log unavailable — /api/v1/log will be empty");
    }

    /* version already carries a leading 'v' (git describe of v* tags). */
    ESP_LOGI(TAG, "=== Bisque %s ===", esp_app_get_description()->version);

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
        .max_transfer_sz = APP_LCD_H_RES * 40 * 2,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(APP_SPI_HOST, &spi_bus_cfg, SPI_DMA_CH_AUTO));
    ESP_LOGI(TAG, "SPI bus initialized");

    /* Park the chip selects of populated-but-undriven bus peers HIGH before any
     * traffic. Rev B multi-drops four devices on SPI2 — the LCD, both MAX31856s
     * and the XPT2046 touch controller — but only the LCD and TC1 have drivers,
     * which own their CS via spics_io_num. TC2's and touch's CS are left in
     * their reset state: no firmware writes them and neither net carries a
     * pull-up, so both sit floating at an active-low input. A float sampled low
     * puts that device on the bus for every transaction, and it drives MISO
     * alongside TC1 — so the failure is not "channel 2 misbehaves", it is TC1's
     * CR0 probe failing or its temperature reads returning contended data.
     *
     * The level is latched before the output driver is enabled so enabling it
     * cannot glitch the line low. Drop a pin from this list only when something
     * else has taken ownership of it (TC2 at RB-3, touch when a driver lands). */
    static const int idle_cs_pins[] = {APP_PIN_TC2_CS, APP_PIN_TOUCH_CS};
    for (size_t i = 0; i < sizeof(idle_cs_pins) / sizeof(idle_cs_pins[0]); i++) {
        int pin = idle_cs_pins[i];
        if (pin < 0) {
            continue; /* -1 = not fitted on this build */
        }
        gpio_set_level(pin, 1);
        gpio_config_t cs_cfg = {
            .pin_bit_mask = 1ULL << pin,
            .mode = GPIO_MODE_OUTPUT,
            /* Holds the line deasserted if the pin is ever floated again. */
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ESP_ERROR_CHECK(gpio_config(&cs_cfg));
        gpio_set_level(pin, 1);
        ESP_LOGI(TAG, "Parked idle SPI chip select on GPIO %d", pin);
    }

    /* ── Thermocouple Init ─────────────────────────── */
    ESP_ERROR_CHECK(thermocouple_init(APP_SPI_HOST, APP_PIN_TC1_CS));

    /* ── Safety Init ───────────────────────────────── */
    ESP_ERROR_CHECK(safety_init(APP_PIN_SSR1, APP_DEFAULT_MAX_SAFE_TEMP));
    safety_init_io(APP_PIN_ALARM, APP_PIN_VENT, APP_PIN_LID_SWITCH);
    safety_init_wdt(APP_PIN_WDT_KICK);

    /* ── Firing Engine Init ────────────────────────── */
    ESP_ERROR_CHECK(firing_engine_init());

    /* Update safety max temp from loaded settings */
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);
    safety_set_max_temp(settings.max_safe_temp);
    safety_set_tc_offset(settings.tc_offset_c);

    /* ── Storage for the firing history ────────────── */
    /* Mounted here rather than implicitly inside web_server_start() so
       history_init() — firing_task's only external dependency — is ready before
       the control tasks below. The mount is idempotent; web_server_start()
       still calls it and gets a no-op. */
    if (web_server_mount_spiffs() != ESP_OK) {
        ESP_LOGW(TAG, "SPIFFS mount failed; history and static files unavailable");
    }
    history_init();

    /* ── Create Real-Time Control Tasks (Core 1) ───── */
    /* These come before every optional or slow subsystem below — display, Wi-Fi,
       mDNS, NTP, web server. Safety supervision must never be gated on hardware
       that may be absent or on a network stack that can stall for 30 s (#250):
       safety_task is what runs the over-temp check, the SSR heartbeat, and the
       thermocouple-fault watchdog, and it is useless if it starts last.
       Keep it that way — nothing that can energize the SSR belongs above here. */
    ESP_ERROR_CHECK(start_control_task(safety_task, "safety", APP_TASK_SAFETY_STACK, APP_TASK_SAFETY_PRIO));
    ESP_ERROR_CHECK(start_control_task(temp_read_task, "temp_read", APP_TASK_TEMP_READ_STACK, APP_TASK_TEMP_READ_PRIO));
    ESP_ERROR_CHECK(start_control_task(firing_task, "firing", APP_TASK_FIRING_STACK, APP_TASK_FIRING_PRIO));

    /* ── Display Init ──────────────────────────────── */
    ret = display_init(APP_SPI_HOST, APP_PIN_LCD_CS, APP_PIN_LCD_DC, APP_PIN_LCD_RST, APP_PIN_LCD_BL);
    bool display_initialized = (ret == ESP_OK);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Display init failed (non-fatal): %s", esp_err_to_name(ret));
    }

    /* Bring up the display task immediately so the splash is on-screen during
     * the slow init steps below (Wi-Fi can take up to 30 s). The task gets a
     * hard error check because if internal SRAM is too tight to satisfy the
     * 16 KiB stack, FreeRTOS silently returns errCOULD_NOT_ALLOCATE and the UI
     * just never starts (with no diagnostic) — easier to crash loudly. */
    if (display_initialized) {
        BaseType_t disp_rc = xTaskCreatePinnedToCore(display_task, "display", APP_TASK_DISPLAY_STACK, NULL,
                                                     APP_TASK_DISPLAY_PRIO, NULL, 0);
        if (disp_rc != pdPASS) {
            ESP_LOGE(TAG, "Failed to create display_task (rc=%d) — out of internal RAM?", (int)disp_rc);
            abort();
        }
    } else {
        ESP_LOGW(TAG, "Display task skipped; controller will run headless");
    }

    /* ── Wi-Fi Init ────────────────────────────────── */
    /* Try NVS-saved credentials first, fall back to compile-time config */
    char nvs_ssid[WIFI_SSID_BUF_LEN] = {0};
    char nvs_pass[WIFI_PASS_BUF_LEN] = {0};
    const char *sta_ssid = "";
    const char *sta_pass = "";
    if (wifi_manager_load_creds(nvs_ssid, sizeof(nvs_ssid), nvs_pass, sizeof(nvs_pass)) == ESP_OK && nvs_ssid[0]) {
        sta_ssid = nvs_ssid;
        sta_pass = nvs_pass;
        ESP_LOGI(TAG, "Using Wi-Fi credentials from NVS");
    } else {
#ifdef CONFIG_KILN_WIFI_STA_SSID
        sta_ssid = CONFIG_KILN_WIFI_STA_SSID;
        sta_pass = CONFIG_KILN_WIFI_STA_PASS;
        ESP_LOGI(TAG, "Using compile-time Wi-Fi credentials");
        if (sta_ssid[0]) {
            /* Seed NVS so the credentials persist across firmware updates even
               if later removed from sdkconfig.local. */
            wifi_manager_save_creds(sta_ssid, sta_pass);
        }
#else
        ESP_LOGI(TAG, "No Wi-Fi credentials configured, starting in AP mode");
#endif
    }
    ESP_ERROR_CHECK(wifi_manager_init(sta_ssid, sta_pass, APP_WIFI_AP_SSID, APP_WIFI_AP_PASS));

    /* Wait for Wi-Fi (30s timeout) */
    boot_status_set("Connecting to Wi-Fi...");
    if (wifi_manager_wait_connected(30000) == ESP_OK) {
        ESP_LOGI(TAG, "Wi-Fi ready: %s (AP mode: %s)", wifi_manager_get_ip(), wifi_manager_is_ap_mode() ? "yes" : "no");
    } else {
        ESP_LOGW(TAG, "Wi-Fi connection timed out");
    }
    if (wifi_manager_is_ap_mode()) {
        boot_status_set("Wi-Fi: access point mode");
    }

    /* ── Status LED Init ────────────────────────────── */
    bool status_led_initialized = (status_led_init() == ESP_OK);
    if (!status_led_initialized) {
        ESP_LOGW(TAG, "Status LED init failed (non-fatal)");
    }

    /* ── mDNS ─────────────────────────────────────── */
    {
        esp_err_t mdns_err = mdns_init();
        if (mdns_err == ESP_OK) {
            mdns_hostname_set("bisque");
            mdns_instance_name_set("Bisque Kiln Controller");
            mdns_service_add(NULL, "_http", "_tcp", 80, NULL, 0);
            ESP_LOGI(TAG, "mDNS: http://bisque.local/");
        } else {
            ESP_LOGW(TAG, "mDNS init failed: %s", esp_err_to_name(mdns_err));
        }
    }

    /* ── NTP Time Sync ─────────────────────────────── */
    /* Start unconditionally: SNTP polls in the background and syncs whenever
       connectivity appears, so a STA that associates after the 30 s boot wait
       (or after a later AP→STA transition) still gets the clock set. In pure AP
       mode there's no route to pool.ntp.org and it simply keeps retrying
       harmlessly — cheap next to leaving firing-history timestamps at 1970. */
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, "pool.ntp.org");
    esp_sntp_init();
    ESP_LOGI(TAG, "NTP sync started");

    /* ── Web Server Init ───────────────────────────── */
    /* SPIFFS is already mounted (above, for history_init); this re-mount is a
       no-op and only serves as the fallback if that ordering ever changes. */
    ESP_ERROR_CHECK(web_server_start());
    ESP_LOGI(TAG, "Web server started at http://%s/", wifi_manager_get_ip());

    /* ── Create Remaining Tasks (Core 0: UI + network) ── */
    /* The Core 1 control tasks and display_task were created earlier — see the
     * ordering note above safety_task's creation. */

    if (status_led_initialized) {
        xTaskCreatePinnedToCore(status_led_task, "status_led", 2048, NULL, 1, NULL, 0);
    } else {
        ESP_LOGW(TAG, "Status LED task skipped");
    }

    /* ── Workers driven off firing engine + WS broadcast timer ── */
    ESP_ERROR_CHECK(ws_handler_start());
    ESP_ERROR_CHECK(notification_task_start());

    const esp_timer_create_args_t ws_timer_args = {
        .callback = ws_broadcast_timer_cb,
        .name = "ws_broadcast",
    };
    esp_timer_handle_t ws_timer;
    ESP_ERROR_CHECK(esp_timer_create(&ws_timer_args, &ws_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(ws_timer, 1000000)); /* 1s broadcast interval */

    /* ── OTA Rollback Validation ─────────────────────── */
    /* If we booted after an OTA update, defer confirmation to a task that
       observes a healthy-uptime window before canceling rollback. A boot
       loop or panic reboots before the window elapses, so the bootloader
       reverts to the previous firmware. */
    ota_confirm_task_start();

    boot_status_set("Ready");
    boot_status_mark_ready();

    ESP_LOGI(TAG, "=== Bisque started successfully ===");
    /* Report internal SRAM separately: with PSRAM enabled the total is in the
       megabytes and hides the pool that actually constrains this firmware —
       task stacks, DMA buffers and MALLOC_CAP_INTERNAL requests all come out
       of internal RAM only. */
    ESP_LOGI(TAG, "Free heap: %lu bytes total, %lu bytes internal", (unsigned long)esp_get_free_heap_size(),
             (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
}
