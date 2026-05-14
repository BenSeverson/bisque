#pragma once

#include "freertos/FreeRTOS.h"

/* Mutexes are no-ops in single-threaded host tests; just return non-NULL on
 * create so callers don't treat the engine as out-of-memory at init. */

typedef void *SemaphoreHandle_t;

SemaphoreHandle_t xSemaphoreCreateMutex(void);
BaseType_t xSemaphoreTake(SemaphoreHandle_t sem, TickType_t timeout);
BaseType_t xSemaphoreGive(SemaphoreHandle_t sem);
