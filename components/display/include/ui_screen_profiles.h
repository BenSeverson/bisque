#pragma once

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

lv_obj_t *ui_screen_profiles_create(void);
void ui_screen_profiles_refresh(void);
void ui_screen_profiles_set_page_dots(int active_index, int total);

#ifdef __cplusplus
}
#endif
