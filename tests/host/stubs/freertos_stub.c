#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include <stdlib.h>
#include <string.h>

/* ── tick ──────────────────────────────────────────────────────────────── */

TickType_t xTaskGetTickCount(void)
{
    /* Convert virtual microseconds to milliseconds (portTICK_PERIOD_MS=1). */
    return (TickType_t)(esp_timer_get_time() / 1000);
}

void vTaskDelay(TickType_t ticks)
{
    (void)ticks;
}

void vTaskDelayUntil(TickType_t *last_wake, TickType_t increment)
{
    if (last_wake) {
        *last_wake += increment;
    }
}

/* ── mutex ─────────────────────────────────────────────────────────────── */

SemaphoreHandle_t xSemaphoreCreateMutex(void)
{
    /* Non-NULL sentinel — single-threaded tests don't need actual locking. */
    static int s_sentinel;
    return &s_sentinel;
}

BaseType_t xSemaphoreTake(SemaphoreHandle_t sem, TickType_t timeout)
{
    (void)sem;
    (void)timeout;
    return pdTRUE;
}

BaseType_t xSemaphoreGive(SemaphoreHandle_t sem)
{
    (void)sem;
    return pdTRUE;
}

/* ── queue ─────────────────────────────────────────────────────────────── */

typedef struct {
    UBaseType_t capacity;
    UBaseType_t item_size;
    UBaseType_t count;
    UBaseType_t head; /* next slot to read */
    UBaseType_t tail; /* next slot to write */
    uint8_t *buffer;
} queue_t;

QueueHandle_t xQueueCreate(UBaseType_t length, UBaseType_t item_size)
{
    queue_t *q = calloc(1, sizeof(*q));
    if (!q) {
        return NULL;
    }
    q->buffer = calloc(length, item_size);
    if (!q->buffer) {
        free(q);
        return NULL;
    }
    q->capacity = length;
    q->item_size = item_size;
    return q;
}

BaseType_t xQueueSend(QueueHandle_t qh, const void *item, TickType_t timeout)
{
    (void)timeout;
    queue_t *q = (queue_t *)qh;
    if (!q || q->count >= q->capacity) {
        return pdFAIL;
    }
    memcpy(q->buffer + q->tail * q->item_size, item, q->item_size);
    q->tail = (q->tail + 1) % q->capacity;
    q->count++;
    return pdPASS;
}

BaseType_t xQueueReceive(QueueHandle_t qh, void *out, TickType_t timeout)
{
    (void)timeout;
    queue_t *q = (queue_t *)qh;
    if (!q || q->count == 0) {
        return pdFAIL;
    }
    memcpy(out, q->buffer + q->head * q->item_size, q->item_size);
    q->head = (q->head + 1) % q->capacity;
    q->count--;
    return pdPASS;
}

UBaseType_t uxQueueMessagesWaiting(QueueHandle_t qh)
{
    queue_t *q = (queue_t *)qh;
    return q ? q->count : 0;
}

/* ── event group ───────────────────────────────────────────────────────── */

typedef struct {
    EventBits_t bits;
} event_group_t;

EventGroupHandle_t xEventGroupCreate(void)
{
    return calloc(1, sizeof(event_group_t));
}

EventBits_t xEventGroupSetBits(EventGroupHandle_t gh, EventBits_t bits)
{
    event_group_t *g = (event_group_t *)gh;
    if (!g) {
        return 0;
    }
    g->bits |= bits;
    return g->bits;
}

EventBits_t xEventGroupClearBits(EventGroupHandle_t gh, EventBits_t bits)
{
    event_group_t *g = (event_group_t *)gh;
    if (!g) {
        return 0;
    }
    EventBits_t old = g->bits;
    g->bits &= ~bits;
    return old;
}

EventBits_t xEventGroupGetBits(EventGroupHandle_t gh)
{
    event_group_t *g = (event_group_t *)gh;
    return g ? g->bits : 0;
}
