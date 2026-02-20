#pragma once

#include "lvgl.h"
#include "thermocouple.h"

#ifdef __cplusplus
extern "C" {
#endif

lv_obj_t *ui_screen_chart_create(void);
void ui_screen_chart_update(const thermocouple_reading_t *tc);
void ui_screen_chart_set_page_dots(int active_index, int total);

#ifdef __cplusplus
}
#endif
