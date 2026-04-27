#include "dashboard.h"
#include "modal.h"
#include "modal_profile_picker.h"
#include "modal_action_menu.h"
#include "ui_common.h"
#include "firing_engine.h"
#include "firing_history.h"
#include "esp_log.h"
#include <stdio.h>

extern lv_group_t *g_input_group;

static const char *TAG = "dashboard";

#define STATUS_BAR_H 44
#define CONTENT_Y    STATUS_BAR_H
#define LEFT_COL_X   16
#define LEFT_COL_W   180

#define CHART_X                    206
#define CHART_Y_REL                (52 - CONTENT_Y)
#define CHART_W                    258
#define CHART_H                    212
#define CHART_POINTS               240
#define CHART_DEFAULT_DUR_S        3600u /* fallback when active profile has no estimate */
#define CHART_Y_MAX_DEFAULT        1400
#define CHART_PLANNED_START_TEMP_C 20.0f /* assumed cold-kiln start */

/* Visual state of the dashboard. Selected from firing_progress_t.status. */
typedef enum {
    VIEW_NONE = 0,
    VIEW_IDLE,
    VIEW_ACTIVE,
    VIEW_PAUSED,
    VIEW_COMPLETE,
    VIEW_ERROR,
    VIEW_AUTOTUNE,
} view_id_t;

/* Persistent widgets, created once in dashboard_create. */
static lv_obj_t *s_screen = NULL;
static lv_obj_t *s_status_bar = NULL;
static lv_obj_t *s_status_label = NULL;
static lv_obj_t *s_seg_label = NULL;
/* Invisible focusable widget. The encoder always points at it (in g_input_group),
 * so a SELECT press fires LV_EVENT_CLICKED and we open the contextual modal. */
static lv_obj_t *s_select_trap = NULL;

/* Swappable per-view content container. View-specific widgets are children. */
static lv_obj_t *s_content = NULL;
static view_id_t s_current_view = VIEW_NONE;
static view_id_t s_prev_view = VIEW_NONE;

/* IDLE view widgets. */
static lv_obj_t *s_idle_temp = NULL;

/* ACTIVE / PAUSED / AUTOTUNE view widgets. */
static lv_obj_t *s_active_temp = NULL;
static lv_obj_t *s_active_target = NULL;
static lv_obj_t *s_active_elapsed = NULL;
static lv_obj_t *s_active_remaining = NULL;
static lv_obj_t *s_chart = NULL;
static lv_chart_series_t *s_chart_actual = NULL;
static lv_chart_series_t *s_chart_planned = NULL;
static lv_obj_t *s_paused_overlay = NULL;

/* COMPLETE view widgets. */
static lv_obj_t *s_complete_now_temp = NULL;

/* ERROR view widgets. */
static lv_obj_t *s_error_now_temp = NULL;

/* Cached active profile + peak + total duration. Refreshed when entering a profile-using view
 * from a non-profile view. */
static firing_profile_t s_cached_profile;
static bool s_cached_profile_valid = false;
static uint32_t s_cached_total_dur_s = CHART_DEFAULT_DUR_S;
static float s_active_peak_c = 0.0f;

/* ── Mapping helpers ─────────────────────────────────── */

static view_id_t view_for_status(firing_status_t status)
{
    switch (status) {
    case FIRING_STATUS_HEATING:
    case FIRING_STATUS_HOLDING:
    case FIRING_STATUS_COOLING:
        return VIEW_ACTIVE;
    case FIRING_STATUS_PAUSED:
        return VIEW_PAUSED;
    case FIRING_STATUS_COMPLETE:
        return VIEW_COMPLETE;
    case FIRING_STATUS_ERROR:
        return VIEW_ERROR;
    case FIRING_STATUS_AUTOTUNE:
        return VIEW_AUTOTUNE;
    case FIRING_STATUS_IDLE:
    default:
        return VIEW_IDLE;
    }
}

static bool view_is_active_family(view_id_t v)
{
    return v == VIEW_ACTIVE || v == VIEW_PAUSED || v == VIEW_AUTOTUNE;
}

static bool view_uses_profile(view_id_t v)
{
    return view_is_active_family(v) || v == VIEW_COMPLETE || v == VIEW_ERROR;
}

/* Pick black or white for status-bar text so it stays readable on the bar's color. */
static lv_color_t status_text_color(firing_status_t status)
{
    switch (status) {
    case FIRING_STATUS_COOLING:
    case FIRING_STATUS_ERROR:
        return UI_COLOR_TEXT;
    default:
        return UI_COLOR_BG;
    }
}

static const char *error_code_description(firing_error_code_t code)
{
    switch (code) {
    case FIRING_ERR_TC_FAULT:
        return "Thermocouple disconnected or shorted";
    case FIRING_ERR_OVER_TEMP:
        return "Over temperature";
    case FIRING_ERR_NOT_RISING:
        return "Kiln not heating";
    case FIRING_ERR_RUNAWAY:
        return "Heating too fast";
    case FIRING_ERR_EMERGENCY_STOP:
        return "Emergency stop";
    case FIRING_ERR_NONE:
    default:
        return "Firing halted";
    }
}

/* ── Widget helpers ──────────────────────────────────── */

static lv_obj_t *make_label(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text);
    return l;
}

static lv_obj_t *create_content_area(void)
{
    lv_obj_t *c = lv_obj_create(s_screen);
    lv_obj_set_size(c, UI_LCD_W, UI_LCD_H - STATUS_BAR_H);
    lv_obj_set_pos(c, 0, CONTENT_Y);
    lv_obj_set_style_bg_opa(c, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(c, 0, 0);
    lv_obj_set_style_pad_all(c, 0, 0);
    lv_obj_clear_flag(c, LV_OBJ_FLAG_SCROLLABLE);
    return c;
}

/* Format a seconds count as "Hh MMm" or "Mm SSs" (under 1h). Optional prefix. */
static void format_duration(uint32_t seconds, char *buf, size_t buf_size, const char *prefix)
{
    unsigned h = (unsigned)(seconds / 3600u);
    unsigned m = (unsigned)((seconds % 3600u) / 60u);
    unsigned s = (unsigned)(seconds % 60u);
    if (h > 0) {
        snprintf(buf, buf_size, "%s%uh %02um", prefix, h, m);
    } else {
        snprintf(buf, buf_size, "%s%um %02us", prefix, m, s);
    }
}

static void clear_view_widgets(void)
{
    s_idle_temp = NULL;
    s_active_temp = NULL;
    s_active_target = NULL;
    s_active_elapsed = NULL;
    s_active_remaining = NULL;
    s_chart = NULL;
    s_chart_actual = NULL;
    s_chart_planned = NULL;
    s_paused_overlay = NULL;
    s_complete_now_temp = NULL;
    s_error_now_temp = NULL;
}

static void destroy_content(void)
{
    if (s_content) {
        lv_obj_delete(s_content);
        s_content = NULL;
    }
    clear_view_widgets();
}

/* Refresh the cached profile (and derived total duration + reset peak) for views that
 * need profile context. Call when entering a profile-using view from a non-profile view. */
static void enter_profile_view(const firing_progress_t *prog, const thermocouple_reading_t *tc)
{
    s_cached_profile_valid = false;
    s_cached_total_dur_s = CHART_DEFAULT_DUR_S;

    if (prog->profile_id[0] != '\0') {
        if (firing_engine_load_profile(prog->profile_id, &s_cached_profile) == ESP_OK) {
            s_cached_profile_valid = true;
            if (s_cached_profile.estimated_duration > 0) {
                s_cached_total_dur_s = s_cached_profile.estimated_duration * 60u;
            }
        } else {
            ESP_LOGW(TAG, "could not load active profile '%s'", prog->profile_id);
        }
    }

    s_active_peak_c = (tc && !tc->fault) ? tc->temperature_c : 0.0f;
}

/* ── IDLE view ─────────────────────────────────────────── */

static const char *outcome_label(history_outcome_t outcome)
{
    switch (outcome) {
    case HISTORY_OUTCOME_COMPLETE:
        return "complete";
    case HISTORY_OUTCOME_ABORTED:
        return "aborted";
    case HISTORY_OUTCOME_ERROR:
    default:
        return "error";
    }
}

static void build_view_idle(void)
{
    s_content = create_content_area();

    s_idle_temp = make_label(s_content, UI_FONT_BIG, UI_COLOR_TEXT, "-");
    lv_obj_align(s_idle_temp, LV_ALIGN_TOP_MID, 0, 92 - CONTENT_Y);

    lv_obj_t *ready = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "Ready");
    lv_obj_align(ready, LV_ALIGN_TOP_MID, 0, 156 - CONTENT_Y);

    /* Last-firing summary, only shown if there's at least one history record. */
    history_record_t last;
    if (history_get_records(&last, 1) > 0) {
        lv_obj_t *sep = lv_obj_create(s_content);
        lv_obj_set_size(sep, 200, 1);
        lv_obj_align(sep, LV_ALIGN_TOP_MID, 0, 200 - CONTENT_Y);
        lv_obj_set_style_bg_color(sep, UI_COLOR_BORDER, 0);
        lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(sep, 0, 0);
        lv_obj_set_style_pad_all(sep, 0, 0);
        lv_obj_clear_flag(sep, LV_OBJ_FLAG_SCROLLABLE);

        lv_obj_t *header = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "LAST FIRING");
        lv_obj_align(header, LV_ALIGN_TOP_MID, 0, 212 - CONTENT_Y);

        lv_obj_t *name = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT, last.profile_name);
        lv_obj_align(name, LV_ALIGN_TOP_MID, 0, 236 - CONTENT_Y);

        char dur_buf[24];
        format_duration(last.duration_s, dur_buf, sizeof(dur_buf), "");
        char details[96];
        snprintf(details, sizeof(details), "Peak %.0f°C  -  %s  -  %s", (double)last.peak_temp_c, dur_buf,
                 outcome_label(last.outcome));
        lv_obj_t *details_label = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, details);
        lv_obj_align(details_label, LV_ALIGN_TOP_MID, 0, 260 - CONTENT_Y);
    }

    lv_obj_t *hint = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT to start a firing");
    lv_obj_align(hint, LV_ALIGN_TOP_MID, 0, 286 - CONTENT_Y);
}

static void update_view_idle(const thermocouple_reading_t *tc)
{
    if (!s_idle_temp) {
        return;
    }
    if (tc->fault) {
        lv_label_set_text(s_idle_temp, "-");
    } else {
        char buf[16];
        snprintf(buf, sizeof(buf), "%.0f°C", (double)tc->temperature_c);
        lv_label_set_text(s_idle_temp, buf);
    }
}

/* ── ACTIVE / PAUSED / AUTOTUNE view ───────────────────── */

static void build_view_active(void)
{
    s_content = create_content_area();

    s_active_temp = make_label(s_content, UI_FONT_BIG, UI_COLOR_TEXT, "-");
    lv_obj_align(s_active_temp, LV_ALIGN_TOP_LEFT, LEFT_COL_X, 56 - CONTENT_Y);

    s_active_target = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "");
    lv_obj_align(s_active_target, LV_ALIGN_TOP_LEFT, LEFT_COL_X, 112 - CONTENT_Y);

    lv_obj_t *sep = lv_obj_create(s_content);
    lv_obj_set_size(sep, LEFT_COL_W - 12, 1);
    lv_obj_set_pos(sep, LEFT_COL_X, 156 - CONTENT_Y);
    lv_obj_set_style_bg_color(sep, UI_COLOR_BORDER, 0);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(sep, 0, 0);
    lv_obj_set_style_pad_all(sep, 0, 0);
    lv_obj_clear_flag(sep, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *elapsed_hdr = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "ELAPSED");
    lv_obj_align(elapsed_hdr, LV_ALIGN_TOP_LEFT, LEFT_COL_X, 168 - CONTENT_Y);

    s_active_elapsed = make_label(s_content, UI_FONT_MEDIUM, UI_COLOR_TEXT, "0m 00s");
    lv_obj_align(s_active_elapsed, LV_ALIGN_TOP_LEFT, LEFT_COL_X, 192 - CONTENT_Y);

    lv_obj_t *remaining_hdr = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "REMAINING");
    lv_obj_align(remaining_hdr, LV_ALIGN_TOP_LEFT, LEFT_COL_X, 232 - CONTENT_Y);

    s_active_remaining = make_label(s_content, UI_FONT_MEDIUM, UI_COLOR_TEXT, "-");
    lv_obj_align(s_active_remaining, LV_ALIGN_TOP_LEFT, LEFT_COL_X, 256 - CONTENT_Y);

    /* Chart with planned overlay + actual series. */
    s_chart = lv_chart_create(s_content);
    lv_obj_set_size(s_chart, CHART_W, CHART_H);
    lv_obj_set_pos(s_chart, CHART_X, CHART_Y_REL);
    lv_chart_set_type(s_chart, LV_CHART_TYPE_LINE);
    lv_chart_set_point_count(s_chart, CHART_POINTS);

    int32_t y_max = CHART_Y_MAX_DEFAULT;
    if (s_cached_profile_valid && s_cached_profile.max_temp > 0.0f) {
        int32_t profile_max = (int32_t)(s_cached_profile.max_temp + 50.0f);
        if (profile_max > 0 && profile_max < CHART_Y_MAX_DEFAULT) {
            y_max = profile_max;
        }
    }
    lv_chart_set_range(s_chart, LV_CHART_AXIS_PRIMARY_Y, 0, y_max);
    lv_chart_set_div_line_count(s_chart, 6, 0); /* horizontal grid every ~200°C */

    lv_obj_set_style_bg_color(s_chart, UI_COLOR_SURFACE_1, 0);
    lv_obj_set_style_bg_opa(s_chart, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(s_chart, UI_COLOR_BORDER, 0);
    lv_obj_set_style_border_width(s_chart, 1, 0);
    lv_obj_set_style_radius(s_chart, 4, 0);
    lv_obj_set_style_line_color(s_chart, UI_COLOR_BORDER, LV_PART_MAIN);
    lv_obj_set_style_line_width(s_chart, 3, LV_PART_ITEMS);
    lv_obj_set_style_size(s_chart, 0, 0, LV_PART_INDICATOR); /* no point markers */
    lv_obj_set_style_pad_all(s_chart, 0, 0);
    lv_obj_clear_flag(s_chart, LV_OBJ_FLAG_SCROLLABLE);

    /* Planned series first so it draws underneath the actual line. */
    s_chart_planned = lv_chart_add_series(s_chart, UI_COLOR_TEXT_DIM, LV_CHART_AXIS_PRIMARY_Y);
    s_chart_actual = lv_chart_add_series(s_chart, UI_COLOR_HEATING, LV_CHART_AXIS_PRIMARY_Y);
    for (uint32_t i = 0; i < CHART_POINTS; i++) {
        lv_chart_set_value_by_id(s_chart, s_chart_planned, i, LV_CHART_POINT_NONE);
        lv_chart_set_value_by_id(s_chart, s_chart_actual, i, LV_CHART_POINT_NONE);
    }

    if (s_cached_profile_valid && s_cached_total_dur_s > 0) {
        float dt = (float)s_cached_total_dur_s / (float)CHART_POINTS;
        for (uint32_t i = 0; i < CHART_POINTS; i++) {
            uint32_t t = (uint32_t)((float)i * dt);
            float planned = firing_planned_temp_at(&s_cached_profile, t, CHART_PLANNED_START_TEMP_C);
            lv_chart_set_value_by_id(s_chart, s_chart_planned, i, (int32_t)planned);
        }
    }

    /* PAUSED overlay — created here, hidden by default. dashboard_update toggles visibility. */
    s_paused_overlay = make_label(s_content, UI_FONT_BIG, UI_COLOR_TEXT_DIM, "PAUSED");
    lv_obj_align_to(s_paused_overlay, s_chart, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_paused_overlay, LV_OBJ_FLAG_HIDDEN);

    /* Footer hint, right-aligned. Profile name will fill the left in step 10. */
    lv_obj_t *hint = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT for actions");
    lv_obj_align(hint, LV_ALIGN_TOP_RIGHT, -16, 286 - CONTENT_Y);
}

static void update_view_active(const thermocouple_reading_t *tc, const firing_progress_t *prog)
{
    if (!s_active_temp) {
        return;
    }

    char buf[32];

    if (tc->fault) {
        lv_label_set_text(s_active_temp, "-");
    } else {
        snprintf(buf, sizeof(buf), "%.0f°C", (double)tc->temperature_c);
        lv_label_set_text(s_active_temp, buf);
    }

    snprintf(buf, sizeof(buf), LV_SYMBOL_RIGHT " %.0f°C", (double)prog->target_temp);
    lv_label_set_text(s_active_target, buf);

    format_duration(prog->elapsed_time, buf, sizeof(buf), "");
    lv_label_set_text(s_active_elapsed, buf);

    if (prog->estimated_remaining > 0) {
        format_duration(prog->estimated_remaining, buf, sizeof(buf), "~");
        lv_label_set_text(s_active_remaining, buf);
    } else {
        lv_label_set_text(s_active_remaining, "-");
    }

    if (s_chart && s_chart_actual && s_cached_total_dur_s > 0 && !tc->fault) {
        uint64_t scaled = (uint64_t)prog->elapsed_time * CHART_POINTS;
        uint32_t idx = (uint32_t)(scaled / s_cached_total_dur_s);
        if (idx >= CHART_POINTS) {
            idx = CHART_POINTS - 1;
        }
        lv_chart_set_value_by_id(s_chart, s_chart_actual, idx, (int32_t)tc->temperature_c);
    }
}

/* ── COMPLETE view ─────────────────────────────────────── */

static void build_view_complete(const firing_progress_t *prog)
{
    s_content = create_content_area();

    lv_obj_t *title = make_label(s_content, UI_FONT_MEDIUM, UI_COLOR_TEXT, "Firing complete");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 80 - CONTENT_Y);

    const char *name = (s_cached_profile_valid && s_cached_profile.name[0] != '\0') ? s_cached_profile.name : "Firing";
    lv_obj_t *prof = make_label(s_content, UI_FONT_MEDIUM, UI_COLOR_TEXT, name);
    lv_obj_align(prof, LV_ALIGN_TOP_MID, 0, 132 - CONTENT_Y);

    char peak_buf[24];
    snprintf(peak_buf, sizeof(peak_buf), "Peak %.0f°C", (double)s_active_peak_c);
    lv_obj_t *peak = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT, peak_buf);
    lv_obj_align(peak, LV_ALIGN_TOP_MID, 0, 180 - CONTENT_Y);

    char buf[32];
    format_duration(prog->elapsed_time, buf, sizeof(buf), "Duration ");
    lv_obj_t *dur = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT, buf);
    lv_obj_align(dur, LV_ALIGN_TOP_MID, 0, 208 - CONTENT_Y);

    s_complete_now_temp = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "");
    lv_obj_align(s_complete_now_temp, LV_ALIGN_TOP_MID, 0, 240 - CONTENT_Y);

    lv_obj_t *hint = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT to start a new firing");
    lv_obj_align(hint, LV_ALIGN_TOP_MID, 0, 286 - CONTENT_Y);
}

static void update_view_complete(const thermocouple_reading_t *tc)
{
    if (!s_complete_now_temp) {
        return;
    }
    if (tc->fault) {
        lv_label_set_text(s_complete_now_temp, "");
    } else {
        char buf[32];
        snprintf(buf, sizeof(buf), "Now %.0f°C, cooling", (double)tc->temperature_c);
        lv_label_set_text(s_complete_now_temp, buf);
    }
}

/* ── ERROR view ────────────────────────────────────────── */

static void build_view_error(const firing_progress_t *prog)
{
    s_content = create_content_area();

    firing_error_code_t code = firing_engine_get_error_code();
    const char *desc = error_code_description(code);

    lv_obj_t *title = make_label(s_content, UI_FONT_MEDIUM, UI_COLOR_TEXT, "Firing stopped");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 80 - CONTENT_Y);

    lv_obj_t *err = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT, desc);
    lv_obj_align(err, LV_ALIGN_TOP_MID, 0, 132 - CONTENT_Y);

    s_error_now_temp = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT, "");
    lv_obj_align(s_error_now_temp, LV_ALIGN_TOP_MID, 0, 176 - CONTENT_Y);

    if (s_cached_profile_valid && s_cached_profile.name[0] != '\0') {
        lv_obj_t *prof = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "");
        lv_label_set_text_fmt(prof, "Profile: %s", s_cached_profile.name);
        lv_obj_align(prof, LV_ALIGN_TOP_MID, 0, 204 - CONTENT_Y);
    }

    if (prog->total_segments > 0) {
        char buf[64];
        char dur_buf[24];
        format_duration(prog->elapsed_time, dur_buf, sizeof(dur_buf), "");
        snprintf(buf, sizeof(buf), "Stopped at Seg %u / %s", (unsigned)(prog->current_segment + 1), dur_buf);
        lv_obj_t *seg = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, buf);
        lv_obj_align(seg, LV_ALIGN_TOP_MID, 0, 232 - CONTENT_Y);
    }

    lv_obj_t *hint = make_label(s_content, UI_FONT_SMALL, UI_COLOR_TEXT_DIM, "SELECT to acknowledge");
    lv_obj_align(hint, LV_ALIGN_TOP_MID, 0, 286 - CONTENT_Y);
}

static void update_view_error(const thermocouple_reading_t *tc)
{
    if (!s_error_now_temp) {
        return;
    }
    if (tc->fault) {
        lv_label_set_text(s_error_now_temp, "Last reading -");
    } else {
        char buf[32];
        snprintf(buf, sizeof(buf), "Last reading %.0f°C", (double)tc->temperature_c);
        lv_label_set_text(s_error_now_temp, buf);
    }
}

/* ── SELECT-driven menus ───────────────────────────────── */

/* SELECT on the bare dashboard opens the contextual modal for the current view. */
static void on_select_trap_clicked(lv_event_t *e)
{
    (void)e;
    if (dashboard_modal_active()) {
        return;
    }
    switch (s_current_view) {
    case VIEW_IDLE:
    case VIEW_COMPLETE:
    case VIEW_ERROR:
        modal_profile_picker_open();
        break;
    case VIEW_ACTIVE:
    case VIEW_PAUSED:
    case VIEW_AUTOTUNE: {
        firing_progress_t prog;
        firing_engine_get_progress(&prog);
        modal_action_menu_open(prog.status);
        break;
    }
    case VIEW_NONE:
    default:
        break;
    }
}

/* ── View switching ────────────────────────────────────── */

static void switch_view(view_id_t target, const firing_progress_t *prog)
{
    if (target == s_current_view) {
        return;
    }
    destroy_content();
    switch (target) {
    case VIEW_ACTIVE:
    case VIEW_PAUSED:
    case VIEW_AUTOTUNE:
        build_view_active();
        break;
    case VIEW_COMPLETE:
        build_view_complete(prog);
        break;
    case VIEW_ERROR:
        build_view_error(prog);
        break;
    case VIEW_IDLE:
    default:
        build_view_idle();
        break;
    case VIEW_NONE:
        break;
    }
    s_current_view = target;
}

/* ── Public API ────────────────────────────────────────── */

void dashboard_create(void)
{
    s_screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_screen, UI_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(s_screen, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(s_screen, 0, 0);
    lv_obj_clear_flag(s_screen, LV_OBJ_FLAG_SCROLLABLE);

    s_status_bar = lv_obj_create(s_screen);
    lv_obj_set_size(s_status_bar, UI_LCD_W, STATUS_BAR_H);
    lv_obj_set_pos(s_status_bar, 0, 0);
    lv_obj_set_style_bg_color(s_status_bar, UI_COLOR_IDLE, 0);
    lv_obj_set_style_bg_opa(s_status_bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_status_bar, 0, 0);
    lv_obj_set_style_radius(s_status_bar, 0, 0);
    lv_obj_set_style_pad_all(s_status_bar, 0, 0);
    lv_obj_clear_flag(s_status_bar, LV_OBJ_FLAG_SCROLLABLE);

    s_status_label = make_label(s_status_bar, UI_FONT_SMALL, UI_COLOR_BG, "IDLE");
    lv_obj_align(s_status_label, LV_ALIGN_LEFT_MID, 16, 0);

    s_seg_label = make_label(s_status_bar, UI_FONT_SMALL, UI_COLOR_BG, "");
    lv_obj_align(s_seg_label, LV_ALIGN_RIGHT_MID, -16, 0);

    /* Invisible 1x1 trap parked off-screen. It's the only object in g_input_group,
     * so the encoder is always focused on it and SELECT presses fire its click event. */
    s_select_trap = lv_obj_create(s_screen);
    lv_obj_set_size(s_select_trap, 1, 1);
    lv_obj_set_pos(s_select_trap, -10, -10);
    lv_obj_set_style_bg_opa(s_select_trap, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(s_select_trap, 0, 0);
    lv_obj_set_style_pad_all(s_select_trap, 0, 0);
    lv_obj_clear_flag(s_select_trap, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(s_select_trap, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(s_select_trap, on_select_trap_clicked, LV_EVENT_CLICKED, NULL);
    lv_group_add_obj(g_input_group, s_select_trap);
    lv_group_focus_obj(s_select_trap);

    lv_screen_load(s_screen);
    switch_view(VIEW_IDLE, NULL);
    s_prev_view = VIEW_IDLE;

    ESP_LOGI(TAG, "dashboard created");
}

void dashboard_update(const thermocouple_reading_t *tc, const firing_progress_t *prog)
{
    if (!s_screen) {
        return;
    }

    view_id_t target = view_for_status(prog->status);

    if (!view_uses_profile(s_prev_view) && view_uses_profile(target)) {
        enter_profile_view(prog, tc);
    }

    switch_view(target, prog);
    s_prev_view = target;

    /* Track peak across active firing. */
    if (view_is_active_family(s_current_view) && !tc->fault && tc->temperature_c > s_active_peak_c) {
        s_active_peak_c = tc->temperature_c;
    }

    /* Status bar color + text. */
    lv_color_t bar_color = ui_status_color(prog->status);
    lv_color_t text_color = status_text_color(prog->status);
    lv_obj_set_style_bg_color(s_status_bar, bar_color, 0);
    lv_obj_set_style_text_color(s_status_label, text_color, 0);
    lv_obj_set_style_text_color(s_seg_label, text_color, 0);
    lv_label_set_text(s_status_label, ui_status_label(prog->status));

    if (view_is_active_family(s_current_view)) {
        lv_label_set_text_fmt(s_seg_label, "SEGMENT %u/%u", (unsigned)(prog->current_segment + 1),
                              (unsigned)prog->total_segments);
    } else {
        lv_label_set_text(s_seg_label, "");
    }

    /* PAUSED overlay visibility. */
    if (s_paused_overlay) {
        if (s_current_view == VIEW_PAUSED) {
            lv_obj_clear_flag(s_paused_overlay, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(s_paused_overlay, LV_OBJ_FLAG_HIDDEN);
        }
    }

    /* View-specific data refresh. */
    switch (s_current_view) {
    case VIEW_ACTIVE:
    case VIEW_PAUSED:
    case VIEW_AUTOTUNE:
        update_view_active(tc, prog);
        break;
    case VIEW_COMPLETE:
        update_view_complete(tc);
        break;
    case VIEW_ERROR:
        update_view_error(tc);
        break;
    case VIEW_IDLE:
    default:
        update_view_idle(tc);
        break;
    }
}
