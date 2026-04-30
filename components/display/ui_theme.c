#include "ui_theme.h"
#include "ui_common.h"
#include "esp_log.h"
#include "lvgl.h"

static const char *TAG = "ui_theme";

static lv_theme_t *s_theme = NULL;

/* Shared static styles. Initialized once on first ui_theme_init(); never freed.
 * Apply targets:
 *   s_screen          → top-level screens (parent == NULL)
 *   s_panel           → plain lv_obj containers (chrome-free div)
 *   s_button*         → lv_button base + focused state
 *   s_list*           → lv_list and lv_list_button + focused state
 *   s_chart*          → lv_chart main/grid/items/indicator parts
 */
static lv_style_t s_screen;
static lv_style_t s_panel;
static lv_style_t s_button;
static lv_style_t s_button_focused;
#if LV_USE_LIST
static lv_style_t s_list;
static lv_style_t s_list_button;
static lv_style_t s_list_button_focused;
#endif
#if LV_USE_CHART
static lv_style_t s_chart;
static lv_style_t s_chart_grid;
static lv_style_t s_chart_items;
static lv_style_t s_chart_indicator;
#endif

static void styles_init(void)
{
    /* Screen baseline. Sets text/font defaults that every descendant inherits. */
    lv_style_init(&s_screen);
    lv_style_set_bg_color(&s_screen, UI_COLOR_BG);
    lv_style_set_bg_opa(&s_screen, LV_OPA_COVER);
    lv_style_set_text_color(&s_screen, UI_COLOR_TEXT);
    lv_style_set_text_font(&s_screen, UI_FONT_SMALL);
    lv_style_set_pad_all(&s_screen, 0);
    lv_style_set_border_width(&s_screen, 0);

    /* Plain container = transparent, borderless, padless. Most lv_obj usages
     * are layout boxes over a screen; instances that want a fill override bg. */
    lv_style_init(&s_panel);
    lv_style_set_bg_opa(&s_panel, LV_OPA_TRANSP);
    lv_style_set_border_width(&s_panel, 0);
    lv_style_set_radius(&s_panel, 0);
    lv_style_set_pad_all(&s_panel, 0);

    /* Button defaults. bg_color is intentionally left to per-instance overrides
     * because Bisque uses bg as a semantic flag (ERROR / HEATING / BUTTON_BG). */
    lv_style_init(&s_button);
    lv_style_set_radius(&s_button, 6);
    lv_style_set_text_color(&s_button, UI_COLOR_TEXT);

    lv_style_init(&s_button_focused);
    lv_style_set_outline_color(&s_button_focused, UI_COLOR_TEXT);
    lv_style_set_outline_width(&s_button_focused, 3);
    lv_style_set_outline_pad(&s_button_focused, 2);

#if LV_USE_LIST
    lv_style_init(&s_list);
    lv_style_set_bg_color(&s_list, UI_COLOR_SURFACE_1);
    lv_style_set_bg_opa(&s_list, LV_OPA_COVER);
    lv_style_set_border_color(&s_list, UI_COLOR_BORDER);
    lv_style_set_border_width(&s_list, 1);
    lv_style_set_radius(&s_list, 4);
    lv_style_set_pad_all(&s_list, 4);

    lv_style_init(&s_list_button);
    lv_style_set_bg_color(&s_list_button, UI_COLOR_SURFACE_2);
    lv_style_set_bg_opa(&s_list_button, LV_OPA_COVER);
    lv_style_set_text_color(&s_list_button, UI_COLOR_TEXT);
    lv_style_set_text_font(&s_list_button, UI_FONT_SMALL);

    lv_style_init(&s_list_button_focused);
    lv_style_set_bg_color(&s_list_button_focused, UI_COLOR_HEATING);
    lv_style_set_text_color(&s_list_button_focused, UI_COLOR_BG);
#endif

#if LV_USE_CHART
    lv_style_init(&s_chart);
    lv_style_set_bg_color(&s_chart, UI_COLOR_SURFACE_1);
    lv_style_set_bg_opa(&s_chart, LV_OPA_COVER);
    lv_style_set_border_color(&s_chart, UI_COLOR_BORDER);
    lv_style_set_border_width(&s_chart, 1);
    lv_style_set_radius(&s_chart, 4);
    lv_style_set_pad_all(&s_chart, 0);

    lv_style_init(&s_chart_grid);
    lv_style_set_line_color(&s_chart_grid, UI_COLOR_BORDER);

    lv_style_init(&s_chart_items);
    lv_style_set_line_width(&s_chart_items, 3);

    /* Hide point markers on chart series. */
    lv_style_init(&s_chart_indicator);
    lv_style_set_width(&s_chart_indicator, 0);
    lv_style_set_height(&s_chart_indicator, 0);
#endif
}

static void apply_cb(lv_theme_t *th, lv_obj_t *obj)
{
    LV_UNUSED(th);

    /* Screen: top-level object with no parent. */
    if (lv_obj_get_parent(obj) == NULL) {
        lv_obj_add_style(obj, &s_screen, 0);
        return;
    }

    if (lv_obj_check_type(obj, &lv_obj_class)) {
        lv_obj_add_style(obj, &s_panel, 0);
        return;
    }
#if LV_USE_BUTTON
    if (lv_obj_check_type(obj, &lv_button_class)) {
        lv_obj_add_style(obj, &s_button, 0);
        lv_obj_add_style(obj, &s_button_focused, LV_STATE_FOCUSED);
        return;
    }
#endif
#if LV_USE_LIST
    if (lv_obj_check_type(obj, &lv_list_class)) {
        lv_obj_add_style(obj, &s_list, 0);
        return;
    }
    if (lv_obj_check_type(obj, &lv_list_button_class)) {
        lv_obj_add_style(obj, &s_list_button, 0);
        lv_obj_add_style(obj, &s_list_button_focused, LV_STATE_FOCUSED);
        return;
    }
#endif
#if LV_USE_CHART
    if (lv_obj_check_type(obj, &lv_chart_class)) {
        lv_obj_add_style(obj, &s_chart, 0);
        lv_obj_add_style(obj, &s_chart_grid, LV_PART_MAIN);
        lv_obj_add_style(obj, &s_chart_items, LV_PART_ITEMS);
        lv_obj_add_style(obj, &s_chart_indicator, LV_PART_INDICATOR);
        return;
    }
#endif
    /* lv_label, lv_image, lv_buttonmatrix etc. inherit text/font from the screen
     * style. No explicit theme entry needed yet; add one if a class needs its own
     * defaults later. */
}

void ui_theme_init(lv_display_t *disp)
{
    if (s_theme != NULL) {
        return;
    }
    styles_init();

    s_theme = lv_theme_create();
    if (!s_theme) {
        ESP_LOGE(TAG, "failed to allocate theme");
        return;
    }
    lv_theme_set_apply_cb(s_theme, apply_cb);
    lv_display_set_theme(disp, s_theme);
    ESP_LOGI(TAG, "ui theme installed");
}
