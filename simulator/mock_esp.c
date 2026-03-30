/**
 * Mock implementations of ESP-IDF APIs that the display UI screens call.
 * Provides fake thermocouple readings and firing engine state for the simulator.
 */
#include "firing_types.h"
#include "thermocouple.h"
#include "firing_engine.h"
#include <string.h>
#include <stdio.h>

/* --- Mock thermocouple --- */

static thermocouple_reading_t s_mock_tc = {
    .temperature_c = 842.0f,
    .internal_temp_c = 28.0f,
    .fault = 0,
    .timestamp_us = 0,
};

void thermocouple_get_latest(thermocouple_reading_t *out)
{
    *out = s_mock_tc;
}

/* --- Mock firing engine --- */

static firing_progress_t s_mock_progress = {
    .is_active = true,
    .profile_id = "cone6-medium",
    .current_temp = 842.0f,
    .target_temp = 1222.0f,
    .current_segment = 1,
    .total_segments = 4,
    .elapsed_time = 5520,  /* 1h 32m */
    .estimated_remaining = 14400,
    .status = FIRING_STATUS_HEATING,
};

void firing_engine_get_progress(firing_progress_t *out)
{
    *out = s_mock_progress;
}

static QueueHandle_t s_mock_queue = NULL;

QueueHandle_t firing_engine_get_cmd_queue(void)
{
    return s_mock_queue;
}

/* Mock profiles */
static const char *s_mock_profile_names[] = {
    "Cone 06 Bisque",
    "Cone 6 Medium",
    "Cone 10 Slow",
};
#define MOCK_PROFILE_COUNT 3

int firing_engine_list_profiles(char ids_out[][FIRING_ID_LEN], int max_count)
{
    int count = MOCK_PROFILE_COUNT;
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

    /* Determine which mock profile by parsing the index */
    int idx = 0;
    if (sscanf(id, "profile-%d", &idx) == 1 && idx >= 0 && idx < MOCK_PROFILE_COUNT) {
        strncpy(profile->name, s_mock_profile_names[idx], FIRING_NAME_LEN - 1);
    } else {
        strncpy(profile->name, id, FIRING_NAME_LEN - 1);
    }

    profile->segment_count = 3;
    profile->max_temp = 1222.0f;
    profile->estimated_duration = 480;
    return ESP_OK;
}
