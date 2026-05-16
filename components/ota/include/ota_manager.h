#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define OTA_VERSION_MAX 32
#define OTA_URL_MAX     256
#define OTA_SHA256_MAX  65
#define OTA_NOTES_MAX   128

/* Parsed release manifest fetched from the GitHub releases channel. */
typedef struct {
    char version[OTA_VERSION_MAX];
    char url[OTA_URL_MAX];
    char sha256[OTA_SHA256_MAX];
    uint32_t size;
    char notes[OTA_NOTES_MAX];
} ota_manifest_t;

typedef enum {
    OTA_PHASE_IDLE,
    OTA_PHASE_DOWNLOAD,
    OTA_PHASE_FLASH,
    OTA_PHASE_COMPLETE,
    OTA_PHASE_ERROR,
} ota_phase_t;

/*
 * Progress callback. `percent` is 0..100; `err` is NULL unless
 * `phase == OTA_PHASE_ERROR`. Invoked from the OTA worker task.
 */
typedef void (*ota_progress_cb_t)(ota_phase_t phase, int percent, const char *err);

/* Register a progress sink (the web server registers a WebSocket broadcaster). */
void ota_set_progress_cb(ota_progress_cb_t cb);

/* Version string of the running app (from esp_app_get_description()). */
const char *ota_current_version(void);

/*
 * Fetch and parse the release manifest. Blocking (network I/O, ~seconds).
 * Returns ESP_ERR_INVALID_STATE if an OTA operation is already running.
 */
esp_err_t ota_check(ota_manifest_t *out_manifest);

/*
 * Begin installing `manifest` on a background task and return immediately.
 * Progress is reported via the registered callback; the device reboots on
 * success. Returns ESP_ERR_INVALID_STATE if an OTA operation is running.
 */
esp_err_t ota_install_from_manifest(const ota_manifest_t *manifest);

/* True while a check or install is in progress. */
bool ota_is_busy(void);

/*
 * Spawn the one-shot confirm task. If the running image is pending
 * verification, the task waits a healthy-uptime window and then cancels
 * rollback. Call once after core services are up.
 */
void ota_confirm_task_start(void);

#ifdef __cplusplus
}
#endif
