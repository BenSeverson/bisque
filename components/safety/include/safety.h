#pragma once

#include <stdbool.h>
#include "esp_err.h"
#include "vent_state.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Event group bits */
#define SAFETY_BIT_EMERGENCY_STOP  (1 << 0)
#define SAFETY_BIT_TEMP_FAULT      (1 << 1)
#define SAFETY_BIT_FIRING_COMPLETE (1 << 2)

/* Why the most recent emergency stop tripped. The firing engine maps this onto
 * its own error code so the UI can show a specific cause; SAFETY_TRIP_OTHER
 * covers engine-initiated trips (not-rising, runaway) that already set their
 * own code, and control-loop stalls. */
typedef enum {
    SAFETY_TRIP_NONE = 0,
    SAFETY_TRIP_TC_FAULT,
    SAFETY_TRIP_OVER_TEMP,
    SAFETY_TRIP_OTHER,
} safety_trip_cause_t;

/**
 * Initialize the safety system.
 * @param ssr_pin       GPIO that drives the SSR (set LOW on emergency stop)
 * @param max_safe_temp User-configurable max temp (must be <= hardware max)
 */
esp_err_t safety_init(int ssr_pin, float max_safe_temp);

/**
 * Configure optional alarm and vent GPIO outputs.
 * Pass -1 to disable either GPIO.
 * @param alarm_gpio  GPIO for buzzer/relay on error or complete.
 * @param vent_gpio   GPIO for downdraft vent relay (active when firing at <700°C).
 */
void safety_init_io(int alarm_gpio, int vent_gpio);

/**
 * Trigger alarm output (call on firing complete or error if alarm_enabled).
 * @param pattern 0 = short beep, 1 = long beep, 2 = error pattern.
 */
void safety_trigger_alarm(int pattern);

/**
 * Update the vent relay GPIO based on current temperature and firing state.
 * Call from firing_task on each tick.
 * @param is_firing  true if firing is active.
 * @param current_temp_c  Current kiln temperature.
 */
void safety_update_vent(bool is_firing, float current_temp_c);

/**
 * State of the vent relay as of the last safety_update_vent() call, or
 * VENT_STATE_NOT_FITTED when no vent GPIO was configured.
 *
 * This is the pin's own state, not a re-derivation of the is_firing/temperature
 * rule: an operator looking at a vent indicator wants to know whether the fan is
 * running, and the two answers diverge whenever the firing task stops calling in
 * (a wedged control loop, a firing that ended between ticks).
 */
vent_state_t safety_get_vent_state(void);

/**
 * Get the global event group for safety/firing events.
 */
EventGroupHandle_t safety_get_event_group(void);

/**
 * Trigger an emergency stop. Immediately drives SSR LOW and sets event bit.
 * Equivalent to safety_emergency_stop_cause(SAFETY_TRIP_OTHER).
 */
void safety_emergency_stop(void);

/**
 * Like safety_emergency_stop(), but records why it tripped. The cause is latched
 * (first cause wins until safety_clear_emergency()).
 */
void safety_emergency_stop_cause(safety_trip_cause_t cause);

/**
 * Cause of the latched emergency stop, or SAFETY_TRIP_NONE if not tripped.
 */
safety_trip_cause_t safety_get_trip_cause(void);

/**
 * Clear the emergency stop condition (after user acknowledges).
 */
void safety_clear_emergency(void);

/**
 * Check if emergency stop is active.
 */
bool safety_is_emergency(void);

/**
 * Update the user-configurable max safe temperature.
 */
void safety_set_max_temp(float max_safe_temp);

/**
 * Get the current max safe temperature.
 */
float safety_get_max_temp(void);

/**
 * Set the thermocouple calibration offset (°C) used by the over-temp check so
 * safety compares the same corrected temperature the control loop acts on.
 */
void safety_set_tc_offset(float offset_c);

/**
 * Set the SSR output. Respects emergency stop (output forced to 0 during emergency).
 * @param duty 0.0 to 1.0
 */
void safety_set_ssr(float duty);

/**
 * Last SSR duty actually in force, 0.0 to 1.0 — i.e. element power.
 *
 * Read from here rather than from the firing engine's PID output because this
 * is the value the time-proportional window drives the pin with: it is already
 * clamped, zeroed by an emergency stop, and zeroed by the unsupervised-boot
 * guard. Reporting the engine's raw PID output instead would tell an operator
 * the element is at 80% while safety is holding it off.
 */
float safety_get_ssr_duty(void);

/**
 * FreeRTOS task: monitors temperature faults and over-temp at 500ms intervals.
 * Pass NULL as parameter.
 */
void safety_task(void *param);

#ifdef __cplusplus
}
#endif
