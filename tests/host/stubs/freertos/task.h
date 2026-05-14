#pragma once

#include "freertos/FreeRTOS.h"

/* Returned in milliseconds derived from the virtual esp_timer clock so
 * pdMS_TO_TICKS(1000) lines up. Host harness never blocks. */
TickType_t xTaskGetTickCount(void);
void vTaskDelay(TickType_t ticks);
void vTaskDelayUntil(TickType_t *last_wake, TickType_t increment);
