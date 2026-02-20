#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "driver/spi_master.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the ST7735 TFT display with LVGL.
 * Sets up LCD panel, LVGL core, double-buffered rendering,
 * button input (encoder-style), and the default input group.
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
 * Manages 4 navigable screens (Home, Chart, Profiles, Firing).
 * Pass NULL as parameter.
 */
void display_task(void *param);

#ifdef __cplusplus
}
#endif
