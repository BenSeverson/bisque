/* Stub for FreeRTOS queue.h */
#pragma once
#include "FreeRTOS.h"

static inline BaseType_t xQueueSend(QueueHandle_t q, const void *item, uint32_t ticks)
{
    (void)q; (void)item; (void)ticks;
    return pdTRUE;
}
