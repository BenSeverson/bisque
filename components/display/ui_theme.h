#pragma once

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Install the Bisque LVGL theme on the given display. Must be called once,
 * after lv_display_create() and before any widget creation. Idempotent. */
void ui_theme_init(lv_display_t *disp);

#ifdef __cplusplus
}
#endif
