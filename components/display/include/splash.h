#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/* Boot-time splash screen.
 *
 * Renders a light-theme branded screen (flame icon + "Bisque" wordmark +
 * subtitle + status line + version) on the active LVGL screen. Lives only
 * for the duration of boot, then is destroyed when display_task transitions
 * to the dashboard.
 *
 * All three calls must be made with the LVGL lock held (lv_lock()). */

void splash_create(void);
void splash_set_status(const char *text);
void splash_destroy(void);

#ifdef __cplusplus
}
#endif
