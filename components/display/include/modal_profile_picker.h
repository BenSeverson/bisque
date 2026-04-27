#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Open the profile-picker modal. Loads all profiles from NVS, presents them
 * as a focusable list, and on SELECT pushes a confirmation modal showing the
 * profile's max temp and estimated duration. Confirming dispatches a
 * FIRING_CMD_START to the firing engine.
 *
 * No-op if no profiles exist.
 *
 * Must be called with the LVGL mutex held.
 */
void modal_profile_picker_open(void);

#ifdef __cplusplus
}
#endif
