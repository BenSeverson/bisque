#include "ui_screen_profiles.h"
#include "ui_common.h"
#include "firing_engine.h"
#include "firing_types.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "ui_profiles";

static lv_obj_t *s_screen = NULL;
static lv_obj_t *s_title_lbl = NULL;
static lv_obj_t *s_list = NULL;
static lv_obj_t *s_dots[UI_SCREEN_COUNT];

/* Store profile IDs for launching */
static char s_profile_ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
static int s_profile_count = 0;

static void profile_btn_cb(lv_event_t *e)
{
    int idx = (int)(intptr_t)lv_event_get_user_data(e);
    if (idx < 0 || idx >= s_profile_count)
        return;

    firing_profile_t profile;
    esp_err_t ret = firing_engine_load_profile(s_profile_ids[idx], &profile);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Failed to load profile %s", s_profile_ids[idx]);
        return;
    }

    /* Send start command to firing engine */
    firing_cmd_t cmd = {
        .type = FIRING_CMD_START,
        .start =
            {
                .profile = profile,
                .delay_minutes = 0,
            },
    };

    QueueHandle_t q = firing_engine_get_cmd_queue();
    if (xQueueSend(q, &cmd, pdMS_TO_TICKS(100)) == pdTRUE) {
        ESP_LOGI(TAG, "Starting profile: %s", profile.name);
    } else {
        ESP_LOGW(TAG, "Failed to queue start command");
    }
}

lv_obj_t *ui_screen_profiles_create(void)
{
    s_screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_screen, UI_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(s_screen, LV_OPA_COVER, 0);
    lv_obj_clear_flag(s_screen, LV_OBJ_FLAG_SCROLLABLE);

    /* Title */
    s_title_lbl = lv_label_create(s_screen);
    lv_obj_set_style_text_font(s_title_lbl, UI_FONT_MEDIUM, 0);
    lv_obj_set_style_text_color(s_title_lbl, UI_COLOR_TEXT, 0);
    lv_label_set_text(s_title_lbl, "Profiles");
    lv_obj_align(s_title_lbl, LV_ALIGN_TOP_LEFT, 12, 8);

    /* Profile list */
    s_list = lv_list_create(s_screen);
    lv_obj_set_size(s_list, 456, 230);
    lv_obj_align(s_list, LV_ALIGN_TOP_MID, 0, 52);
    lv_obj_set_style_bg_color(s_list, UI_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(s_list, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_list, 0, 0);
    lv_obj_set_style_pad_all(s_list, 8, 0);

    /* Page dots */
    ui_create_page_dots(s_screen, s_dots, UI_SCREEN_COUNT);

    /* Initial population */
    ui_screen_profiles_refresh();

    return s_screen;
}

void ui_screen_profiles_refresh(void)
{
    if (!s_list)
        return;

    /* Clear existing list items */
    lv_obj_clean(s_list);

    /* Load profile IDs */
    s_profile_count = firing_engine_list_profiles(s_profile_ids, FIRING_MAX_PROFILES);

    if (s_profile_count == 0) {
        lv_obj_t *lbl = lv_label_create(s_list);
        lv_obj_set_style_text_font(lbl, UI_FONT_SMALL, 0);
        lv_obj_set_style_text_color(lbl, UI_COLOR_TEXT_DIM, 0);
        lv_label_set_text(lbl, "No profiles");
        return;
    }

    for (int i = 0; i < s_profile_count; i++) {
        firing_profile_t profile;
        const char *name = s_profile_ids[i];

        if (firing_engine_load_profile(s_profile_ids[i], &profile) == ESP_OK) {
            name = profile.name;
        }

        lv_obj_t *btn = lv_list_add_button(s_list, NULL, name);
        lv_obj_set_style_text_font(btn, UI_FONT_SMALL, 0);
        lv_obj_set_style_text_color(btn, UI_COLOR_TEXT, 0);
        lv_obj_set_style_bg_color(btn, UI_COLOR_BG, 0);
        lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(btn, UI_COLOR_BORDER, LV_STATE_FOCUSED);
        lv_obj_add_event_cb(btn, profile_btn_cb, LV_EVENT_CLICKED, (void *)(intptr_t)i);
        lv_group_add_obj(lv_group_get_default(), btn);
    }
}

void ui_screen_profiles_set_page_dots(int active_index, int total)
{
    (void)total;
    if (!s_screen)
        return;
    ui_update_page_dots(s_dots, UI_SCREEN_COUNT, active_index);
}
