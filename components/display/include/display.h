#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "driver/spi_master.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the ST7735 TFT display.
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
 * FreeRTOS task: updates the display at ~500ms intervals.
 * Shows temperature, status, segment info, elapsed time.
 * Pass NULL as parameter.
 */
void display_task(void *param);

#ifdef __cplusplus
}
#endif
