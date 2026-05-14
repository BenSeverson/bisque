#pragma once

#include "freertos/FreeRTOS.h"

/* Real FIFO semantics — the firing engine drains command and event queues
 * during normal operation, and tests inspect emitted events. */

typedef void *QueueHandle_t;

QueueHandle_t xQueueCreate(UBaseType_t length, UBaseType_t item_size);
BaseType_t xQueueSend(QueueHandle_t q, const void *item, TickType_t timeout);
BaseType_t xQueueReceive(QueueHandle_t q, void *out, TickType_t timeout);
UBaseType_t uxQueueMessagesWaiting(QueueHandle_t q);
