#include "ui_widgets.h"
#include "ui_common.h"

lv_obj_t *ui_make_label(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text);
    return l;
}

lv_obj_t *ui_make_button(lv_obj_t *parent, int32_t w, int32_t h, const char *text, lv_color_t bg, lv_color_t fg)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_size(btn, w, h);
    lv_obj_set_style_bg_color(btn, bg, 0);
    lv_obj_t *lbl = lv_label_create(btn);
    lv_obj_set_style_text_font(lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(lbl, fg, 0);
    lv_label_set_text(lbl, text);
    lv_obj_center(lbl);
    return btn;
}

lv_obj_t *ui_make_separator(lv_obj_t *parent, int32_t w)
{
    lv_obj_t *sep = lv_obj_create(parent);
    lv_obj_set_size(sep, w, 1);
    lv_obj_set_style_bg_color(sep, UI_COLOR_BORDER, 0);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    return sep;
}
