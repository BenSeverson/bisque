#include "modal_profile_picker.h"
#include "modal.h"
#include "ui_common.h"
#include "firing_engine.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <stdint.h>
#include <stdio.h>

static const char *TAG = "picker";

/* IDs only. Full profile is loaded from NVS on demand (per row when building the
 * list, and once when the user picks). This keeps BSS small enough that
 * display_task's 16 KiB stack still fits in internal RAM. */
static char s_profile_ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
static int s_profile_count = 0;

/* The profile the user picked, used by the confirm builder and the START cmd. */
static firing_profile_t s_selected_profile;
static bool s_selected_valid = false;

static void confirm_builder(lv_obj_t *root, void *ctx);
static void picker_builder(lv_obj_t *root, void *ctx);

/* ── Helpers ───────────────────────────────────────── */

static void format_duration_minutes(uint32_t total_minutes, char *buf, size_t buf_size)
{
    unsigned h = (unsigned)(total_minutes / 60u);
    unsigned m = (unsigned)(total_minutes % 60u);
    if (h > 0) {
        snprintf(buf, buf_size, "%uh %02um", h, m);
    } else {
        snprintf(buf, buf_size, "%um", m);
    }
}

static lv_obj_t *make_modal_label(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text);
    return l;
}

static lv_obj_t *make_modal_button(lv_obj_t *parent, const char *text, lv_color_t bg, lv_color_t fg)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_size(btn, 140, 60);
    lv_obj_set_style_bg_color(btn, bg, 0);
    lv_obj_set_style_radius(btn, 6, 0);
    lv_obj_t *lbl = lv_label_create(btn);
    lv_obj_set_style_text_font(lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(lbl, fg, 0);
    lv_label_set_text(lbl, text);
    lv_obj_center(lbl);
    return btn;
}

/* ── Confirm modal ─────────────────────────────────── */

static void on_start_clicked(lv_event_t *e)
{
    (void)e;
    if (!s_selected_valid) {
        dashboard_modal_close_all();
        return;
    }

    QueueHandle_t q = firing_engine_get_cmd_queue();
    if (q) {
        firing_cmd_t cmd = {0};
        cmd.type = FIRING_CMD_START;
        cmd.start.profile = s_selected_profile;
        cmd.start.delay_minutes = 0;
        if (xQueueSend(q, &cmd, pdMS_TO_TICKS(100)) != pdTRUE) {
            ESP_LOGE(TAG, "failed to queue START for profile '%s'", s_selected_profile.id);
        } else {
            ESP_LOGI(TAG, "queued START for profile '%s'", s_selected_profile.id);
        }
    } else {
        ESP_LOGE(TAG, "firing engine command queue not available");
    }

    dashboard_modal_close_all();
}

static void on_cancel_clicked(lv_event_t *e)
{
    (void)e;
    dashboard_modal_close(); /* pop confirm; picker remains on stack */
}

static void confirm_builder(lv_obj_t *root, void *ctx)
{
    (void)ctx;
    if (!s_selected_valid) {
        return;
    }

    char buf[160];
    snprintf(buf, sizeof(buf), "Start %s?", s_selected_profile.name);
    lv_obj_t *title = make_modal_label(root, UI_FONT_MEDIUM, UI_COLOR_TEXT, buf);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 60);

    char dur_buf[24];
    format_duration_minutes(s_selected_profile.estimated_duration, dur_buf, sizeof(dur_buf));
    snprintf(buf, sizeof(buf), "Max %.0f°C   ~%s   %u segments", (double)s_selected_profile.max_temp, dur_buf,
             (unsigned)s_selected_profile.segment_count);
    lv_obj_t *details = make_modal_label(root, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, buf);
    lv_obj_align(details, LV_ALIGN_TOP_MID, 0, 130);

    lv_obj_t *start_btn = make_modal_button(root, "Start", UI_COLOR_HEATING, UI_COLOR_BG);
    lv_obj_align(start_btn, LV_ALIGN_CENTER, -80, 30);
    lv_obj_add_event_cb(start_btn, on_start_clicked, LV_EVENT_CLICKED, NULL);

    lv_obj_t *cancel_btn = make_modal_button(root, "Cancel", UI_COLOR_BUTTON_BG, UI_COLOR_TEXT);
    lv_obj_align(cancel_btn, LV_ALIGN_CENTER, 80, 30);
    lv_obj_add_event_cb(cancel_btn, on_cancel_clicked, LV_EVENT_CLICKED, NULL);

    lv_group_focus_obj(start_btn);

    lv_obj_t *hint = make_modal_label(root, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT to confirm  |  LEFT to go back");
    lv_obj_align(hint, LV_ALIGN_BOTTOM_MID, 0, -16);
}

/* ── Picker modal ──────────────────────────────────── */

static void on_profile_clicked(lv_event_t *e)
{
    const char *id = (const char *)lv_event_get_user_data(e);
    if (!id || id[0] == '\0') {
        return;
    }
    if (firing_engine_load_profile(id, &s_selected_profile) != ESP_OK) {
        ESP_LOGW(TAG, "could not load profile '%s'", id);
        return;
    }
    s_selected_valid = true;
    dashboard_modal_open(confirm_builder, NULL);
}

static void picker_builder(lv_obj_t *root, void *ctx)
{
    (void)ctx;

    lv_obj_t *title = make_modal_label(root, UI_FONT_MEDIUM, UI_COLOR_TEXT, "Select a profile");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 16);

    lv_obj_t *list = lv_list_create(root);
    lv_obj_set_size(list, UI_LCD_W - 32, UI_LCD_H - 130);
    lv_obj_align(list, LV_ALIGN_TOP_MID, 0, 60);
    lv_obj_set_style_bg_color(list, UI_COLOR_SURFACE_1, 0);
    lv_obj_set_style_bg_opa(list, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(list, UI_COLOR_BORDER, 0);
    lv_obj_set_style_border_width(list, 1, 0);
    lv_obj_set_style_radius(list, 4, 0);
    lv_obj_set_style_pad_all(list, 4, 0);

    for (int i = 0; i < s_profile_count; i++) {
        firing_profile_t p;
        if (firing_engine_load_profile(s_profile_ids[i], &p) != ESP_OK) {
            continue;
        }
        char dur_buf[24];
        format_duration_minutes(p.estimated_duration, dur_buf, sizeof(dur_buf));
        char label[128];
        snprintf(label, sizeof(label), "%s   |   %.0f°C   |   ~%s", p.name, (double)p.max_temp, dur_buf);
        lv_obj_t *btn = lv_list_add_button(list, NULL, label);
        lv_obj_set_style_bg_color(btn, UI_COLOR_SURFACE_2, 0);
        lv_obj_set_style_text_color(btn, UI_COLOR_TEXT, 0);
        lv_obj_set_style_text_font(btn, UI_FONT_SMALL, 0);
        /* user_data points into s_profile_ids, which has static lifetime — safe to dereference later. */
        lv_obj_add_event_cb(btn, on_profile_clicked, LV_EVENT_CLICKED, s_profile_ids[i]);
    }

    lv_obj_t *hint = make_modal_label(root, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT to choose  |  LEFT to cancel");
    lv_obj_align(hint, LV_ALIGN_BOTTOM_MID, 0, -16);
}

/* ── Public API ────────────────────────────────────── */

void modal_profile_picker_open(void)
{
    s_selected_valid = false;
    s_profile_count = firing_engine_list_profiles(s_profile_ids, FIRING_MAX_PROFILES);
    if (s_profile_count == 0) {
        ESP_LOGW(TAG, "no profiles available; nothing to pick");
        return;
    }
    dashboard_modal_open(picker_builder, NULL);
}
