#include "modal_action_menu.h"
#include "modal.h"
#include "ui_common.h"
#include "firing_engine.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

static const char *TAG = "actions";

#define BTN_W      200
#define BTN_H      60
#define BTN_GAP    16
#define BTN_FIRST_Y 72

static firing_status_t s_status_at_open = FIRING_STATUS_IDLE;

static void send_cmd(firing_cmd_type_t type, const char *desc)
{
    QueueHandle_t q = firing_engine_get_cmd_queue();
    if (!q) {
        ESP_LOGE(TAG, "firing engine command queue not available");
        return;
    }
    firing_cmd_t cmd = {0};
    cmd.type = type;
    if (xQueueSend(q, &cmd, pdMS_TO_TICKS(100)) != pdTRUE) {
        ESP_LOGE(TAG, "failed to queue %s", desc);
    } else {
        ESP_LOGI(TAG, "queued %s", desc);
    }
}

static lv_obj_t *make_label(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text);
    return l;
}

static lv_obj_t *make_button(lv_obj_t *parent, const char *text, lv_color_t bg, lv_color_t fg)
{
    lv_obj_t *btn = lv_button_create(parent);
    lv_obj_set_size(btn, BTN_W, BTN_H);
    lv_obj_set_style_bg_color(btn, bg, 0);
    lv_obj_set_style_radius(btn, 6, 0);
    lv_obj_t *lbl = lv_label_create(btn);
    lv_obj_set_style_text_font(lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(lbl, fg, 0);
    lv_label_set_text(lbl, text);
    lv_obj_center(lbl);
    return btn;
}

/* ── Stop confirm ──────────────────────────────────── */

static void on_stop_confirmed(lv_event_t *e)
{
    (void)e;
    send_cmd(FIRING_CMD_STOP, "STOP");
    dashboard_modal_close_all();
}

static void on_stop_cancelled(lv_event_t *e)
{
    (void)e;
    dashboard_modal_close(); /* pop confirm; action menu remains on stack */
}

static void stop_confirm_builder(lv_obj_t *root, void *ctx)
{
    (void)ctx;

    lv_obj_t *title = make_label(root, UI_FONT_MEDIUM, UI_COLOR_TEXT, "Stop the firing?");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 80);

    lv_obj_t *body = make_label(root, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "Progress will be lost.");
    lv_obj_align(body, LV_ALIGN_TOP_MID, 0, 130);

    lv_obj_t *stop_btn = make_button(root, "Stop", UI_COLOR_ERROR, UI_COLOR_TEXT);
    lv_obj_align(stop_btn, LV_ALIGN_CENTER, -80, 30);
    lv_obj_add_event_cb(stop_btn, on_stop_confirmed, LV_EVENT_CLICKED, NULL);

    lv_obj_t *cancel_btn = make_button(root, "Cancel", UI_COLOR_BUTTON_BG, UI_COLOR_TEXT);
    lv_obj_align(cancel_btn, LV_ALIGN_CENTER, 80, 30);
    lv_obj_add_event_cb(cancel_btn, on_stop_cancelled, LV_EVENT_CLICKED, NULL);

    /* Destructive default — focus Cancel so accidental SELECT presses don't stop the firing. */
    lv_group_focus_obj(cancel_btn);

    lv_obj_t *hint = make_label(root, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT to confirm  |  LEFT to go back");
    lv_obj_align(hint, LV_ALIGN_BOTTOM_MID, 0, -16);
}

/* ── Action menu ───────────────────────────────────── */

static void on_pause_clicked(lv_event_t *e)
{
    (void)e;
    send_cmd(FIRING_CMD_PAUSE, "PAUSE");
    dashboard_modal_close_all();
}

static void on_resume_clicked(lv_event_t *e)
{
    (void)e;
    send_cmd(FIRING_CMD_RESUME, "RESUME");
    dashboard_modal_close_all();
}

static void on_skip_clicked(lv_event_t *e)
{
    (void)e;
    send_cmd(FIRING_CMD_SKIP_SEGMENT, "SKIP_SEGMENT");
    dashboard_modal_close_all();
}

static void on_stop_clicked(lv_event_t *e)
{
    (void)e;
    dashboard_modal_open(stop_confirm_builder, NULL);
}

static void on_autotune_stop_clicked(lv_event_t *e)
{
    (void)e;
    send_cmd(FIRING_CMD_AUTOTUNE_STOP, "AUTOTUNE_STOP");
    dashboard_modal_close_all();
}

static void menu_builder(lv_obj_t *root, void *ctx)
{
    (void)ctx;

    lv_obj_t *title = make_label(root, UI_FONT_MEDIUM, UI_COLOR_TEXT, "Actions");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 16);

    lv_obj_t *first_btn = NULL;
    int y = BTN_FIRST_Y;

    if (s_status_at_open == FIRING_STATUS_AUTOTUNE) {
        lv_obj_t *btn = make_button(root, "Stop Autotune", UI_COLOR_ERROR, UI_COLOR_TEXT);
        lv_obj_align(btn, LV_ALIGN_TOP_MID, 0, y);
        lv_obj_add_event_cb(btn, on_autotune_stop_clicked, LV_EVENT_CLICKED, NULL);
        first_btn = btn;
    } else {
        if (s_status_at_open == FIRING_STATUS_PAUSED) {
            lv_obj_t *btn = make_button(root, "Resume", UI_COLOR_HEATING, UI_COLOR_BG);
            lv_obj_align(btn, LV_ALIGN_TOP_MID, 0, y);
            lv_obj_add_event_cb(btn, on_resume_clicked, LV_EVENT_CLICKED, NULL);
            first_btn = btn;
        } else {
            lv_obj_t *btn = make_button(root, "Pause", UI_COLOR_BUTTON_BG, UI_COLOR_TEXT);
            lv_obj_align(btn, LV_ALIGN_TOP_MID, 0, y);
            lv_obj_add_event_cb(btn, on_pause_clicked, LV_EVENT_CLICKED, NULL);
            first_btn = btn;
        }
        y += BTN_H + BTN_GAP;

        lv_obj_t *skip = make_button(root, "Skip Segment", UI_COLOR_BUTTON_BG, UI_COLOR_TEXT);
        lv_obj_align(skip, LV_ALIGN_TOP_MID, 0, y);
        lv_obj_add_event_cb(skip, on_skip_clicked, LV_EVENT_CLICKED, NULL);
        y += BTN_H + BTN_GAP;

        lv_obj_t *stop = make_button(root, "Stop", UI_COLOR_ERROR, UI_COLOR_TEXT);
        lv_obj_align(stop, LV_ALIGN_TOP_MID, 0, y);
        lv_obj_add_event_cb(stop, on_stop_clicked, LV_EVENT_CLICKED, NULL);
    }

    if (first_btn) {
        lv_group_focus_obj(first_btn);
    }

    lv_obj_t *hint = make_label(root, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT to choose  |  LEFT to cancel");
    lv_obj_align(hint, LV_ALIGN_BOTTOM_MID, 0, -16);
}

/* ── Public API ────────────────────────────────────── */

void modal_action_menu_open(firing_status_t status_at_open)
{
    s_status_at_open = status_at_open;
    dashboard_modal_open(menu_builder, NULL);
}
