#pragma once

#include "lvgl.h"
#include "thermocouple.h"
#include "firing_types.h"
#include "vent_state.h"
#include "lid_state.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Create the dashboard screen and load it as the active screen.
 * Must be called with LVGL locked via lv_lock().
 */
void dashboard_create(void);

/**
 * Refresh the dashboard from the latest thermocouple reading and firing progress.
 * Layout swaps based on prog->status.
 *
 * `vent` is the downdraft vent relay (safety_get_vent_state()), passed in rather
 * than read here so this file stays free of the safety driver — the SDL
 * simulator compiles it with no ESP-IDF at all, and gets to drive the indicator
 * through states a real kiln would take hours to reach.
 *
 * `lid` is the lid interlock switch (safety_get_lid_state()), passed in for the
 * same reason.
 *
 * Must be called with LVGL locked via lv_lock().
 */
void dashboard_update(const thermocouple_reading_t *tc, const firing_progress_t *prog, vent_state_t vent,
                      lid_state_t lid);

#ifdef __cplusplus
}
#endif
