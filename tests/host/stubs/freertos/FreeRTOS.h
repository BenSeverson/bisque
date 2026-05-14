#pragma once

/* Minimal FreeRTOS shim for the host test harness. Single-threaded, so
 * mutexes are no-ops; critical sections are no-ops; tick is derived from
 * the virtual esp_timer clock. Queues are real FIFOs (the firing engine
 * relies on them to ferry commands and events). */

#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef uint32_t TickType_t;
typedef int32_t BaseType_t;
typedef uint32_t UBaseType_t;

#define pdTRUE  1
#define pdFALSE 0
#define pdPASS  1
#define pdFAIL  0

#define portMAX_DELAY      ((TickType_t)0xFFFFFFFFU)
#define portTICK_PERIOD_MS 1
#define pdMS_TO_TICKS(ms)  ((TickType_t)(ms))

typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(mux)      ((void)(mux))
#define portEXIT_CRITICAL(mux)       ((void)(mux))
