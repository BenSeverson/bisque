#include "display.h"
#include "ui_common.h"
#include "dashboard.h"
#include "modal.h"
#include "splash.h"
#include "boot_status.h"
#include "thermocouple.h"
#include "firing_engine.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"

static const char *TAG = "display_task";

#define SPLASH_MIN_VISIBLE_US 1500000 /* keep splash on screen at least 1.5 s */

static void check_left_cancel(void)
{
    bool left = display_consume_left_press();
    bool right = display_consume_right_press();
    if (!left && !right) {
        return;
    }

    lv_lock();
    if (dashboard_modal_active()) {
        if (left) {
            dashboard_modal_nav_left();
        }
        if (right) {
            dashboard_modal_nav_right();
        }
    }
    lv_unlock();
}

/* Render the splash, then loop pumping LVGL until boot is complete and the
 * splash has been visible for at least SPLASH_MIN_VISIBLE_US. Status text is
 * pushed onto the splash whenever main has published a new pointer. */
static void run_splash_phase(void)
{
    lv_lock();
    splash_create();
    lv_unlock();

    /* Pump LVGL until the first frame is fully flushed, then raise the backlight.
     * Partial render mode pushes the 320 rows in 8 chunks via async DMA; running
     * the handler ~10 times with a short delay between calls covers the chunks
     * plus their on_color_trans_done callbacks. Without this warm-up the panel
     * shows uninitialized VRAM (static) when the backlight first comes on. */
    for (int i = 0; i < 10; i++) {
        lv_lock();
        lv_timer_handler();
        lv_unlock();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    display_backlight_on();

    int64_t shown_at_us = esp_timer_get_time();
    const char *last_status = boot_status_get();

    for (;;) {
        const char *current = boot_status_get();
        if (current != last_status) {
            last_status = current;
            lv_lock();
            splash_set_status(current);
            lv_unlock();
        }

        lv_lock();
        lv_timer_handler();
        lv_unlock();

        if (boot_status_is_ready() && (esp_timer_get_time() - shown_at_us) >= SPLASH_MIN_VISIBLE_US) {
            break;
        }

        vTaskDelay(pdMS_TO_TICKS(30));
    }
}

void display_task(void *param)
{
    (void)param;
    ESP_LOGI(TAG, "display_task started");

    run_splash_phase();

    /* Hand off splash → dashboard inside a single lv_lock region so LVGL never
     * renders an intermediate frame between the two. */
    lv_lock();
    splash_destroy();
    dashboard_create();
    lv_unlock();

    TickType_t last_wake = xTaskGetTickCount();
    int64_t last_data_update_us = 0;

    for (;;) {
        /* LVGL timer handler (~30ms interval → ~30 FPS) */
        lv_timer_handler();
        check_left_cancel();

        /* Data polling at 500ms intervals */
        int64_t now_us = esp_timer_get_time();
        if (now_us - last_data_update_us >= 500000) {
            last_data_update_us = now_us;

            thermocouple_reading_t tc;
            thermocouple_get_latest(&tc);

            firing_progress_t prog;
            firing_engine_get_progress(&prog);

            /* Log LVGL heap usage to help right-size CONFIG_LV_MEM_SIZE_KILOBYTES (currently 64 KB).
             * Once you know peak usage, shrink the pool to reclaim DIRAM for the system heap.
             * TODO: remove this
             */
            lv_mem_monitor_t mon;
            lv_lock();
            dashboard_update(&tc, &prog);
            lv_mem_monitor(&mon);
            lv_unlock();
            ESP_LOGI(TAG, "LVGL mem: %lu used, %lu free, %d%% frag", (unsigned long)(mon.total_size - mon.free_size),
                     (unsigned long)mon.free_size, mon.frag_pct);

            float temp = tc.fault ? 0 : tc.temperature_c;
            uint32_t hours = prog.elapsed_time / 3600;
            uint32_t mins = (prog.elapsed_time % 3600) / 60;
            ESP_LOGI(TAG, "Temp: %.0f°C/%.0f°C | %s | Seg %d/%d | %" PRIu32 "h %" PRIu32 "m", temp, prog.target_temp,
                     ui_status_label(prog.status), prog.current_segment + 1, prog.total_segments, hours, mins);
        }

        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(30));
    }
}
