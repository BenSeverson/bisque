#pragma once

/* Minimal host stub of ESP-IDF esp_err.h — enough to compile cone_table /
 * pid_control / firing_engine_internal under the unit-test harness. Numeric
 * values match ESP-IDF where it matters (callers compare to ESP_OK and pass
 * codes through; we don't translate to strings except via esp_err_to_name). */

typedef int esp_err_t;

#define ESP_OK   0
#define ESP_FAIL -1

#define ESP_ERR_NO_MEM        0x101
#define ESP_ERR_INVALID_ARG   0x102
#define ESP_ERR_INVALID_STATE 0x103
#define ESP_ERR_INVALID_SIZE  0x104
#define ESP_ERR_NOT_FOUND     0x105

#define ESP_ERR_NVS_BASE      0x1100
#define ESP_ERR_NVS_NOT_FOUND (ESP_ERR_NVS_BASE + 0x02)

const char *esp_err_to_name(esp_err_t code);
