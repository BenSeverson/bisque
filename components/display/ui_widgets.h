#pragma once

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Convenience constructors built on top of the Bisque LVGL theme. Themed
 * widget defaults (font, text color, button focus ring, list-row colors, chart
 * frame) come from the theme — these helpers add the small per-instance
 * settings that don't generalize: explicit font/color overrides, button size
 * and bg color, separator dimensions. */

/* Label with explicit font + color override. Pass UI_FONT_* and UI_COLOR_*
 * tokens. The theme already provides UI_FONT_SMALL + UI_COLOR_TEXT inherited
 * from the screen, so a default label with those values doesn't strictly need
 * this helper — but using it keeps call sites uniform. */
lv_obj_t *ui_make_label(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text);

/* Button with centered child label. bg/fg are per-instance because Bisque
 * uses bg as a semantic color (ERROR / HEATING / BUTTON_BG). The focus
 * outline is provided automatically by the theme. */
lv_obj_t *ui_make_button(lv_obj_t *parent, int32_t w, int32_t h, const char *text, lv_color_t bg, lv_color_t fg);

/* 1px horizontal hairline filled with UI_COLOR_BORDER. */
lv_obj_t *ui_make_separator(lv_obj_t *parent, int32_t w);

#ifdef __cplusplus
}
#endif
