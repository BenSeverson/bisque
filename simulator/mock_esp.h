/**
 * Mock ESP-IDF types and functions for the desktop simulator.
 * Provides stubs for thermocouple, firing engine, and FreeRTOS APIs
 * that the display screens depend on.
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

/* --- esp_err.h stub --- */
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1

/* --- esp_log.h stub --- */
#define ESP_LOGI(tag, fmt, ...) (void)0
#define ESP_LOGW(tag, fmt, ...) (void)0
#define ESP_LOGE(tag, fmt, ...) (void)0

/* --- FreeRTOS stubs --- */
typedef void *QueueHandle_t;
typedef int BaseType_t;
#define pdTRUE 1
#define pdFALSE 0
#define pdMS_TO_TICKS(ms) (ms)

static inline BaseType_t xQueueSend(QueueHandle_t q, const void *item, uint32_t ticks)
{
    (void)q; (void)item; (void)ticks;
    return pdTRUE;
}
