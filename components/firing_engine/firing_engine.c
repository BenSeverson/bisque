#include "firing_engine.h"
#include "thermocouple.h"
#include "pid_control.h"
#include "safety.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <string.h>
#include <math.h>

static const char *TAG = "firing_engine";

#define NVS_NS_PROFILES "profiles"
#define NVS_NS_SETTINGS "kiln_set"
#define NVS_KEY_INDEX   "idx"

/* Shared state */
static firing_progress_t s_progress;
static SemaphoreHandle_t s_progress_mutex;

static kiln_settings_t s_settings;
static SemaphoreHandle_t s_settings_mutex;

static QueueHandle_t s_cmd_queue;

/* PID controller */
static pid_controller_t s_pid;

/* Auto-tune state */
static pid_autotune_t s_autotune;

/* ── Internal helpers ──────────────────────────────── */

static void progress_lock(void)   { xSemaphoreTake(s_progress_mutex, portMAX_DELAY); }
static void progress_unlock(void) { xSemaphoreGive(s_progress_mutex); }
static void settings_lock(void)   { xSemaphoreTake(s_settings_mutex, portMAX_DELAY); }
static void settings_unlock(void) { xSemaphoreGive(s_settings_mutex); }

/* ── Default Profiles ──────────────────────────────── */

static const firing_profile_t s_default_profiles[] = {
    {
        .id = "bisque-04",
        .name = "Bisque Cone 04",
        .description = "Standard bisque firing to cone 04",
        .segment_count = 3,
        .max_temp = 1060.0f,
        .estimated_duration = 540,
        .segments = {
            { .id = "1", .name = "Warm-up", .ramp_rate = 100.0f, .target_temp = 200.0f, .hold_time = 60 },
            { .id = "2", .name = "Water smoke", .ramp_rate = 50.0f, .target_temp = 600.0f, .hold_time = 30 },
            { .id = "3", .name = "Ramp to top", .ramp_rate = 150.0f, .target_temp = 1060.0f, .hold_time = 15 },
        }
    },
    {
        .id = "glaze-6",
        .name = "Glaze Cone 6",
        .description = "Mid-fire glaze for stoneware",
        .segment_count = 3,
        .max_temp = 1222.0f,
        .estimated_duration = 480,
        .segments = {
            { .id = "1", .name = "Initial heat", .ramp_rate = 150.0f, .target_temp = 600.0f, .hold_time = 0 },
            { .id = "2", .name = "Medium ramp", .ramp_rate = 100.0f, .target_temp = 1000.0f, .hold_time = 0 },
            { .id = "3", .name = "Final ramp", .ramp_rate = 80.0f, .target_temp = 1222.0f, .hold_time = 10 },
        }
    },
    {
        .id = "glaze-10",
        .name = "Glaze Cone 10",
        .description = "High-fire glaze for porcelain",
        .segment_count = 3,
        .max_temp = 1305.0f,
        .estimated_duration = 600,
        .segments = {
            { .id = "1", .name = "Low heat", .ramp_rate = 120.0f, .target_temp = 500.0f, .hold_time = 0 },
            { .id = "2", .name = "Medium heat", .ramp_rate = 150.0f, .target_temp = 1000.0f, .hold_time = 15 },
            { .id = "3", .name = "High heat", .ramp_rate = 100.0f, .target_temp = 1305.0f, .hold_time = 20 },
        }
    },
    {
        .id = "low-fire",
        .name = "Low Fire Cone 06",
        .description = "Low temp for earthenware and decals",
        .segment_count = 2,
        .max_temp = 999.0f,
        .estimated_duration = 420,
        .segments = {
            { .id = "1", .name = "Warm-up", .ramp_rate = 100.0f, .target_temp = 400.0f, .hold_time = 30 },
            { .id = "2", .name = "Ramp to top", .ramp_rate = 120.0f, .target_temp = 999.0f, .hold_time = 10 },
        }
    },
    {
        .id = "crystalline",
        .name = "Crystalline Glaze",
        .description = "Controlled cooling for crystal growth",
        .segment_count = 3,
        .max_temp = 1260.0f,
        .estimated_duration = 720,
        .segments = {
            { .id = "1", .name = "Initial ramp", .ramp_rate = 200.0f, .target_temp = 1260.0f, .hold_time = 30 },
            { .id = "2", .name = "Crystal growth", .ramp_rate = -200.0f, .target_temp = 1100.0f, .hold_time = 120 },
            { .id = "3", .name = "Cool down", .ramp_rate = -150.0f, .target_temp = 800.0f, .hold_time = 0 },
        }
    },
};

#define NUM_DEFAULT_PROFILES (sizeof(s_default_profiles) / sizeof(s_default_profiles[0]))

static void load_default_profiles(void)
{
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    int count = firing_engine_list_profiles(ids, FIRING_MAX_PROFILES);

    if (count > 0) {
        ESP_LOGI(TAG, "Found %d existing profiles, skipping defaults", count);
        return;
    }

    ESP_LOGI(TAG, "No profiles found, loading %d defaults...", (int)NUM_DEFAULT_PROFILES);
    for (size_t i = 0; i < NUM_DEFAULT_PROFILES; i++) {
        esp_err_t err = firing_engine_save_profile(&s_default_profiles[i]);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "  Loaded: %s", s_default_profiles[i].name);
        } else {
            ESP_LOGW(TAG, "  Failed to load: %s (%s)", s_default_profiles[i].name, esp_err_to_name(err));
        }
    }
}

/* ── Init ──────────────────────────────────────────── */

esp_err_t firing_engine_init(void)
{
    s_progress_mutex = xSemaphoreCreateMutex();
    s_settings_mutex = xSemaphoreCreateMutex();
    s_cmd_queue = xQueueCreate(4, sizeof(firing_cmd_t));

    if (!s_progress_mutex || !s_settings_mutex || !s_cmd_queue) {
        return ESP_ERR_NO_MEM;
    }

    memset(&s_progress, 0, sizeof(s_progress));
    s_progress.status = FIRING_STATUS_IDLE;

    /* Load settings from NVS */
    s_settings.temp_unit = 'C';
    s_settings.max_safe_temp = 1300.0f;
    s_settings.alarm_enabled = true;
    s_settings.auto_shutdown = true;
    s_settings.notifications_enabled = true;

    nvs_handle_t handle;
    if (nvs_open(NVS_NS_SETTINGS, NVS_READONLY, &handle) == ESP_OK) {
        uint8_t u8;
        int32_t i32;
        if (nvs_get_u8(handle, "unit", &u8) == ESP_OK)
            s_settings.temp_unit = (char)u8;
        if (nvs_get_i32(handle, "max_temp", &i32) == ESP_OK)
            s_settings.max_safe_temp = (float)i32;
        if (nvs_get_u8(handle, "alarm", &u8) == ESP_OK)
            s_settings.alarm_enabled = u8;
        if (nvs_get_u8(handle, "autoshut", &u8) == ESP_OK)
            s_settings.auto_shutdown = u8;
        if (nvs_get_u8(handle, "notif", &u8) == ESP_OK)
            s_settings.notifications_enabled = u8;
        nvs_close(handle);
    }

    /* Initialize PID */
    float kp, ki, kd;
    pid_load_gains(&kp, &ki, &kd);
    pid_init(&s_pid, kp, ki, kd, 0.0f, 1.0f);

    /* Initialize auto-tune state */
    memset(&s_autotune, 0, sizeof(s_autotune));
    s_autotune.state = AUTOTUNE_IDLE;

    /* Load default profiles if none exist */
    load_default_profiles();

    ESP_LOGI(TAG, "Firing engine initialized (PID: Kp=%.4f Ki=%.4f Kd=%.4f)", kp, ki, kd);
    return ESP_OK;
}

QueueHandle_t firing_engine_get_cmd_queue(void)
{
    return s_cmd_queue;
}

void firing_engine_get_progress(firing_progress_t *out)
{
    progress_lock();
    *out = s_progress;
    progress_unlock();
}

void firing_engine_get_settings(kiln_settings_t *out)
{
    settings_lock();
    *out = s_settings;
    settings_unlock();
}

esp_err_t firing_engine_set_settings(const kiln_settings_t *settings)
{
    settings_lock();
    s_settings = *settings;
    settings_unlock();

    /* Update safety module */
    safety_set_max_temp(settings->max_safe_temp);

    /* Persist to NVS */
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_SETTINGS, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    nvs_set_u8(handle, "unit", (uint8_t)settings->temp_unit);
    nvs_set_i32(handle, "max_temp", (int32_t)settings->max_safe_temp);
    nvs_set_u8(handle, "alarm", settings->alarm_enabled ? 1 : 0);
    nvs_set_u8(handle, "autoshut", settings->auto_shutdown ? 1 : 0);
    nvs_set_u8(handle, "notif", settings->notifications_enabled ? 1 : 0);
    err = nvs_commit(handle);
    nvs_close(handle);
    return err;
}

/* ── Profile NVS Storage ───────────────────────────── */

/*
 * Profiles stored as NVS blobs under namespace "profiles".
 * Key = profile ID (truncated to 15 chars for NVS key limit).
 * A separate "idx" blob holds the list of stored profile IDs.
 */

static void make_nvs_key(const char *id, char *key, size_t key_size)
{
    /* NVS keys max 15 chars */
    strncpy(key, id, key_size - 1);
    key[key_size - 1] = '\0';
    /* Replace any non-alphanumeric with underscore */
    for (int i = 0; key[i]; i++) {
        char c = key[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_')) {
            key[i] = '_';
        }
    }
}

esp_err_t firing_engine_save_profile(const firing_profile_t *profile)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_PROFILES, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    char key[16];
    make_nvs_key(profile->id, key, sizeof(key));

    err = nvs_set_blob(handle, key, profile, sizeof(firing_profile_t));
    if (err != ESP_OK) {
        nvs_close(handle);
        return err;
    }

    /* Update index: load existing, add if not present */
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    size_t idx_size = sizeof(ids);
    int count = 0;
    if (nvs_get_blob(handle, NVS_KEY_INDEX, ids, &idx_size) == ESP_OK) {
        count = (int)(idx_size / FIRING_ID_LEN);
    }

    /* Check if already in index */
    bool found = false;
    for (int i = 0; i < count; i++) {
        if (strcmp(ids[i], profile->id) == 0) {
            found = true;
            break;
        }
    }
    if (!found && count < FIRING_MAX_PROFILES) {
        strncpy(ids[count], profile->id, FIRING_ID_LEN - 1);
        ids[count][FIRING_ID_LEN - 1] = '\0';
        count++;
        nvs_set_blob(handle, NVS_KEY_INDEX, ids, count * FIRING_ID_LEN);
    }

    err = nvs_commit(handle);
    nvs_close(handle);
    ESP_LOGI(TAG, "Profile saved: %s", profile->name);
    return err;
}

esp_err_t firing_engine_load_profile(const char *id, firing_profile_t *profile)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_PROFILES, NVS_READONLY, &handle);
    if (err != ESP_OK) return err;

    char key[16];
    make_nvs_key(id, key, sizeof(key));

    size_t size = sizeof(firing_profile_t);
    err = nvs_get_blob(handle, key, profile, &size);
    nvs_close(handle);
    return err;
}

esp_err_t firing_engine_delete_profile(const char *id)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_PROFILES, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    char key[16];
    make_nvs_key(id, key, sizeof(key));
    nvs_erase_key(handle, key);

    /* Remove from index */
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    size_t idx_size = sizeof(ids);
    int count = 0;
    if (nvs_get_blob(handle, NVS_KEY_INDEX, ids, &idx_size) == ESP_OK) {
        count = (int)(idx_size / FIRING_ID_LEN);
    }

    for (int i = 0; i < count; i++) {
        if (strcmp(ids[i], id) == 0) {
            memmove(&ids[i], &ids[i + 1], (count - i - 1) * FIRING_ID_LEN);
            count--;
            nvs_set_blob(handle, NVS_KEY_INDEX, ids, count * FIRING_ID_LEN);
            break;
        }
    }

    err = nvs_commit(handle);
    nvs_close(handle);
    ESP_LOGI(TAG, "Profile deleted: %s", id);
    return err;
}

int firing_engine_list_profiles(char ids_out[][FIRING_ID_LEN], int max_count)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NS_PROFILES, NVS_READONLY, &handle) != ESP_OK) {
        return 0;
    }

    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    size_t idx_size = sizeof(ids);
    int count = 0;
    if (nvs_get_blob(handle, NVS_KEY_INDEX, ids, &idx_size) == ESP_OK) {
        count = (int)(idx_size / FIRING_ID_LEN);
    }
    nvs_close(handle);

    int result = (count < max_count) ? count : max_count;
    memcpy(ids_out, ids, result * FIRING_ID_LEN);
    return result;
}

/* ── Firing Task ───────────────────────────────────── */

/* State for active firing */
static firing_profile_t s_active_profile;
static int64_t s_segment_start_time_us;
static float s_segment_start_temp;
static float s_segment_hold_start_time_s;
static bool s_holding;

static void start_segment(int segment_idx, float current_temp)
{
    s_segment_start_time_us = esp_timer_get_time();
    s_segment_start_temp = current_temp;
    s_holding = false;
    s_segment_hold_start_time_s = 0;

    firing_segment_t *seg = &s_active_profile.segments[segment_idx];
    ESP_LOGI(TAG, "Starting segment %d: '%s' — ramp %.0f°C/hr to %.0f°C, hold %d min",
             segment_idx, seg->name, seg->ramp_rate, seg->target_temp, seg->hold_time);
}

static void do_stop(void)
{
    safety_set_ssr(0.0f);
    pid_reset(&s_pid);
    progress_lock();
    s_progress.is_active = false;
    s_progress.status = FIRING_STATUS_IDLE;
    progress_unlock();
    ESP_LOGI(TAG, "Firing stopped");
}

void firing_task(void *param)
{
    (void)param;
    TickType_t last_wake = xTaskGetTickCount();
    int64_t last_compute_us = esp_timer_get_time();

    ESP_LOGI(TAG, "firing_task started");

    for (;;) {
        /* Process commands */
        firing_cmd_t cmd;
        while (xQueueReceive(s_cmd_queue, &cmd, 0) == pdTRUE) {
            switch (cmd.type) {
            case FIRING_CMD_START:
                s_active_profile = cmd.start.profile;
                {
                    thermocouple_reading_t r;
                    thermocouple_get_latest(&r);
                    start_segment(0, r.temperature_c);
                }
                pid_reset(&s_pid);
                progress_lock();
                s_progress.is_active = true;
                s_progress.status = FIRING_STATUS_HEATING;
                strncpy(s_progress.profile_id, s_active_profile.id, FIRING_ID_LEN - 1);
                s_progress.current_segment = 0;
                s_progress.total_segments = s_active_profile.segment_count;
                s_progress.elapsed_time = 0;
                progress_unlock();
                ESP_LOGI(TAG, "Firing started: %s", s_active_profile.name);
                break;

            case FIRING_CMD_STOP:
                do_stop();
                break;

            case FIRING_CMD_PAUSE:
                progress_lock();
                if (s_progress.is_active && s_progress.status != FIRING_STATUS_PAUSED) {
                    s_progress.status = FIRING_STATUS_PAUSED;
                    safety_set_ssr(0.0f);
                    ESP_LOGI(TAG, "Firing paused");
                }
                progress_unlock();
                break;

            case FIRING_CMD_RESUME:
                progress_lock();
                if (s_progress.status == FIRING_STATUS_PAUSED) {
                    s_progress.status = s_holding ? FIRING_STATUS_HOLDING : FIRING_STATUS_HEATING;
                    ESP_LOGI(TAG, "Firing resumed");
                }
                progress_unlock();
                break;

            case FIRING_CMD_AUTOTUNE_START:
                pid_autotune_start(&s_autotune, cmd.autotune.setpoint, cmd.autotune.hysteresis);
                progress_lock();
                s_progress.is_active = true;
                s_progress.status = FIRING_STATUS_AUTOTUNE;
                s_progress.elapsed_time = 0;
                progress_unlock();
                ESP_LOGI(TAG, "Auto-tune mode started");
                break;

            case FIRING_CMD_AUTOTUNE_STOP:
                pid_autotune_cancel(&s_autotune);
                do_stop();
                break;
            }
        }

        /* Get current temperature */
        thermocouple_reading_t reading;
        thermocouple_get_latest(&reading);
        float current_temp = reading.temperature_c;

        /* Compute dt */
        int64_t now_us = esp_timer_get_time();
        float dt_s = (float)(now_us - last_compute_us) / 1000000.0f;
        last_compute_us = now_us;

        /* Check for emergency stop */
        if (safety_is_emergency()) {
            progress_lock();
            if (s_progress.is_active) {
                s_progress.is_active = false;
                s_progress.status = FIRING_STATUS_ERROR;
            }
            progress_unlock();
            safety_set_ssr(0.0f);
            vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000));
            continue;
        }

        progress_lock();
        firing_status_t status = s_progress.status;
        bool active = s_progress.is_active;
        int seg_idx = s_progress.current_segment;
        s_progress.current_temp = current_temp;
        progress_unlock();

        if (!active || status == FIRING_STATUS_PAUSED || status == FIRING_STATUS_IDLE ||
            status == FIRING_STATUS_COMPLETE || status == FIRING_STATUS_ERROR) {
            if (status != FIRING_STATUS_PAUSED) {
                safety_set_ssr(0.0f);
            }
            vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000));
            continue;
        }

        /* Auto-tune mode */
        if (status == FIRING_STATUS_AUTOTUNE) {
            float output;
            bool done = pid_autotune_update(&s_autotune, current_temp, &output);
            safety_set_ssr(output);

            progress_lock();
            s_progress.elapsed_time += (uint32_t)dt_s;
            s_progress.target_temp = s_autotune.setpoint;
            progress_unlock();

            if (done) {
                if (pid_autotune_is_complete(&s_autotune)) {
                    /* Save tuned gains */
                    pid_save_gains(s_autotune.kp_result, s_autotune.ki_result, s_autotune.kd_result);
                    pid_init(&s_pid, s_autotune.kp_result, s_autotune.ki_result, s_autotune.kd_result,
                             0.0f, 1.0f);
                    ESP_LOGI(TAG, "Auto-tune gains applied");
                }
                do_stop();
            }
            vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000));
            continue;
        }

        /* Normal firing: PID control + state machine */
        firing_segment_t *seg = &s_active_profile.segments[seg_idx];

        /* Compute dynamic setpoint based on ramp rate */
        float setpoint;
        if (s_holding) {
            setpoint = seg->target_temp;
        } else {
            float elapsed_seg_s = (float)(now_us - s_segment_start_time_us) / 1000000.0f;
            float ramp_per_sec = seg->ramp_rate / 3600.0f;
            setpoint = s_segment_start_temp + ramp_per_sec * elapsed_seg_s;

            /* Clamp to target */
            if (seg->ramp_rate >= 0) {
                if (setpoint > seg->target_temp) setpoint = seg->target_temp;
            } else {
                if (setpoint < seg->target_temp) setpoint = seg->target_temp;
            }
        }

        /* PID compute */
        float output = pid_compute(&s_pid, setpoint, current_temp, dt_s);
        safety_set_ssr(output);

        /* Check segment transitions */
        bool at_target = fabsf(current_temp - seg->target_temp) < 2.0f &&
                         fabsf(setpoint - seg->target_temp) < 0.5f;

        if (!s_holding && at_target) {
            /* Start hold phase */
            s_holding = true;
            s_segment_hold_start_time_s = (float)(now_us) / 1000000.0f;
            progress_lock();
            s_progress.status = FIRING_STATUS_HOLDING;
            progress_unlock();
            ESP_LOGI(TAG, "Segment %d: holding at %.0f°C for %d min", seg_idx, seg->target_temp, seg->hold_time);
        }

        if (s_holding) {
            float hold_elapsed_s = (float)(now_us) / 1000000.0f - s_segment_hold_start_time_s;
            float hold_needed_s = seg->hold_time * 60.0f;

            if (hold_elapsed_s >= hold_needed_s) {
                /* Hold complete — advance to next segment */
                int next_seg = seg_idx + 1;
                if (next_seg >= s_active_profile.segment_count) {
                    /* Firing complete */
                    safety_set_ssr(0.0f);
                    progress_lock();
                    s_progress.is_active = false;
                    s_progress.status = FIRING_STATUS_COMPLETE;
                    progress_unlock();
                    xEventGroupSetBits(safety_get_event_group(), SAFETY_BIT_FIRING_COMPLETE);
                    ESP_LOGI(TAG, "Firing complete!");
                } else {
                    start_segment(next_seg, current_temp);
                    progress_lock();
                    s_progress.current_segment = next_seg;
                    /* Determine if next segment is heating or cooling */
                    if (s_active_profile.segments[next_seg].ramp_rate >= 0) {
                        s_progress.status = FIRING_STATUS_HEATING;
                    } else {
                        s_progress.status = FIRING_STATUS_COOLING;
                    }
                    progress_unlock();
                }
            }
        }

        /* Update progress timing */
        progress_lock();
        s_progress.elapsed_time += (uint32_t)dt_s;
        s_progress.target_temp = setpoint;
        if (s_active_profile.estimated_duration > 0) {
            uint32_t est_total_s = s_active_profile.estimated_duration * 60;
            s_progress.estimated_remaining =
                (s_progress.elapsed_time < est_total_s) ?
                (est_total_s - s_progress.elapsed_time) : 0;
        }
        progress_unlock();

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000));
    }
}
