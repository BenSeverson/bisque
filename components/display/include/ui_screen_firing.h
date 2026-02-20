#pragma once

#include "lvgl.h"
#include "firing_types.h"
#include "thermocouple.h"

#ifdef __cplusplus
extern "C" {
#endif

lv_obj_t *ui_screen_firing_create(void);
void ui_screen_firing_update(const thermocouple_reading_t *tc, const firing_progress_t *prog);
void ui_screen_firing_set_page_dots(int active_index, int total);

#ifdef __cplusplus
}
#endif
