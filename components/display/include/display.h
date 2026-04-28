#pragma once

#include "esp_err.h"
#include "driver/spi_master.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the ST7796S TFT display with LVGL.
 * Sets up LCD panel, LVGL core, double-buffered rendering,
 * 5-way nav switch input (Up/Down/Left/Right/Center), and the default input group.
 * The SPI bus must already be initialized.
 *
 * @param host    SPI host
 * @param cs_pin  Chip select GPIO
 * @param dc_pin  Data/Command GPIO
 * @param rst_pin Reset GPIO
 * @param bl_pin  Backlight GPIO (-1 to skip)
 */
esp_err_t display_init(spi_host_device_t host, int cs_pin, int dc_pin, int rst_pin, int bl_pin);

/**
 * FreeRTOS task: runs the LVGL timer handler and updates screen content.
 * Renders at ~30 FPS, polls thermocouple + firing data at 500ms.
 * Drives a single adaptive dashboard whose layout swaps based on firing status.
 * Pass NULL as parameter.
 */
void display_task(void *param);

/* Returns true exactly once per debounced press of Left / Right on the nav switch. */
bool display_consume_left_press(void);
bool display_consume_right_press(void);

/* Drives the backlight pin high. display_init() leaves it low so the panel's
 * uninitialized VRAM isn't visible as static at power-on; display_task calls
 * this once the first frame has been flushed. */
void display_backlight_on(void);

#ifdef __cplusplus
}
#endif
