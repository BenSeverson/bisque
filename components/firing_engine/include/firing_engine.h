#pragma once

#include "firing_types.h"
#include "pid_control.h"
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

/**
 * Find the first segment whose ramp-rate sign is inconsistent with the
 * direction from its starting temperature to its target (a segment that would
 * be mislabelled HEATING/COOLING, disabling the heating watchdogs).
 *
 * Segment 0 starts from `start_temp`; later segments start from the previous
 * target. Pass a non-finite `start_temp` (NAN) to skip segment 0's own check
 * when the firing-start temperature is unknown (profile save). Returns the
 * offending segment index, or -1 if all segments are consistent. Pure.
 *
 * Defined in firing_helpers.c.
 */
int firing_first_bad_ramp_sign(const firing_profile_t *profile, float start_temp);

/**
 * True while a relay diagnostic pulse is holding the SSR on. This is a
 * distinct busy state from a firing: `firing_engine_get_progress()` reports
 * is_active == false during a relay test, so callers that must not run
 * concurrently with it (firing start, autotune start, OTA, reboot) have to
 * consult this in addition to is_active.
 */
bool firing_engine_relay_test_active(void);

/**
 * Arm a relay diagnostic pulse for `duration_s` seconds (clamped to
 * [1, RELAY_TEST_MAX_S internally]). Returns true if armed, false if the kiln
 * is busy (firing, armed delayed start, autotune, or a test already running).
 *
 * Synchronous and atomic: the caller gets a definitive answer with no queue
 * latency, so an HTTP handler can return a real 200/409 instead of a fire-and-
 * forget {ok:true}. Does not check OTA — callers that need that gate it
 * separately. The firing tick drives the SSR for the armed pulse.
 */
bool firing_engine_relay_test_arm(uint32_t duration_s);

/* ── Firing transition events ───────────────────────── */

typedef enum {
    FIRING_EVENT_COMPLETE,
    FIRING_EVENT_ERROR,
} firing_event_kind_t;

typedef struct {
    firing_event_kind_t kind;
    char profile_id[FIRING_ID_LEN];
    char profile_name[FIRING_NAME_LEN];
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
 * Outcome of the most recent auto-tune run.
 *
 * The run itself is over by the time this matters — the engine calls do_stop()
 * as soon as pid_autotune_update() reports done, which returns the progress
 * status to IDLE. Without this, a finished tune and a never-started one are
 * indistinguishable over the API, which is what forced the client to guess with
 * a grace window and report "unconfirmed" (#216).
 *
 * AUTOTUNE_COMPLETE means gains were computed and persisted; AUTOTUNE_FAILED
 * means the run ended without usable gains; AUTOTUNE_IDLE means nothing has run
 * since boot, or the last run was cancelled.
 *
 * Taken as one snapshot with the progress, under the same lock, because the
 * reported state is a function of both: reading them separately can pair a
 * pre-transition status with a post-transition autotune state and report a
 * completed run as "stopped".
 */
void firing_engine_get_autotune_snapshot(firing_progress_t *out_prog, autotune_state_t *out_state);

/**
 * Get current kiln settings (thread-safe copy).
 */
void firing_engine_get_settings(kiln_settings_t *out);

/**
 * Update kiln settings (thread-safe). Saves to NVS.
 */
esp_err_t firing_engine_set_settings(const kiln_settings_t *settings);

/**
 * Read the gains the control loop is currently using (thread-safe).
 *
 * These are the live gains, not a re-read of NVS: after an auto-tune the engine
 * applies the result to the running controller, and this is what reports it.
 */
void firing_engine_get_pid_gains(float *kp, float *ki, float *kd);

/**
 * Replace the PID gains and persist them to NVS.
 *
 * Auto-tune is not the only way a kiln arrives at good gains — people migrate
 * from other controllers with numbers already derived on the same hardware, and
 * a bad tuning run otherwise has no correction short of another one (#182).
 *
 * @return ESP_OK on success;
 *         ESP_ERR_INVALID_ARG if the gains fail pid_gains_valid();
 *         ESP_ERR_INVALID_STATE if a firing, an armed delayed start, or an
 *         auto-tune is active. The running loop's integrator was wound up under
 *         the old Ki, so its contribution rescales the instant Ki changes —
 *         a step in element duty cycle partway up a ramp. Waiting for idle is
 *         the whole fix, and it costs a kiln owner nothing.
 */
esp_err_t firing_engine_set_pid_gains(float kp, float ki, float kd);

/**
 * Get the active temperature display unit ('C' or 'F'). Thread-safe, cheap —
 * intended for presentation-layer formatting (the LVGL display reads this
 * every refresh). All internal temperatures remain Celsius.
 */
char firing_engine_get_temp_unit(void);

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
 * by a flat hold for `hold_time` minutes. `hold_time == 0` is a 0-duration
 * pass-through. `hold_time == FIRING_HOLD_INDEFINITE` (skip-to-advance hold)
 * has no defined planned duration and is treated as 0 in the curve.
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
