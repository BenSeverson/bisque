#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the WS2812B status LED on APP_PIN_STATUS_LED.
 *
 * Returns ESP_ERR_NOT_SUPPORTED, without touching RMT, when the pin is
 * negative (no LED fitted - the rev C PCB). Do not start status_led_task()
 * unless this returned ESP_OK.
 */
esp_err_t status_led_init(void);

/**
 * FreeRTOS task: polls system state every 250ms and updates the LED.
 * Pass NULL as parameter.
 */
void status_led_task(void *param);

#ifdef __cplusplus
}
#endif
