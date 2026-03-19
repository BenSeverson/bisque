#include "display.h"
#include "ui_common.h"
#include "ui_screen_home.h"
#include "ui_screen_chart.h"
#include "ui_screen_profiles.h"
#include "ui_screen_firing.h"
#include "app_config.h"
#include "thermocouple.h"
#include "firing_engine.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "lvgl.h"
#include <string.h>

static const char *TAG = "display_task";

/* Externals from display_init.c */
extern SemaphoreHandle_t g_lvgl_mutex;
extern lv_indev_t       *g_indev_encoder;
extern lv_group_t       *g_input_group;

/* Screen objects */
static lv_obj_t *s_screens[UI_SCREEN_COUNT];
static ui_screen_id_t s_current_screen = UI_SCREEN_HOME;

/* Long-press detection for screen switching */
#define LONG_PRESS_MS 800
static int64_t s_select_press_start_us = 0;
static bool    s_select_was_long = false;

static void ui_switch_screen(ui_screen_id_t id)
{
    if (id >= UI_SCREEN_COUNT) return;
    if (id == s_current_screen && lv_screen_active() == s_screens[id]) return;

    s_current_screen = id;
    lv_screen_load_anim(s_screens[id], LV_SCR_LOAD_ANIM_FADE_IN, 200, 0, false);

    /* Update page dots on all screens */
    ui_screen_home_set_page_dots(id, UI_SCREEN_COUNT);
    ui_screen_chart_set_page_dots(id, UI_SCREEN_COUNT);
    ui_screen_profiles_set_page_dots(id, UI_SCREEN_COUNT);
    ui_screen_firing_set_page_dots(id, UI_SCREEN_COUNT);

    /* Refresh profile list when switching to profiles screen */
    if (id == UI_SCREEN_PROFILES) {
        ui_screen_profiles_refresh();
    }

    ESP_LOGI(TAG, "Switched to screen %d", id);
}

static void check_long_press_screen_switch(void)
{
    bool sel_pressed = (gpio_get_level(APP_PIN_BTN_SELECT) == 0);

    if (sel_pressed && s_select_press_start_us == 0) {
        s_select_press_start_us = esp_timer_get_time();
        s_select_was_long = false;
    } else if (sel_pressed && !s_select_was_long) {
        int64_t held_ms = (esp_timer_get_time() - s_select_press_start_us) / 1000;
        if (held_ms >= LONG_PRESS_MS) {
            s_select_was_long = true;
            ui_screen_id_t next = (s_current_screen + 1) % UI_SCREEN_COUNT;
            ui_switch_screen(next);
        }
    } else if (!sel_pressed) {
        s_select_press_start_us = 0;
        s_select_was_long = false;
    }
}

void display_task(void *param)
{
    (void)param;
    ESP_LOGI(TAG, "display_task started");

    /* Create all screens */
    if (xSemaphoreTake(g_lvgl_mutex, portMAX_DELAY)) {
        s_screens[UI_SCREEN_HOME]     = ui_screen_home_create();
        s_screens[UI_SCREEN_CHART]    = ui_screen_chart_create();
        s_screens[UI_SCREEN_PROFILES] = ui_screen_profiles_create();
        s_screens[UI_SCREEN_FIRING]   = ui_screen_firing_create();

        /* Load home screen */
        lv_screen_load(s_screens[UI_SCREEN_HOME]);
        ui_screen_home_set_page_dots(UI_SCREEN_HOME, UI_SCREEN_COUNT);
        ui_screen_chart_set_page_dots(UI_SCREEN_HOME, UI_SCREEN_COUNT);
        ui_screen_profiles_set_page_dots(UI_SCREEN_HOME, UI_SCREEN_COUNT);
        ui_screen_firing_set_page_dots(UI_SCREEN_HOME, UI_SCREEN_COUNT);

        xSemaphoreGive(g_lvgl_mutex);
    }

    TickType_t last_wake = xTaskGetTickCount();
    int64_t last_data_update_us = 0;

    for (;;) {
        /* LVGL timer handler (~30ms interval → ~30 FPS) */
        if (xSemaphoreTake(g_lvgl_mutex, pdMS_TO_TICKS(10))) {
            lv_timer_handler();
            check_long_press_screen_switch();
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
                ui_screen_home_update(&tc, &prog);
                if (s_current_screen == UI_SCREEN_CHART) {
                    ui_screen_chart_update(&tc);
                }
                ui_screen_firing_update(&tc, &prog);
                xSemaphoreGive(g_lvgl_mutex);
            }

            /* Serial log */
            float temp = tc.fault ? 0 : tc.temperature_c;
            uint32_t hours = prog.elapsed_time / 3600;
            uint32_t mins = (prog.elapsed_time % 3600) / 60;
            ESP_LOGI(TAG, "Temp: %.0f°C/%.0f°C | %s | Seg %d/%d | %" PRIu32 "h %" PRIu32 "m",
                     temp, prog.target_temp, ui_status_label(prog.status),
                     prog.current_segment + 1, prog.total_segments,
                     hours, mins);
        }

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(30));
    }
}
