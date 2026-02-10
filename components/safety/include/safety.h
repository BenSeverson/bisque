#pragma once

#include <stdbool.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Event group bits */
#define SAFETY_BIT_EMERGENCY_STOP  (1 << 0)
#define SAFETY_BIT_TEMP_FAULT      (1 << 1)
#define SAFETY_BIT_FIRING_COMPLETE (1 << 2)

/**
 * Initialize the safety system.
 * @param ssr_pin  GPIO that drives the SSR (set LOW on emergency stop)
 * @param max_safe_temp  User-configurable max temp (must be <= hardware max)
 */
esp_err_t safety_init(int ssr_pin, float max_safe_temp);

/**
 * Get the global event group for safety/firing events.
 */
EventGroupHandle_t safety_get_event_group(void);

/**
 * Trigger an emergency stop. Immediately drives SSR LOW and sets event bit.
 */
void safety_emergency_stop(void);

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
 * Set the SSR output. Respects emergency stop (output forced to 0 during emergency).
 * @param duty 0.0 to 1.0
 */
void safety_set_ssr(float duty);

/**
 * FreeRTOS task: monitors temperature faults and over-temp at 500ms intervals.
 * Pass NULL as parameter.
 */
void safety_task(void *param);

#ifdef __cplusplus
}
#endif
