#pragma once

#include "freertos/FreeRTOS.h"

typedef uint32_t EventBits_t;
typedef void *EventGroupHandle_t;

EventGroupHandle_t xEventGroupCreate(void);
EventBits_t xEventGroupSetBits(EventGroupHandle_t g, EventBits_t bits);
EventBits_t xEventGroupClearBits(EventGroupHandle_t g, EventBits_t bits);
EventBits_t xEventGroupGetBits(EventGroupHandle_t g);
