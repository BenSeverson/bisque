#include "ui_screen_chart.h"
#include "ui_common.h"
#include <stdio.h>

#define CHART_POINTS 120

static lv_obj_t *s_screen    = NULL;
static lv_obj_t *s_temp_lbl  = NULL;
static lv_obj_t *s_chart     = NULL;
static lv_chart_series_t *s_series = NULL;
static lv_obj_t *s_dots[UI_SCREEN_COUNT];

lv_obj_t *ui_screen_chart_create(void)
{
    s_screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_screen, UI_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(s_screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(s_screen, LV_OBJ_FLAG_SCROLLABLE);

    /* Current temp label at top */
    s_temp_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_temp_lbl, UI_FONT_MEDIUM, 0);
    lv_obj_set_style_text_color(s_temp_lbl, UI_COLOR_TEXT, 0);
    lv_label_set_text(s_temp_lbl, "---°C");
    lv_obj_align(s_temp_lbl, LV_ALIGN_TOP_LEFT, 12, 8);

    /* Chart */
    s_chart = lv_chart_create(s_screen);
    lv_obj_set_size(s_chart, 456, 240);
    lv_obj_align(s_chart, LV_ALIGN_TOP_MID, 0, 48);
    lv_chart_set_type(s_chart, LV_CHART_TYPE_LINE);
    lv_chart_set_point_count(s_chart, CHART_POINTS);
    lv_chart_set_range(s_chart, LV_CHART_AXIS_PRIMARY_Y, 0, 1400);

    /* Style the chart */
    lv_obj_set_style_bg_color(s_chart, UI_COLOR_SURFACE_1, 0);
    lv_obj_set_style_bg_opa(s_chart, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(s_chart, UI_COLOR_BORDER, 0);
    lv_obj_set_style_border_width(s_chart, 2, 0);
    lv_obj_set_style_radius(s_chart, 4, 0);
    lv_obj_set_style_line_width(s_chart, 3, LV_PART_ITEMS);
    lv_obj_set_style_size(s_chart, 0, 0, LV_PART_INDICATOR);  /* hide data point dots */

    /* Chart grid lines */
    lv_chart_set_div_line_count(s_chart, 5, 4);  /* 5 horizontal, 4 vertical divisions */
    lv_obj_set_style_line_color(s_chart, UI_COLOR_BORDER, LV_PART_MAIN);

    /* Temperature series */
    s_series = lv_chart_add_series(s_chart, UI_COLOR_HEATING, LV_CHART_AXIS_PRIMARY_Y);

    /* Initialize all points to 0 */
    for (int i = 0; i < CHART_POINTS; i++) {
        lv_chart_set_next_value(s_chart, s_series, 0);
    }

    /* Page dots */
    ui_create_page_dots(s_screen, s_dots, UI_SCREEN_COUNT);

    return s_screen;
}

void ui_screen_chart_update(const thermocouple_reading_t *tc)
{
    if (!s_screen) return;
    char buf[16];

    float temp = tc->fault ? 0 : tc->temperature_c;

    snprintf(buf, sizeof(buf), "%.0f°C", temp);
    lv_label_set_text(s_temp_lbl, buf);

    lv_chart_set_next_value(s_chart, s_series, (int32_t)temp);
}

void ui_screen_chart_set_page_dots(int active_index, int total)
{
    (void)total;
    if (!s_screen) return;
    ui_update_page_dots(s_dots, UI_SCREEN_COUNT, active_index);
}
