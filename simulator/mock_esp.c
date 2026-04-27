/**
 * Mock implementations of ESP-IDF / firmware APIs that the dashboard, modals,
 * and ui_common.h depend on. Provides fake thermocouple readings, firing engine
 * state, error code, planned-curve, history records, and the LVGL group/indev
 * globals that display_init.c exports on hardware.
 */
#include "lvgl.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "firing_engine.h"
#include "firing_history.h"
#include "mock_esp.h"
#include <string.h>
#include <stdio.h>

/* ── LVGL globals normally defined by display_init.c ─────────────────────── */

lv_indev_t *g_indev_encoder = NULL;
lv_group_t *g_input_group = NULL;
lv_group_t *g_modal_group = NULL;

/* ── Mock thermocouple ───────────────────────────────────────────────────── */

static thermocouple_reading_t s_mock_tc = {
    .temperature_c = 24.0f,
    .internal_temp_c = 24.0f,
    .fault = 0,
    .timestamp_us = 0,
};

void thermocouple_get_latest(thermocouple_reading_t *out)
{
    *out = s_mock_tc;
}

void mock_set_thermocouple(const thermocouple_reading_t *tc)
{
    s_mock_tc = *tc;
}

/* ── Mock firing progress ────────────────────────────────────────────────── */

static firing_progress_t s_mock_progress = {
    .is_active = false,
    .profile_id = "",
    .current_temp = 24.0f,
    .target_temp = 0.0f,
    .current_segment = 0,
    .total_segments = 0,
    .elapsed_time = 0,
    .estimated_remaining = 0,
    .status = FIRING_STATUS_IDLE,
};

void firing_engine_get_progress(firing_progress_t *out)
{
    *out = s_mock_progress;
}

void mock_set_progress(const firing_progress_t *p)
{
    s_mock_progress = *p;
}

/* ── Mock command queue (sink) ───────────────────────────────────────────── */

static QueueHandle_t s_mock_queue = NULL;

QueueHandle_t firing_engine_get_cmd_queue(void)
{
    return s_mock_queue;
}

/* ── Mock error code ─────────────────────────────────────────────────────── */

static firing_error_code_t s_mock_error = FIRING_ERR_TC_FAULT;

firing_error_code_t firing_engine_get_error_code(void)
{
    return s_mock_error;
}

void mock_set_error_code(firing_error_code_t code)
{
    s_mock_error = code;
}

/* ── Mock profiles ───────────────────────────────────────────────────────── */

static const char *s_mock_profile_names[] = {
    "Bisque Cone 04",
    "Glaze Cone 6",
    "Glaze Cone 10",
    "Low Fire",
    "Crystalline",
};
static const float s_mock_profile_max_temp[] = {1060.0f, 1222.0f, 1305.0f, 999.0f, 1260.0f};
static const uint32_t s_mock_profile_minutes[] = {540, 480, 600, 420, 720};
#define MOCK_PROFILE_COUNT (sizeof(s_mock_profile_names) / sizeof(s_mock_profile_names[0]))

int firing_engine_list_profiles(char ids_out[][FIRING_ID_LEN], int max_count)
{
    int count = (int)MOCK_PROFILE_COUNT;
    if (count > max_count) {
        count = max_count;
    }
    for (int i = 0; i < count; i++) {
        snprintf(ids_out[i], FIRING_ID_LEN, "profile-%d", i);
    }
    return count;
}

esp_err_t firing_engine_load_profile(const char *id, firing_profile_t *profile)
{
    memset(profile, 0, sizeof(*profile));
    strncpy(profile->id, id, FIRING_ID_LEN - 1);

    int idx = 0;
    if (sscanf(id, "profile-%d", &idx) == 1 && idx >= 0 && idx < (int)MOCK_PROFILE_COUNT) {
        strncpy(profile->name, s_mock_profile_names[idx], FIRING_NAME_LEN - 1);
        profile->max_temp = s_mock_profile_max_temp[idx];
        profile->estimated_duration = s_mock_profile_minutes[idx];
    } else {
        strncpy(profile->name, id, FIRING_NAME_LEN - 1);
        profile->max_temp = 1200.0f;
        profile->estimated_duration = 480;
    }

    profile->segment_count = 3;
    return ESP_OK;
}

/* ── Mock planned-temperature curve ──────────────────────────────────────── */

/* Synthetic ramp-then-hold for visualization. The real per-segment walk lives
 * in firing_engine.c and we deliberately don't drag the whole engine into the
 * simulator. Linear from start_temp → max_temp over the first 85% of the
 * profile's estimated duration, flat after. */
float firing_planned_temp_at(const firing_profile_t *profile, uint32_t t_seconds, float start_temp)
{
    if (!profile || profile->estimated_duration == 0) {
        return start_temp;
    }
    uint32_t total_s = profile->estimated_duration * 60u;
    if (t_seconds >= total_s) {
        return profile->max_temp;
    }
    float frac = (float)t_seconds / (float)total_s;
    if (frac < 0.85f) {
        return start_temp + (profile->max_temp - start_temp) * (frac / 0.85f);
    }
    return profile->max_temp;
}

/* ── Mock history ────────────────────────────────────────────────────────── */

static history_record_t s_mock_last_firing;
static bool s_mock_has_last_firing = false;

esp_err_t history_init(void)
{
    return ESP_OK;
}

int history_get_records(history_record_t *out_records, int max_count)
{
    if (!s_mock_has_last_firing || max_count < 1) {
        return 0;
    }
    out_records[0] = s_mock_last_firing;
    return 1;
}

void mock_set_last_firing(const history_record_t *r)
{
    if (r) {
        s_mock_last_firing = *r;
        s_mock_has_last_firing = true;
    } else {
        s_mock_has_last_firing = false;
    }
}
