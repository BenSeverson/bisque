#include "display.h"
#include "ui_common.h"
#include "dashboard.h"
#include "modal.h"
#include "thermocouple.h"
#include "firing_engine.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "lvgl.h"

static const char *TAG = "display_task";

/* Externals from display_init.c */
extern SemaphoreHandle_t g_lvgl_mutex;
extern lv_indev_t *g_indev_encoder;
extern lv_group_t *g_input_group;

/* LEFT closes the open modal; RIGHT is reserved (drained so its press-edge state stays in sync). */
static void check_left_cancel(void)
{
    if (display_consume_left_press()) {
        if (dashboard_modal_active()) {
            dashboard_modal_close();
        }
    }
    (void)display_consume_right_press();
}

void display_task(void *param)
{
    (void)param;
    ESP_LOGI(TAG, "display_task started");

    if (xSemaphoreTake(g_lvgl_mutex, portMAX_DELAY)) {
        dashboard_create();
        xSemaphoreGive(g_lvgl_mutex);
    }

    TickType_t last_wake = xTaskGetTickCount();
    int64_t last_data_update_us = 0;

    for (;;) {
        /* LVGL timer handler (~30ms interval → ~30 FPS) */
        if (xSemaphoreTake(g_lvgl_mutex, pdMS_TO_TICKS(10))) {
            lv_timer_handler();
            check_left_cancel();
            xSemaphoreGive(g_lvgl_mutex);
        }

        /* Data polling at 500ms intervals */
        int64_t now_us = esp_timer_get_time();
        if (now_us - last_data_update_us >= 500000) {
            last_data_update_us = now_us;

            thermocouple_reading_t tc;
            thermocouple_get_latest(&tc);

            firing_progress_t prog;
            firing_engine_get_progress(&prog);

            if (xSemaphoreTake(g_lvgl_mutex, pdMS_TO_TICKS(10))) {
                dashboard_update(&tc, &prog);
                xSemaphoreGive(g_lvgl_mutex);
            }

            /* Log LVGL heap usage to help right-size CONFIG_LV_MEM_SIZE_KILOBYTES (currently 64 KB).
             * Once you know peak usage, shrink the pool to reclaim DIRAM for the system heap. */
            lv_mem_monitor_t mon;
            lv_mem_monitor(&mon);
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
