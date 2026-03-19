#include "ui_screen_home.h"
#include "ui_common.h"
#include "esp_log.h"
#include <stdio.h>
#include <inttypes.h>

/* Screen widgets */
static lv_obj_t *s_screen     = NULL;
static lv_obj_t *s_status_bar = NULL;
static lv_obj_t *s_status_lbl = NULL;
static lv_obj_t *s_temp_lbl   = NULL;
static lv_obj_t *s_target_lbl = NULL;
static lv_obj_t *s_seg_lbl    = NULL;
static lv_obj_t *s_time_lbl   = NULL;
static lv_obj_t *s_dots[UI_SCREEN_COUNT];

lv_obj_t *ui_screen_home_create(void)
{
    s_screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_screen, UI_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(s_screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(s_screen, LV_OBJ_FLAG_SCROLLABLE);

    /* Status bar (top 40px) */
    s_status_bar = lv_obj_create(s_screen);
    lv_obj_set_size(s_status_bar, UI_LCD_W, 40);
    lv_obj_set_pos(s_status_bar, 0, 0);
    lv_obj_set_style_bg_color(s_status_bar, UI_COLOR_IDLE, 0);
    lv_obj_set_style_bg_opa(s_status_bar, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(s_status_bar, 0, 0);
    lv_obj_set_style_border_width(s_status_bar, 0, 0);
    lv_obj_set_style_pad_all(s_status_bar, 0, 0);
    lv_obj_clear_flag(s_status_bar, LV_OBJ_FLAG_SCROLLABLE);

    s_status_lbl = lv_label_create(s_status_bar);
    lv_obj_set_style_text_font(s_status_lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(s_status_lbl, UI_COLOR_BG, 0);
    lv_label_set_text(s_status_lbl, "IDLE");
    lv_obj_center(s_status_lbl);

    /* Big temperature (centered) */
    s_temp_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_temp_lbl, UI_FONT_BIG, 0);
    lv_obj_set_style_text_color(s_temp_lbl, UI_COLOR_TEXT, 0);
    lv_label_set_text(s_temp_lbl, "---°");
    lv_obj_align(s_temp_lbl, LV_ALIGN_TOP_MID, 0, 60);

    /* Target temperature */
    s_target_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_target_lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(s_target_lbl, UI_COLOR_TEXT_DIM, 0);
    lv_label_set_text(s_target_lbl, "");
    lv_obj_align(s_target_lbl, LV_ALIGN_TOP_MID, 0, 130);

    /* Segment progress */
    s_seg_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_seg_lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(s_seg_lbl, UI_COLOR_TEXT_DIM, 0);
    lv_label_set_text(s_seg_lbl, "");
    lv_obj_align(s_seg_lbl, LV_ALIGN_TOP_MID, 0, 170);

    /* Elapsed time */
    s_time_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_time_lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(s_time_lbl, UI_COLOR_TEXT_DIM, 0);
    lv_label_set_text(s_time_lbl, "");
    lv_obj_align(s_time_lbl, LV_ALIGN_TOP_MID, 0, 210);

    /* Page dots (bottom) */
    int dot_total_w = UI_SCREEN_COUNT * 14 + (UI_SCREEN_COUNT - 1) * 10;
    int dot_x_start = (UI_LCD_W - dot_total_w) / 2;
    for (int i = 0; i < UI_SCREEN_COUNT; i++) {
        s_dots[i] = lv_obj_create(s_screen);
        lv_obj_set_size(s_dots[i], 12, 12);
        lv_obj_set_pos(s_dots[i], dot_x_start + i * 24, UI_LCD_H - 22);
        lv_obj_set_style_radius(s_dots[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(s_dots[i], 0, 0);
        lv_obj_set_style_bg_color(s_dots[i], UI_COLOR_DOT_INACTIVE, 0);
        lv_obj_set_style_bg_opa(s_dots[i], LV_OPA_COVER, 0);
        lv_obj_clear_flag(s_dots[i], LV_OBJ_FLAG_SCROLLABLE);
    }

    return s_screen;
}

void ui_screen_home_update(const thermocouple_reading_t *tc, const firing_progress_t *prog)
{
    if (!s_screen) return;
    char buf[32];

    /* Status bar */
    lv_obj_set_style_bg_color(s_status_bar, ui_status_color(prog->status), 0);
    lv_label_set_text(s_status_lbl, ui_status_label(prog->status));

    /* Temperature */
    float temp = tc->fault ? 0 : tc->temperature_c;
    snprintf(buf, sizeof(buf), "%.0f°", temp);
    lv_label_set_text(s_temp_lbl, buf);
    lv_obj_align(s_temp_lbl, LV_ALIGN_TOP_MID, 0, 60);

    /* Target */
    if (prog->is_active) {
        snprintf(buf, sizeof(buf), LV_SYMBOL_RIGHT " %.0f°C", prog->target_temp);
        lv_label_set_text(s_target_lbl, buf);
    } else {
        lv_label_set_text(s_target_lbl, "");
    }
    lv_obj_align(s_target_lbl, LV_ALIGN_TOP_MID, 0, 130);

    /* Segment */
    if (prog->is_active && prog->total_segments > 0) {
        snprintf(buf, sizeof(buf), "Seg %d/%d", prog->current_segment + 1, prog->total_segments);
        lv_label_set_text(s_seg_lbl, buf);
    } else {
        lv_label_set_text(s_seg_lbl, "");
    }
    lv_obj_align(s_seg_lbl, LV_ALIGN_TOP_MID, 0, 170);

    /* Elapsed time */
    if (prog->is_active) {
        uint32_t h = prog->elapsed_time / 3600;
        uint32_t m = (prog->elapsed_time % 3600) / 60;
        snprintf(buf, sizeof(buf), "%" PRIu32 "h %" PRIu32 "m", h, m);
        lv_label_set_text(s_time_lbl, buf);
    } else {
        lv_label_set_text(s_time_lbl, "");
    }
    lv_obj_align(s_time_lbl, LV_ALIGN_TOP_MID, 0, 210);
}

void ui_screen_home_set_page_dots(int active_index, int total)
{
    (void)total;
    if (!s_screen) return;
    for (int i = 0; i < UI_SCREEN_COUNT; i++) {
        lv_color_t c = (i == active_index) ? UI_COLOR_DOT_ACTIVE : UI_COLOR_DOT_INACTIVE;
        lv_obj_set_style_bg_color(s_dots[i], c, 0);
    }
}
