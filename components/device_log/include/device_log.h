#pragma once

/**
 * In-RAM device log (#189).
 *
 * Installs an esp_log_set_vprintf() hook that tees every ESP_LOGx line into a
 * fixed ring buffer while still writing it to the UART, so a kiln that misfires
 * in a studio with no serial console attached still has the last few hundred
 * lines available over the API. GET /api/v1/log serves them, and the web UI's
 * "Download diagnostics" button bundles them with /system and /settings.
 *
 * RAM only, deliberately: a firing writes a line every few seconds, and putting
 * that on SPIFFS would spend the flash's erase budget on log rotation. The
 * buffer does not survive a reboot — an operator chasing a crash pulls the
 * bundle before restarting.
 */

#include "esp_err.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    size_t line_count;      /* lines in the snapshot just taken */
    size_t used_bytes;      /* bytes retained in the ring, terminators included */
    size_t capacity_bytes;  /* ring size */
    uint32_t dropped_lines; /* lines evicted since boot (buffer wrapped) */
    uint32_t total_lines;   /* lines captured since boot */
} device_log_stats_t;

/**
 * Allocate the ring and install the log hook. Safe to call twice (the second
 * call is a no-op). Returns ESP_ERR_NO_MEM if the ring or its mutex could not
 * be allocated, in which case logging is untouched and the endpoint reports an
 * empty log rather than failing.
 */
esp_err_t device_log_init(void);

/** Ring size in bytes, or 0 when the log was never initialized. */
size_t device_log_capacity(void);

/**
 * Copy the retained lines into `dst` as a packed NUL-separated block, oldest
 * first; returns the number of bytes written. Pass a `dst` of
 * device_log_capacity() bytes to be sure nothing is dropped — a smaller buffer
 * keeps the newest lines. `stats` is optional.
 */
size_t device_log_snapshot(char *dst, size_t dst_capacity, device_log_stats_t *stats);

#ifdef __cplusplus
}
#endif
