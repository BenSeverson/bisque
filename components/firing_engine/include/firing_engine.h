#pragma once

#include "firing_types.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the firing engine. Creates command queue, mutex, and loads settings from NVS.
 */
esp_err_t firing_engine_init(void);

/**
 * Get the command queue (for sending commands from web API).
 */
QueueHandle_t firing_engine_get_cmd_queue(void);

/**
 * Get current firing progress (thread-safe copy).
 */
void firing_engine_get_progress(firing_progress_t *out);

/**
 * Get current kiln settings (thread-safe copy).
 */
void firing_engine_get_settings(kiln_settings_t *out);

/**
 * Update kiln settings (thread-safe). Saves to NVS.
 */
esp_err_t firing_engine_set_settings(const kiln_settings_t *settings);

/* ── Profile Storage (NVS) ─────────────────────────── */

/**
 * Save a profile to NVS.
 */
esp_err_t firing_engine_save_profile(const firing_profile_t *profile);

/**
 * Load a profile from NVS by ID.
 */
esp_err_t firing_engine_load_profile(const char *id, firing_profile_t *profile);

/**
 * Delete a profile from NVS by ID.
 */
esp_err_t firing_engine_delete_profile(const char *id);

/**
 * List all stored profile IDs. Returns count.
 * ids_out must be an array of FIRING_MAX_PROFILES entries, each FIRING_ID_LEN chars.
 */
int firing_engine_list_profiles(char ids_out[][FIRING_ID_LEN], int max_count);

/**
 * FreeRTOS task: runs the firing state machine, PID control, SSR output.
 * Pass NULL as parameter.
 */
void firing_task(void *param);

#ifdef __cplusplus
}
#endif
