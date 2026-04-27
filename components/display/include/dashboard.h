#pragma once

#include "lvgl.h"
#include "thermocouple.h"
#include "firing_types.h"

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
 * Must be called with LVGL locked via lv_lock().
 */
void dashboard_update(const thermocouple_reading_t *tc, const firing_progress_t *prog);

#ifdef __cplusplus
}
#endif
