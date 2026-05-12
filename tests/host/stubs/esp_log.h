#pragma once

/* Minimal host stub of ESP-IDF esp_log.h. Default is silent so tests don't
 * spam stdout; set HOST_TEST_LOG=1 in the environment to route logs to
 * stderr for debugging. */

#include <stdio.h>
#include <stdlib.h>

static inline int esp_log_enabled_for_test(void)
{
    static int cached = -1;
    if (cached < 0) {
        const char *e = getenv("HOST_TEST_LOG");
        cached = (e && *e && *e != '0') ? 1 : 0;
    }
    return cached;
}

#define ESP_LOG_FMT(level, tag, fmt, ...)                                     \
    do {                                                                      \
        if (esp_log_enabled_for_test()) {                                     \
            fprintf(stderr, "[%s] %s: " fmt "\n", level, tag, ##__VA_ARGS__); \
        }                                                                     \
    } while (0)

#define ESP_LOGE(tag, fmt, ...) ESP_LOG_FMT("E", tag, fmt, ##__VA_ARGS__)
#define ESP_LOGW(tag, fmt, ...) ESP_LOG_FMT("W", tag, fmt, ##__VA_ARGS__)
#define ESP_LOGI(tag, fmt, ...) ESP_LOG_FMT("I", tag, fmt, ##__VA_ARGS__)
#define ESP_LOGD(tag, fmt, ...) ESP_LOG_FMT("D", tag, fmt, ##__VA_ARGS__)
#define ESP_LOGV(tag, fmt, ...) ESP_LOG_FMT("V", tag, fmt, ##__VA_ARGS__)

#define ESP_ERROR_CHECK(x)                                                                         \
    do {                                                                                           \
        esp_err_t __err = (x);                                                                     \
        if (__err != 0) {                                                                          \
            fprintf(stderr, "ESP_ERROR_CHECK failed: 0x%x at %s:%d\n", __err, __FILE__, __LINE__); \
            abort();                                                                               \
        }                                                                                          \
    } while (0)
