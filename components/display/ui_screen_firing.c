#include "ui_screen_firing.h"
#include "ui_common.h"
#include "firing_engine.h"
#include "esp_log.h"
#include <stdio.h>
#include <inttypes.h>

static const char *TAG = "ui_firing";

static lv_obj_t *s_screen = NULL;
static lv_obj_t *s_temp_lbl = NULL;
static lv_obj_t *s_status_lbl = NULL;
static lv_obj_t *s_seg_lbl = NULL;
static lv_obj_t *s_btnm = NULL;
static lv_obj_t *s_dots[UI_SCREEN_COUNT];

/* Button map variations */
static const char *s_map_idle[] = {"Start", ""};
static const char *s_map_active[] = {"Pause", "Stop", ""};
static const char *s_map_paused[] = {"Resume", "Stop", ""};

static firing_status_t s_last_status = FIRING_STATUS_IDLE;

static void btnm_cb(lv_event_t *e)
{
    lv_obj_t *obj = lv_event_get_target(e);
    uint32_t idx = lv_buttonmatrix_get_selected_button(obj);
    if (idx == LV_BUTTONMATRIX_BUTTON_NONE) {
        return;
    }

    firing_cmd_t cmd = {0};

    switch (s_last_status) {
    case FIRING_STATUS_IDLE:
    case FIRING_STATUS_COMPLETE:
    case FIRING_STATUS_ERROR:
        /* "Start" — switch to profiles screen instead */
        ESP_LOGI(TAG, "Start pressed — navigate to profiles");
        /* We can't easily switch screens from here; the user should use profiles screen.
           For now just log it. In practice, long-press to profiles screen. */
        return;

    case FIRING_STATUS_HEATING:
    case FIRING_STATUS_HOLDING:
    case FIRING_STATUS_COOLING:
        if (idx == 0) {
            cmd.type = FIRING_CMD_PAUSE;
        } else {
            cmd.type = FIRING_CMD_STOP;
        }
        break;

    case FIRING_STATUS_PAUSED:
        if (idx == 0) {
            cmd.type = FIRING_CMD_RESUME;
        } else {
            cmd.type = FIRING_CMD_STOP;
        }
        break;

    default:
        return;
    }

    QueueHandle_t q = firing_engine_get_cmd_queue();
    if (xQueueSend(q, &cmd, pdMS_TO_TICKS(100)) == pdTRUE) {
        ESP_LOGI(TAG, "Sent firing command type=%d", cmd.type);
    }
}

lv_obj_t *ui_screen_firing_create(void)
{
    s_screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_screen, UI_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(s_screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(s_screen, LV_OBJ_FLAG_SCROLLABLE);

    /* Temperature + status line */
    s_temp_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_temp_lbl, UI_FONT_MEDIUM, 0);
    lv_obj_set_style_text_color(s_temp_lbl, UI_COLOR_TEXT, 0);
    lv_label_set_text(s_temp_lbl, "---°C IDLE");
    lv_obj_align(s_temp_lbl, LV_ALIGN_TOP_LEFT, 12, 8);

    /* Status label (segment + time) */
    s_status_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_status_lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(s_status_lbl, UI_COLOR_TEXT_DIM, 0);
    lv_label_set_text(s_status_lbl, "");
    lv_obj_align(s_status_lbl, LV_ALIGN_TOP_LEFT, 12, 52);

    /* Segment info */
    s_seg_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_seg_lbl, UI_FONT_SMALL, 0);
    lv_obj_set_style_text_color(s_seg_lbl, UI_COLOR_TEXT_DIM, 0);
    lv_label_set_text(s_seg_lbl, "");
    lv_obj_align(s_seg_lbl, LV_ALIGN_TOP_LEFT, 12, 86);

    /* Button matrix */
    s_btnm = lv_buttonmatrix_create(s_screen);
    lv_obj_set_size(s_btnm, 440, 80);
    lv_obj_align(s_btnm, LV_ALIGN_CENTER, 0, 30);
    lv_buttonmatrix_set_map(s_btnm, s_map_idle);
    lv_obj_set_style_text_font(s_btnm, UI_FONT_SMALL, 0);
    lv_obj_set_style_bg_color(s_btnm, UI_COLOR_SURFACE_2, 0);
    lv_obj_set_style_bg_color(s_btnm, UI_COLOR_BUTTON_BG, LV_PART_ITEMS);
    lv_obj_set_style_bg_opa(s_btnm, LV_OPA_COVER, LV_PART_ITEMS);
    lv_obj_set_style_text_color(s_btnm, UI_COLOR_TEXT, LV_PART_ITEMS);
    lv_obj_set_style_border_width(s_btnm, 0, 0);
    lv_obj_add_event_cb(s_btnm, btnm_cb, LV_EVENT_VALUE_CHANGED, NULL);
    lv_group_add_obj(lv_group_get_default(), s_btnm);

    /* Page dots */
    ui_create_page_dots(s_screen, s_dots, UI_SCREEN_COUNT);

    return s_screen;
}

void ui_screen_firing_update(const thermocouple_reading_t *tc, const firing_progress_t *prog)
{
    if (!s_screen) {
        return;
    }
    char buf[48];

    float temp = tc->fault ? 0 : tc->temperature_c;

    /* Temperature + status */
    snprintf(buf, sizeof(buf), "%.0f°C %s", temp, ui_status_label(prog->status));
    lv_label_set_text(s_temp_lbl, buf);

    /* Segment + time */
    if (prog->is_active && prog->total_segments > 0) {
        uint32_t h = prog->elapsed_time / 3600;
        uint32_t m = (prog->elapsed_time % 3600) / 60;
        snprintf(buf, sizeof(buf), "Seg %d/%d  %" PRIu32 "h%" PRIu32 "m", prog->current_segment + 1,
                 prog->total_segments, h, m);
        lv_label_set_text(s_status_lbl, buf);

        snprintf(buf, sizeof(buf), LV_SYMBOL_RIGHT " %.0f°C", prog->target_temp);
        lv_label_set_text(s_seg_lbl, buf);
    } else {
        lv_label_set_text(s_status_lbl, "");
        lv_label_set_text(s_seg_lbl, "");
    }

    /* Update button map if status changed */
    if (prog->status != s_last_status) {
        s_last_status = prog->status;
        switch (prog->status) {
        case FIRING_STATUS_HEATING:
        case FIRING_STATUS_HOLDING:
        case FIRING_STATUS_COOLING:
            lv_buttonmatrix_set_map(s_btnm, s_map_active);
            break;
        case FIRING_STATUS_PAUSED:
            lv_buttonmatrix_set_map(s_btnm, s_map_paused);
            break;
        default:
            lv_buttonmatrix_set_map(s_btnm, s_map_idle);
            break;
        }
    }
}

void ui_screen_firing_set_page_dots(int active_index, int total)
{
    (void)total;
    if (!s_screen) {
        return;
    }
    ui_update_page_dots(s_dots, UI_SCREEN_COUNT, active_index);
}
