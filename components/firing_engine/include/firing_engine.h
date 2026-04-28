#pragma once

#include "firing_types.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

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

/* ── Firing transition events ───────────────────────── */

typedef enum {
    FIRING_EVENT_COMPLETE,
    FIRING_EVENT_ERROR,
} firing_event_kind_t;

typedef struct {
    firing_event_kind_t kind;
    char profile_id[FIRING_ID_LEN];
    float peak_temp;
    uint32_t duration_s;
} firing_event_t;

/**
 * Get the firing-event queue. Drained by a consumer task that runs slow
 * side-effects (alarm beeps, webhook POST) off the firing/safety hot path.
 */
QueueHandle_t firing_engine_get_event_queue(void);

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
 * Get the last firing error code.
 */
firing_error_code_t firing_engine_get_error_code(void);

/**
 * Get accumulated element-on time in seconds (for wear tracking).
 */
uint32_t firing_engine_get_element_hours_s(void);

/**
 * Compute the planned setpoint at a given elapsed time within a profile.
 *
 * Walks segments in order — each consists of a ramp from the previous
 * segment's target to the current target at `ramp_rate` (°C/hr), followed
 * by a flat hold for `hold_time` minutes. `hold_time == 0` is treated as
 * a 0-duration hold (matches `estimated_duration` accounting; the firing
 * engine treats it as an infinite hold but that's not meaningful for a
 * planned curve).
 *
 * @param profile     Profile to walk. NULL or empty profile returns start_temp.
 * @param t_seconds   Elapsed time since firing started.
 * @param start_temp  Temperature segment 0 begins at. The kiln's actual start
 *                    temp is unknown to a UI (and to anyone after a reboot),
 *                    so callers typically pass a fixed assumption like 20°C.
 * @return Planned setpoint in °C. Saturates to the last segment's target after
 *         the profile completes.
 */
float firing_planned_temp_at(const firing_profile_t *profile, uint32_t t_seconds, float start_temp);

/**
 * FreeRTOS task: runs the firing state machine, PID control, SSR output.
 * Pass NULL as parameter.
 */
void firing_task(void *param);

#ifdef __cplusplus
}
#endif
