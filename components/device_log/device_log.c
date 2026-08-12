#include "device_log.h"
#include "log_sink.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef CONFIG_KILN_LOG_BUFFER_BYTES
#define CONFIG_KILN_LOG_BUFFER_BYTES 6144
#endif

#define LOG_RING_BYTES CONFIG_KILN_LOG_BUFFER_BYTES

static const char *TAG = "device_log";

static log_sink_t s_sink;
static char *s_storage = NULL;
static SemaphoreHandle_t s_mutex = NULL;
static vprintf_like_t s_chain = NULL;

/**
 * The esp_log hook. Runs on whichever task logged, so it must not log itself
 * (that would recurse through esp_log_write) and must not block for long.
 *
 * The UART write happens first and unconditionally: capturing a line is a
 * best-effort diagnostic, and a contended mutex must never cost the serial
 * console a message. When the lock is not free within a tick the line is
 * dropped from the ring only.
 */
static int log_vprintf_hook(const char *fmt, va_list args)
{
    va_list copy;
    va_copy(copy, args);
    int written = s_chain ? s_chain(fmt, args) : vprintf(fmt, args);

    /* Formatted separately from the UART path: the chained vprintf consumed its
       own va_list, and there is no portable way to read back what it emitted. */
    char line[LOG_SINK_LINE_MAX + 32];
    int n = vsnprintf(line, sizeof(line), fmt, copy);
    va_end(copy);

    if (n > 0) {
        size_t len = (size_t)n < sizeof(line) - 1 ? (size_t)n : sizeof(line) - 1;
        if (s_mutex && xSemaphoreTake(s_mutex, 1) == pdTRUE) {
            log_sink_write(&s_sink, line, len);
            xSemaphoreGive(s_mutex);
        }
    }
    return written;
}

esp_err_t device_log_init(void)
{
    if (s_storage) {
        return ESP_OK;
    }

    char *storage = malloc(LOG_RING_BYTES);
    if (!storage) {
        ESP_LOGE(TAG, "Failed to allocate %d-byte log buffer", LOG_RING_BYTES);
        return ESP_ERR_NO_MEM;
    }
    SemaphoreHandle_t mutex = xSemaphoreCreateMutex();
    if (!mutex) {
        free(storage);
        ESP_LOGE(TAG, "Failed to create log mutex");
        return ESP_ERR_NO_MEM;
    }

    log_sink_init(&s_sink, storage, LOG_RING_BYTES);
    s_storage = storage;
    s_mutex = mutex;
    /* Chain rather than replace, so the UART console keeps working. */
    s_chain = esp_log_set_vprintf(log_vprintf_hook);

    ESP_LOGI(TAG, "Device log capturing into %d bytes of RAM", LOG_RING_BYTES);
    return ESP_OK;
}

size_t device_log_capacity(void)
{
    return s_storage ? (size_t)LOG_RING_BYTES : 0;
}

size_t device_log_snapshot(char *dst, size_t dst_capacity, device_log_stats_t *stats)
{
    if (stats) {
        memset(stats, 0, sizeof(*stats));
        stats->capacity_bytes = device_log_capacity();
    }
    if (!dst || dst_capacity == 0 || !s_storage || !s_mutex) {
        return 0;
    }
    if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(100)) != pdTRUE) {
        return 0;
    }

    size_t lines = 0;
    size_t bytes = log_sink_snapshot(&s_sink, dst, dst_capacity, &lines);
    if (stats) {
        stats->line_count = lines;
        stats->used_bytes = s_sink.used;
        stats->dropped_lines = s_sink.dropped;
        stats->total_lines = s_sink.total;
    }
    xSemaphoreGive(s_mutex);
    return bytes;
}
