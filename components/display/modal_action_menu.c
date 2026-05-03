#include "modal_action_menu.h"
#include "modal.h"
#include "ui_common.h"
#include "ui_widgets.h"
#include "firing_engine.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

static const char *TAG = "actions";

#define BTN_W       200
#define BTN_H       44
#define BTN_GAP     12
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

static lv_obj_t *make_button(lv_obj_t *parent, const char *text, lv_color_t bg, lv_color_t fg)
{
    return ui_make_button(parent, BTN_W, BTN_H, text, bg, fg);
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

    lv_obj_t *title = ui_make_label(root, UI_FONT_MEDIUM, UI_COLOR_TEXT, "Stop the firing?");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 80);

    lv_obj_t *body = ui_make_label(root, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "Progress will be lost.");
    lv_obj_align(body, LV_ALIGN_TOP_MID, 0, 130);

    /* 140-wide confirm buttons sit side-by-side at +/-80 with a 20px gap; the
     * 200-wide menu-list size (BTN_W) would overlap at this offset. */
    lv_obj_t *stop_btn = ui_make_button(root, 140, 60, "Stop", UI_COLOR_ERROR, lv_color_white());
    lv_obj_align(stop_btn, LV_ALIGN_CENTER, -80, 30);
    lv_obj_add_event_cb(stop_btn, on_stop_confirmed, LV_EVENT_CLICKED, NULL);

    lv_obj_t *cancel_btn = ui_make_button(root, 140, 60, "Cancel", UI_COLOR_BUTTON_BG, UI_COLOR_TEXT);
    lv_obj_align(cancel_btn, LV_ALIGN_CENTER, 80, 30);
    lv_obj_add_event_cb(cancel_btn, on_stop_cancelled, LV_EVENT_CLICKED, NULL);

    /* Destructive default — focus Cancel so accidental SELECT presses don't stop the firing. */
    lv_group_focus_obj(cancel_btn);
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

static void on_menu_cancel_clicked(lv_event_t *e)
{
    (void)e;
    dashboard_modal_close();
}

static void menu_builder(lv_obj_t *root, void *ctx)
{
    (void)ctx;

    lv_obj_t *title = ui_make_label(root, UI_FONT_MEDIUM, UI_COLOR_TEXT, "Actions");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 16);

    lv_obj_t *first_btn = NULL;
    int y = BTN_FIRST_Y;

    if (s_status_at_open == FIRING_STATUS_AUTOTUNE) {
        lv_obj_t *btn = make_button(root, "Stop Autotune", UI_COLOR_ERROR, lv_color_white());
        lv_obj_align(btn, LV_ALIGN_TOP_MID, 0, y);
        lv_obj_add_event_cb(btn, on_autotune_stop_clicked, LV_EVENT_CLICKED, NULL);
        first_btn = btn;
        y += BTN_H + BTN_GAP;
    } else {
        if (s_status_at_open == FIRING_STATUS_PAUSED) {
            lv_obj_t *btn = make_button(root, "Resume", UI_COLOR_HEATING, UI_COLOR_ON_ACCENT);
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

        lv_obj_t *stop = make_button(root, "Stop", UI_COLOR_ERROR, lv_color_white());
        lv_obj_align(stop, LV_ALIGN_TOP_MID, 0, y);
        lv_obj_add_event_cb(stop, on_stop_clicked, LV_EVENT_CLICKED, NULL);
        y += BTN_H + BTN_GAP;
    }

    lv_obj_t *cancel = make_button(root, "Cancel", UI_COLOR_BUTTON_BG, UI_COLOR_TEXT);
    lv_obj_align(cancel, LV_ALIGN_TOP_MID, 0, y);
    lv_obj_add_event_cb(cancel, on_menu_cancel_clicked, LV_EVENT_CLICKED, NULL);

    if (first_btn) {
        lv_group_focus_obj(first_btn);
    }
}

/* ── Public API ────────────────────────────────────── */

void modal_action_menu_open(firing_status_t status_at_open)
{
    s_status_at_open = status_at_open;
    dashboard_modal_open(menu_builder, NULL);
}
