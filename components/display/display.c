#include "display.h"
#include "firing_engine.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "esp_log.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_st7735.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <stdio.h>

static const char *TAG = "display";

#define LCD_H_RES 128
#define LCD_V_RES 160

static esp_lcd_panel_handle_t s_panel = NULL;

/*
 * Simple 8x16 font rendering via direct pixel drawing.
 * For a production build, use a proper font library (e.g., LVGL).
 * This implementation draws text by filling rectangular character cells
 * with foreground/background colors (block text).
 *
 * For now we render status info to the serial log and draw colored
 * status bars on the LCD to indicate state.
 */

/* Color definitions (RGB565) */
#define COLOR_BLACK   0x0000
#define COLOR_WHITE   0xFFFF
#define COLOR_RED     0xF800
#define COLOR_GREEN   0x07E0
#define COLOR_ORANGE  0xFD20
#define COLOR_BLUE    0x001F
#define COLOR_YELLOW  0xFFE0

static void fill_rect(int x, int y, int w, int h, uint16_t color)
{
    if (!s_panel) return;

    /* Allocate a single row buffer */
    uint16_t *row = heap_caps_malloc(w * sizeof(uint16_t), MALLOC_CAP_DMA);
    if (!row) return;

    for (int i = 0; i < w; i++) {
        row[i] = color;
    }

    for (int row_y = y; row_y < y + h; row_y++) {
        esp_lcd_panel_draw_bitmap(s_panel, x, row_y, x + w, row_y + 1, row);
    }

    free(row);
}

static uint16_t status_color(firing_status_t status)
{
    switch (status) {
    case FIRING_STATUS_HEATING:  return COLOR_ORANGE;
    case FIRING_STATUS_HOLDING:  return COLOR_YELLOW;
    case FIRING_STATUS_COOLING:  return COLOR_BLUE;
    case FIRING_STATUS_ERROR:    return COLOR_RED;
    case FIRING_STATUS_COMPLETE: return COLOR_GREEN;
    case FIRING_STATUS_PAUSED:   return COLOR_YELLOW;
    case FIRING_STATUS_AUTOTUNE: return COLOR_ORANGE;
    default: return COLOR_GREEN;
    }
}

static const char *status_label(firing_status_t status)
{
    switch (status) {
    case FIRING_STATUS_IDLE:     return "IDLE";
    case FIRING_STATUS_HEATING:  return "HEATING";
    case FIRING_STATUS_HOLDING:  return "HOLDING";
    case FIRING_STATUS_COOLING:  return "COOLING";
    case FIRING_STATUS_COMPLETE: return "COMPLETE";
    case FIRING_STATUS_ERROR:    return "ERROR";
    case FIRING_STATUS_PAUSED:   return "PAUSED";
    case FIRING_STATUS_AUTOTUNE: return "AUTOTUNE";
    default: return "UNKNOWN";
    }
}

esp_err_t display_init(spi_host_device_t host, int cs_pin, int dc_pin, int rst_pin, int bl_pin)
{
    /* Backlight - WeAct ST7735 uses active-low (0 = on, 1 = off) */
    if (bl_pin >= 0) {
        gpio_config_t bl_cfg = {
            .pin_bit_mask = (1ULL << bl_pin),
            .mode = GPIO_MODE_OUTPUT,
        };
        gpio_config(&bl_cfg);
        gpio_set_level(bl_pin, 0);  /* LOW = backlight ON for WeAct modules */
    }

    /* LCD panel IO (SPI) */
    esp_lcd_panel_io_handle_t io_handle = NULL;
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = dc_pin,
        .cs_gpio_num = cs_pin,
        .pclk_hz = 10 * 1000 * 1000,  /* Some ST7735 modules need slower SPI */
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    esp_err_t ret = esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)host, &io_config, &io_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create panel IO: %s", esp_err_to_name(ret));
        return ret;
    }

    /* LCD panel (ST7735) */
    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = rst_pin,
        .rgb_endian = LCD_RGB_ENDIAN_BGR,
        .bits_per_pixel = 16,
    };
    ret = esp_lcd_new_panel_st7735(io_handle, &panel_config, &s_panel);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create panel: %s", esp_err_to_name(ret));
        return ret;
    }

    esp_lcd_panel_reset(s_panel);
    esp_lcd_panel_init(s_panel);
    /* WeAct ST7735 1.8" settings */
    esp_lcd_panel_set_gap(s_panel, 0, 0);  /* Try no offset */
    esp_lcd_panel_invert_color(s_panel, true);  /* WeAct needs inversion */
    esp_lcd_panel_swap_xy(s_panel, false);
    esp_lcd_panel_mirror(s_panel, false, false);
    esp_lcd_panel_disp_on_off(s_panel, true);

    /* Clear screen to black */
    fill_rect(0, 0, LCD_H_RES, LCD_V_RES, COLOR_BLACK);

    ESP_LOGI(TAG, "ST7735 display initialized (%dx%d)", LCD_H_RES, LCD_V_RES);
    return ESP_OK;
}

void display_task(void *param)
{
    (void)param;
    TickType_t last_wake = xTaskGetTickCount();

    ESP_LOGI(TAG, "display_task started");

    for (;;) {
        thermocouple_reading_t tc;
        thermocouple_get_latest(&tc);

        firing_progress_t prog;
        firing_engine_get_progress(&prog);

        /* Draw status indicator bar at top */
        uint16_t color = status_color(prog.status);
        fill_rect(0, 0, LCD_H_RES, 20, color);

        /* Draw temperature bar (proportional to temp, max ~1400°C) */
        float temp = tc.fault ? 0 : tc.temperature_c;
        int bar_width = (int)(temp / 1400.0f * LCD_H_RES);
        if (bar_width > LCD_H_RES) bar_width = LCD_H_RES;
        if (bar_width < 0) bar_width = 0;

        fill_rect(0, 30, LCD_H_RES, 20, COLOR_BLACK);  /* Clear bar area */
        fill_rect(0, 30, bar_width, 20, COLOR_RED);     /* Temp bar */

        /* Draw target temp bar */
        int target_x = (int)(prog.target_temp / 1400.0f * LCD_H_RES);
        if (target_x >= 0 && target_x < LCD_H_RES) {
            fill_rect(target_x, 30, 2, 20, COLOR_WHITE);  /* Target marker */
        }

        /* Draw segment progress indicator */
        if (prog.total_segments > 0 && prog.is_active) {
            int seg_w = LCD_H_RES / prog.total_segments;
            for (int i = 0; i < prog.total_segments; i++) {
                uint16_t seg_color = (i < prog.current_segment) ? COLOR_GREEN :
                                     (i == prog.current_segment) ? COLOR_ORANGE : COLOR_BLACK;
                fill_rect(i * seg_w, 60, seg_w - 1, 10, seg_color);
            }
        } else {
            fill_rect(0, 60, LCD_H_RES, 10, COLOR_BLACK);
        }

        /* Log to serial (human-readable status) */
        uint32_t hours = prog.elapsed_time / 3600;
        uint32_t mins = (prog.elapsed_time % 3600) / 60;
        ESP_LOGI(TAG, "Temp: %.0f°C/%.0f°C | %s | Seg %d/%d | %luh %lum",
                 temp, prog.target_temp, status_label(prog.status),
                 prog.current_segment + 1, prog.total_segments,
                 (unsigned long)hours, (unsigned long)mins);

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(500));
    }
}
