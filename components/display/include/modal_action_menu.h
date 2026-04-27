#pragma once

#include "firing_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Open the action-menu modal for an active firing. The set of buttons depends on
 * `status_at_open`:
 *   HEATING / HOLDING / COOLING → [Pause] [Skip Segment] [Stop]
 *   PAUSED                      → [Resume] [Skip Segment] [Stop]
 *   AUTOTUNE                    → [Stop Autotune]
 *
 * Pause / Resume / Skip / Stop-Autotune dispatch their command directly and
 * close the modal stack. Stop pushes a confirmation modal first.
 *
 * Must be called with the LVGL mutex held.
 */
void modal_action_menu_open(firing_status_t status_at_open);

#ifdef __cplusplus
}
#endif
