#include "firing_engine.h"
#include "app_config.h"
#include "thermocouple.h"
#include "pid_control.h"
#include "safety.h"
#include "firing_history.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <string.h>
#include <math.h>
#include <time.h>

static const char *TAG = "firing_engine";

#define NVS_NS_PROFILES  "profiles"
#define NVS_NS_SETTINGS  "kiln_set"
#define NVS_KEY_INDEX    "idx"
#define NVS_KEY_ELEM_HRS "elem_hrs"

/* Shared state */
static firing_progress_t s_progress;
static SemaphoreHandle_t s_progress_mutex;

static kiln_settings_t s_settings;
static SemaphoreHandle_t s_settings_mutex;

static QueueHandle_t s_cmd_queue;
static QueueHandle_t s_event_queue;

/* PID controller */
static pid_controller_t s_pid;

/* Auto-tune state */
static pid_autotune_t s_autotune;

/* Last error code */
static firing_error_code_t s_last_error_code = FIRING_ERR_NONE;

/* Accumulated element-on seconds (SSR duty > 0), persisted to NVS */
static uint32_t s_element_on_s = 0;

/* ── Internal helpers ──────────────────────────────── */

static void progress_lock(void)
{
    xSemaphoreTake(s_progress_mutex, portMAX_DELAY);
}
static void progress_unlock(void)
{
    xSemaphoreGive(s_progress_mutex);
}
static void settings_lock(void)
{
    xSemaphoreTake(s_settings_mutex, portMAX_DELAY);
}
static void settings_unlock(void)
{
    xSemaphoreGive(s_settings_mutex);
}

/* ── Default Profiles ──────────────────────────────── */

static const firing_profile_t s_default_profiles[] = {
    {.id = "bisque-04",
     .name = "Bisque Cone 04",
     .description = "Standard bisque firing to cone 04",
     .segment_count = 3,
     .max_temp = 1060.0f,
     .estimated_duration = 540,
     .segments =
         {
             {.id = "1", .name = "Warm-up", .ramp_rate = 100.0f, .target_temp = 200.0f, .hold_time = 60},
             {.id = "2", .name = "Water smoke", .ramp_rate = 50.0f, .target_temp = 600.0f, .hold_time = 30},
             {.id = "3", .name = "Ramp to top", .ramp_rate = 150.0f, .target_temp = 1060.0f, .hold_time = 15},
         }},
    {.id = "glaze-6",
     .name = "Glaze Cone 6",
     .description = "Mid-fire glaze for stoneware",
     .segment_count = 3,
     .max_temp = 1222.0f,
     .estimated_duration = 480,
     .segments =
         {
             {.id = "1", .name = "Initial heat", .ramp_rate = 150.0f, .target_temp = 600.0f, .hold_time = 0},
             {.id = "2", .name = "Medium ramp", .ramp_rate = 100.0f, .target_temp = 1000.0f, .hold_time = 0},
             {.id = "3", .name = "Final ramp", .ramp_rate = 80.0f, .target_temp = 1222.0f, .hold_time = 10},
         }},
    {.id = "glaze-10",
     .name = "Glaze Cone 10",
     .description = "High-fire glaze for porcelain",
     .segment_count = 3,
     .max_temp = 1305.0f,
     .estimated_duration = 600,
     .segments =
         {
             {.id = "1", .name = "Low heat", .ramp_rate = 120.0f, .target_temp = 500.0f, .hold_time = 0},
             {.id = "2", .name = "Medium heat", .ramp_rate = 150.0f, .target_temp = 1000.0f, .hold_time = 15},
             {.id = "3", .name = "High heat", .ramp_rate = 100.0f, .target_temp = 1305.0f, .hold_time = 20},
         }},
    {.id = "low-fire",
     .name = "Low Fire Cone 06",
     .description = "Low temp for earthenware and decals",
     .segment_count = 2,
     .max_temp = 999.0f,
     .estimated_duration = 420,
     .segments =
         {
             {.id = "1", .name = "Warm-up", .ramp_rate = 100.0f, .target_temp = 400.0f, .hold_time = 30},
             {.id = "2", .name = "Ramp to top", .ramp_rate = 120.0f, .target_temp = 999.0f, .hold_time = 10},
         }},
    {.id = "crystalline",
     .name = "Crystalline Glaze",
     .description = "Controlled cooling for crystal growth",
     .segment_count = 3,
     .max_temp = 1260.0f,
     .estimated_duration = 720,
     .segments =
         {
             {.id = "1", .name = "Initial ramp", .ramp_rate = 200.0f, .target_temp = 1260.0f, .hold_time = 30},
             {.id = "2", .name = "Crystal growth", .ramp_rate = -200.0f, .target_temp = 1100.0f, .hold_time = 120},
             {.id = "3", .name = "Cool down", .ramp_rate = -150.0f, .target_temp = 800.0f, .hold_time = 0},
         }},
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
    s_event_queue = xQueueCreate(4, sizeof(firing_event_t));

    if (!s_progress_mutex || !s_settings_mutex || !s_cmd_queue || !s_event_queue) {
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
    s_settings.tc_offset_c = 0.0f;
    s_settings.webhook_url[0] = '\0';
    s_settings.api_token[0] = '\0';
    s_settings.element_watts = 5000.0f;
    s_settings.electricity_cost_kwh = 0.15f;

    nvs_handle_t handle;
    if (nvs_open(NVS_NS_SETTINGS, NVS_READONLY, &handle) == ESP_OK) {
        uint8_t u8;
        int32_t i32;
        size_t str_sz;
        if (nvs_get_u8(handle, "unit", &u8) == ESP_OK) {
            s_settings.temp_unit = (char)u8;
        }
        if (nvs_get_i32(handle, "max_temp", &i32) == ESP_OK) {
            s_settings.max_safe_temp = (float)i32;
        }
        if (nvs_get_u8(handle, "alarm", &u8) == ESP_OK) {
            s_settings.alarm_enabled = u8;
        }
        if (nvs_get_u8(handle, "autoshut", &u8) == ESP_OK) {
            s_settings.auto_shutdown = u8;
        }
        if (nvs_get_u8(handle, "notif", &u8) == ESP_OK) {
            s_settings.notifications_enabled = u8;
        }
        /* TC offset stored as i32 * 100 */
        if (nvs_get_i32(handle, "tc_off", &i32) == ESP_OK) {
            s_settings.tc_offset_c = (float)i32 / 100.0f;
        }
        str_sz = sizeof(s_settings.webhook_url);
        nvs_get_str(handle, "webhook", s_settings.webhook_url, &str_sz);
        str_sz = sizeof(s_settings.api_token);
        nvs_get_str(handle, "api_tok", s_settings.api_token, &str_sz);
        if (nvs_get_i32(handle, "elem_w", &i32) == ESP_OK) {
            s_settings.element_watts = (float)i32;
        }
        if (nvs_get_i32(handle, "elec_c", &i32) == ESP_OK) {
            s_settings.electricity_cost_kwh = (float)i32 / 1000.0f;
        }
        nvs_close(handle);
    }

    /* Load accumulated element hours */
    nvs_handle_t nvs_diag;
    if (nvs_open("kiln_diag", NVS_READONLY, &nvs_diag) == ESP_OK) {
        uint32_t u32;
        if (nvs_get_u32(nvs_diag, NVS_KEY_ELEM_HRS, &u32) == ESP_OK) {
            s_element_on_s = u32;
        }
        nvs_close(nvs_diag);
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

QueueHandle_t firing_engine_get_event_queue(void)
{
    return s_event_queue;
}

static void emit_event(firing_event_kind_t kind, float peak_temp, uint32_t duration_s)
{
    firing_event_t evt = {
        .kind = kind,
        .peak_temp = peak_temp,
        .duration_s = duration_s,
    };
    progress_lock();
    strncpy(evt.profile_id, s_progress.profile_id, FIRING_ID_LEN - 1);
    evt.profile_id[FIRING_ID_LEN - 1] = '\0';
    progress_unlock();

    if (xQueueSend(s_event_queue, &evt, 0) != pdTRUE) {
        ESP_LOGW(TAG, "event queue full, dropping %s", kind == FIRING_EVENT_COMPLETE ? "complete" : "error");
    }
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

firing_error_code_t firing_engine_get_error_code(void)
{
    return s_last_error_code;
}

uint32_t firing_engine_get_element_hours_s(void)
{
    return s_element_on_s;
}

static void save_element_hours(void)
{
    nvs_handle_t handle;
    if (nvs_open("kiln_diag", NVS_READWRITE, &handle) == ESP_OK) {
        nvs_set_u32(handle, NVS_KEY_ELEM_HRS, s_element_on_s);
        nvs_commit(handle);
        nvs_close(handle);
    }
}

esp_err_t firing_engine_set_settings(const kiln_settings_t *settings)
{
    /* Clamp max_safe_temp to hardware limit */
    kiln_settings_t safe = *settings;
    if (safe.max_safe_temp > APP_HARDWARE_MAX_TEMP_C) {
        safe.max_safe_temp = APP_HARDWARE_MAX_TEMP_C;
    }
    if (safe.max_safe_temp < 100.0f) {
        safe.max_safe_temp = 100.0f;
    }

    settings_lock();
    s_settings = safe;
    settings_unlock();

    /* Update safety module */
    safety_set_max_temp(safe.max_safe_temp);

    /* Persist to NVS */
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_SETTINGS, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }

    nvs_set_u8(handle, "unit", (uint8_t)safe.temp_unit);
    nvs_set_i32(handle, "max_temp", (int32_t)safe.max_safe_temp);
    nvs_set_u8(handle, "alarm", safe.alarm_enabled ? 1 : 0);
    nvs_set_u8(handle, "autoshut", safe.auto_shutdown ? 1 : 0);
    nvs_set_u8(handle, "notif", safe.notifications_enabled ? 1 : 0);
    nvs_set_i32(handle, "tc_off", (int32_t)(safe.tc_offset_c * 100.0f));
    nvs_set_str(handle, "webhook", safe.webhook_url);
    nvs_set_str(handle, "api_tok", safe.api_token);
    nvs_set_i32(handle, "elem_w", (int32_t)safe.element_watts);
    nvs_set_i32(handle, "elec_c", (int32_t)(safe.electricity_cost_kwh * 1000.0f));
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
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) {
            key[i] = '_';
        }
    }
}

static int load_profile_index(nvs_handle_t handle, char ids[][FIRING_ID_LEN])
{
    size_t idx_size = FIRING_MAX_PROFILES * FIRING_ID_LEN;
    if (nvs_get_blob(handle, NVS_KEY_INDEX, ids, &idx_size) == ESP_OK) {
        return (int)(idx_size / FIRING_ID_LEN);
    }
    return 0;
}

esp_err_t firing_engine_save_profile(const firing_profile_t *profile)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_PROFILES, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }

    char key[16];
    make_nvs_key(profile->id, key, sizeof(key));

    err = nvs_set_blob(handle, key, profile, sizeof(firing_profile_t));
    if (err != ESP_OK) {
        nvs_close(handle);
        return err;
    }

    /* Update index: load existing, add if not present */
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    int count = load_profile_index(handle, ids);

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
    if (err != ESP_OK) {
        return err;
    }

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
    if (err != ESP_OK) {
        return err;
    }

    char key[16];
    make_nvs_key(id, key, sizeof(key));
    nvs_erase_key(handle, key);

    /* Remove from index */
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    int count = load_profile_index(handle, ids);

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
    int count = load_profile_index(handle, ids);
    nvs_close(handle);

    int result = (count < max_count) ? count : max_count;
    memcpy(ids_out, ids, result * FIRING_ID_LEN);
    return result;
}

float firing_planned_temp_at(const firing_profile_t *profile, uint32_t t_seconds, float start_temp)
{
    if (!profile || profile->segment_count == 0) {
        return start_temp;
    }

    float seg_start_temp = start_temp;
    uint32_t cumulative_s = 0;

    for (int i = 0; i < profile->segment_count; i++) {
        const firing_segment_t *seg = &profile->segments[i];

        float ramp_per_sec = seg->ramp_rate / 3600.0f;
        uint32_t ramp_dur_s = 0;
        if (fabsf(ramp_per_sec) > 0.0001f) {
            float delta = seg->target_temp - seg_start_temp;
            ramp_dur_s = (uint32_t)fabsf(delta / ramp_per_sec);
        }
        uint32_t hold_dur_s = (seg->hold_time == FIRING_HOLD_INDEFINITE) ? 0u : (uint32_t)seg->hold_time * 60u;
        uint32_t seg_total_s = ramp_dur_s + hold_dur_s;

        if (t_seconds < cumulative_s + ramp_dur_s) {
            uint32_t in_seg = t_seconds - cumulative_s;
            return seg_start_temp + ramp_per_sec * (float)in_seg;
        }
        if (t_seconds < cumulative_s + seg_total_s) {
            return seg->target_temp;
        }

        cumulative_s += seg_total_s;
        seg_start_temp = seg->target_temp;
    }

    return seg_start_temp;
}

/* ── Firing Task ───────────────────────────────────── */

/* State for active firing */
static firing_profile_t s_active_profile;
static int64_t s_segment_start_time_us;
static float s_segment_start_temp;
static float s_segment_hold_start_time_s;
static bool s_holding;

/* Delay-start state */
static int64_t s_delay_start_end_us = 0;
static bool s_delay_active = false;

/* Safety tracking for kiln-not-rising and rate-of-rise runaway */
static float s_check_start_temp = 0.0f;
static int64_t s_check_start_time_us = 0;
#define RISING_CHECK_INTERVAL_US (15LL * 60 * 1000000) /* 15 minutes */
#define RISING_THRESHOLD_C       10.0f                 /* must rise ≥10°C */
#define RUNAWAY_RATE_MULTIPLIER  2.0f                  /* alert if rate > 2× programmed */

/* History: record temperature once per minute */
static int64_t s_last_history_sample_us = 0;
#define HISTORY_SAMPLE_INTERVAL_US (60LL * 1000000)

/* Element hours: accumulate SSR-on time */
static int64_t s_last_elem_save_us = 0;
#define ELEM_SAVE_INTERVAL_US (5LL * 60 * 1000000) /* save every 5 min */

static void start_segment(int segment_idx, float current_temp)
{
    s_segment_start_time_us = esp_timer_get_time();
    s_segment_start_temp = current_temp;
    s_holding = false;
    s_segment_hold_start_time_s = 0;

    firing_segment_t *seg = &s_active_profile.segments[segment_idx];
    ESP_LOGI(TAG, "Starting segment %d: '%s' — ramp %.0f°C/hr to %.0f°C, hold %d min", segment_idx, seg->name,
             seg->ramp_rate, seg->target_temp, seg->hold_time);
}

static void begin_firing(float cur_temp, int64_t now_us)
{
    start_segment(0, cur_temp);
    pid_reset(&s_pid);
    s_check_start_temp = cur_temp;
    s_check_start_time_us = now_us;
    s_last_history_sample_us = now_us;
    history_firing_start(s_active_profile.id, s_active_profile.name);
    progress_lock();
    s_progress.status = FIRING_STATUS_HEATING;
    progress_unlock();
}

static void complete_firing(float peak, uint32_t dur, bool save_elem_hrs)
{
    safety_set_ssr(0.0f);
    progress_lock();
    s_progress.is_active = false;
    s_progress.status = FIRING_STATUS_COMPLETE;
    progress_unlock();
    history_firing_end(HISTORY_OUTCOME_COMPLETE, peak, dur, 0);
    if (save_elem_hrs) {
        save_element_hours();
    }
    xEventGroupSetBits(safety_get_event_group(), SAFETY_BIT_FIRING_COMPLETE);
    emit_event(FIRING_EVENT_COMPLETE, peak, dur);
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

static void handle_cmd(const firing_cmd_t *cmd)
{
    switch (cmd->type) {
    case FIRING_CMD_START: {
        /* Defense in depth: refuse to overwrite an active firing.
           The HTTP layer also gates this, but other callers (display
           modal, future internal callers) bypass that path. */
        progress_lock();
        bool already_active = s_progress.is_active;
        progress_unlock();
        if (already_active || s_delay_active) {
            ESP_LOGW(TAG, "START rejected: firing already active");
            break;
        }

        /* Sanity-check the profile so a malformed one never reaches
           begin_firing(). The HTTP validator is stricter; these are
           the floor any caller must clear. */
        const firing_profile_t *np = &cmd->start.profile;
        if (np->segment_count == 0 || np->segment_count > FIRING_MAX_SEGMENTS) {
            ESP_LOGW(TAG, "START rejected: bad segment_count=%u", np->segment_count);
            break;
        }
        float max_safe = safety_get_max_temp();
        bool seg_ok = true;
        for (uint8_t i = 0; i < np->segment_count; i++) {
            float t = np->segments[i].target_temp;
            float r_rate = np->segments[i].ramp_rate;
            if (!isfinite(t) || t <= 0.0f || t > max_safe || !isfinite(r_rate) || r_rate == 0.0f) {
                ESP_LOGW(TAG, "START rejected: segment %u invalid (target=%.1f rate=%.1f)", i, t, r_rate);
                seg_ok = false;
                break;
            }
        }
        if (!seg_ok) {
            break;
        }

        /* Release any prior soft emergency stop (NOT_RISING, RUNAWAY, ...).
           safety_task re-trips within 500 ms if a persistent fault (TC fault,
           over-temp) is still active, so this only clears stale latched trips. */
        safety_clear_emergency();

        s_active_profile = cmd->start.profile;
        thermocouple_reading_t r;
        thermocouple_get_latest(&r);
        float cur_temp = r.temperature_c;

        kiln_settings_t settings;
        firing_engine_get_settings(&settings);
        cur_temp += settings.tc_offset_c;

        s_delay_active = false;
        if (cmd->start.delay_minutes > 0) {
            s_delay_start_end_us = esp_timer_get_time() + (int64_t)cmd->start.delay_minutes * 60 * 1000000LL;
            s_delay_active = true;
            progress_lock();
            s_progress.is_active = true;
            s_progress.status = FIRING_STATUS_IDLE; /* show as idle during delay */
            strncpy(s_progress.profile_id, s_active_profile.id, FIRING_ID_LEN - 1);
            s_progress.current_segment = 0;
            s_progress.total_segments = s_active_profile.segment_count;
            s_progress.elapsed_time = 0;
            progress_unlock();
            ESP_LOGI(TAG, "Firing queued with %u min delay: %s", cmd->start.delay_minutes,
                     s_active_profile.name);
        } else {
            progress_lock();
            s_progress.is_active = true;
            strncpy(s_progress.profile_id, s_active_profile.id, FIRING_ID_LEN - 1);
            s_progress.current_segment = 0;
            s_progress.total_segments = s_active_profile.segment_count;
            s_progress.elapsed_time = 0;
            progress_unlock();
            begin_firing(cur_temp, esp_timer_get_time());
            ESP_LOGI(TAG, "Firing started: %s", s_active_profile.name);
        }
        s_last_error_code = FIRING_ERR_NONE;
        break;
    }

    case FIRING_CMD_STOP: {
        bool was_active;
        progress_lock();
        was_active = s_progress.is_active;
        float peak = s_progress.current_temp;
        uint32_t dur = s_progress.elapsed_time;
        progress_unlock();
        if (was_active) {
            history_firing_end(HISTORY_OUTCOME_ABORTED, peak, dur, 0);
        }
        s_delay_active = false;
        do_stop();
        break;
    }

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

    case FIRING_CMD_SKIP_SEGMENT: {
        progress_lock();
        bool active = s_progress.is_active;
        int seg_idx = s_progress.current_segment;
        int total = s_progress.total_segments;
        float cur = s_progress.current_temp;
        progress_unlock();

        if (active && seg_idx + 1 < total) {
            int next = seg_idx + 1;
            start_segment(next, cur);
            progress_lock();
            s_progress.current_segment = next;
            s_progress.status = (s_active_profile.segments[next].ramp_rate >= 0) ? FIRING_STATUS_HEATING
                                                                                 : FIRING_STATUS_COOLING;
            progress_unlock();
            ESP_LOGI(TAG, "Skipped to segment %d", next);
        } else if (active && seg_idx + 1 >= total) {
            /* Skip last segment → firing complete */
            progress_lock();
            float peak = s_progress.current_temp;
            uint32_t dur = s_progress.elapsed_time;
            progress_unlock();
            complete_firing(peak, dur, false);
        }
        break;
    }

    case FIRING_CMD_AUTOTUNE_START:
        pid_autotune_start(&s_autotune, cmd->autotune.setpoint, cmd->autotune.hysteresis);
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

/* Block on the command queue until the next 1 Hz deadline, dispatching any
 * commands that arrive in the meantime. Keeps PID cadence anchored to
 * *last_wake while giving commands ms-level latency instead of up to 1 s. */
static void wait_until_next_tick(TickType_t *last_wake)
{
    TickType_t deadline = *last_wake + pdMS_TO_TICKS(1000);
    firing_cmd_t cmd;
    for (;;) {
        TickType_t now = xTaskGetTickCount();
        int32_t remaining = (int32_t)(deadline - now);
        if (remaining <= 0) break;
        if (xQueueReceive(s_cmd_queue, &cmd, (TickType_t)remaining) != pdTRUE) break;
        handle_cmd(&cmd);
    }
    *last_wake = deadline;
}

void firing_task(void *param)
{
    (void)param;
    TickType_t last_wake = xTaskGetTickCount();
    int64_t last_compute_us = esp_timer_get_time();

    ESP_LOGI(TAG, "firing_task started");

    for (;;) {
        /* Handle delay-start countdown */
        if (s_delay_active) {
            int64_t now_us = esp_timer_get_time();
            if (now_us >= s_delay_start_end_us) {
                s_delay_active = false;
                thermocouple_reading_t r;
                thermocouple_get_latest(&r);
                kiln_settings_t st;
                firing_engine_get_settings(&st);
                float cur_temp = r.temperature_c + st.tc_offset_c;
                begin_firing(cur_temp, now_us);
                last_compute_us = now_us;
                ESP_LOGI(TAG, "Delay expired, firing started: %s", s_active_profile.name);
            } else {
                /* Keep vent in sync while waiting for delay to expire. */
                thermocouple_reading_t r;
                thermocouple_get_latest(&r);
                safety_update_vent(true, r.temperature_c);
                wait_until_next_tick(&last_wake);
                continue;
            }
        }

        /* Get current temperature (with TC offset applied) */
        thermocouple_reading_t reading;
        thermocouple_get_latest(&reading);
        settings_lock();
        float tc_offset = s_settings.tc_offset_c;
        settings_unlock();
        float current_temp = reading.temperature_c + tc_offset;

        /* Drive vent relay once per tick (cheap GPIO write). */
        progress_lock();
        bool vent_active = s_progress.is_active;
        progress_unlock();
        safety_update_vent(vent_active, current_temp);

        /* Compute dt */
        int64_t now_us = esp_timer_get_time();
        float dt_s = (float)(now_us - last_compute_us) / 1000000.0f;
        last_compute_us = now_us;

        /* Check for emergency stop */
        if (safety_is_emergency()) {
            progress_lock();
            if (s_progress.is_active) {
                float peak = s_progress.current_temp;
                uint32_t dur = s_progress.elapsed_time;
                s_progress.is_active = false;
                s_progress.status = FIRING_STATUS_ERROR;
                progress_unlock();
                if (s_last_error_code == FIRING_ERR_NONE) {
                    s_last_error_code = FIRING_ERR_EMERGENCY_STOP;
                }
                history_firing_end(HISTORY_OUTCOME_ERROR, peak, dur, (int)s_last_error_code);
                emit_event(FIRING_EVENT_ERROR, peak, dur);
            } else {
                progress_unlock();
            }
            safety_set_ssr(0.0f);
            wait_until_next_tick(&last_wake);
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
            wait_until_next_tick(&last_wake);
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
                    pid_init(&s_pid, s_autotune.kp_result, s_autotune.ki_result, s_autotune.kd_result, 0.0f, 1.0f);
                    ESP_LOGI(TAG, "Auto-tune gains applied");
                }
                do_stop();
            }
            wait_until_next_tick(&last_wake);
            continue;
        }

        /* Normal firing: PID control + state machine */
        firing_segment_t *seg = &s_active_profile.segments[seg_idx];

        /* ── Safety: kiln-not-rising check ──────────────────────────────── */
        if (status == FIRING_STATUS_HEATING && !s_holding) {
            if ((now_us - s_check_start_time_us) >= RISING_CHECK_INTERVAL_US) {
                float temp_rise = current_temp - s_check_start_temp;
                if (temp_rise < RISING_THRESHOLD_C) {
                    ESP_LOGE(TAG, "Kiln not rising: only %.1f°C in 15 min (need %.0f°C)", temp_rise,
                             RISING_THRESHOLD_C);
                    s_last_error_code = FIRING_ERR_NOT_RISING;
                    safety_emergency_stop();
                }
                /* Reset window */
                s_check_start_temp = current_temp;
                s_check_start_time_us = now_us;
            }
        }

        /* ── Safety: rate-of-rise runaway check ──────────────────────────── */
        if (status == FIRING_STATUS_HEATING && !s_holding && fabsf(seg->ramp_rate) > 0.1f) {
            float elapsed_seg_s = (float)(now_us - s_segment_start_time_us) / 1000000.0f;
            if (elapsed_seg_s > 300.0f) { /* Only check after 5 minutes in segment */
                float actual_rate_c_hr = ((current_temp - s_segment_start_temp) / elapsed_seg_s) * 3600.0f;
                if (actual_rate_c_hr > seg->ramp_rate * RUNAWAY_RATE_MULTIPLIER &&
                    actual_rate_c_hr > 50.0f) { /* Ignore when rate < 50°C/hr (noise) */
                    ESP_LOGE(TAG, "Runaway: actual rate %.0f°C/hr vs programmed %.0f°C/hr", actual_rate_c_hr,
                             seg->ramp_rate);
                    s_last_error_code = FIRING_ERR_RUNAWAY;
                    safety_emergency_stop();
                }
            }
        }

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
                if (setpoint > seg->target_temp) {
                    setpoint = seg->target_temp;
                }
            } else {
                if (setpoint < seg->target_temp) {
                    setpoint = seg->target_temp;
                }
            }
        }

        /* PID compute */
        float output = pid_compute(&s_pid, setpoint, current_temp, dt_s);
        safety_set_ssr(output);

        /* Accumulate element-on time */
        if (output > 0.0f) {
            s_element_on_s += (uint32_t)dt_s;
            if ((now_us - s_last_elem_save_us) >= ELEM_SAVE_INTERVAL_US) {
                save_element_hours();
                s_last_elem_save_us = now_us;
            }
        }

        /* History: record temperature once per minute */
        if ((now_us - s_last_history_sample_us) >= HISTORY_SAMPLE_INTERVAL_US) {
            history_record_temp(current_temp);
            s_last_history_sample_us = now_us;
        }

        /* Check segment transitions */
        bool at_target = fabsf(current_temp - seg->target_temp) < 2.0f && fabsf(setpoint - seg->target_temp) < 0.5f;

        if (!s_holding && at_target) {
            /* Reached target. hold_time == 0 → pass through (advance next iteration via
               hold_done below). FIRING_HOLD_INDEFINITE → wait for SKIP_SEGMENT. */
            s_holding = true;
            s_segment_hold_start_time_s = (float)(now_us) / 1000000.0f;
            progress_lock();
            s_progress.status = FIRING_STATUS_HOLDING;
            progress_unlock();
            if (seg->hold_time == FIRING_HOLD_INDEFINITE) {
                ESP_LOGI(TAG, "Segment %d: holding at %.0f°C indefinitely (tap skip to advance)", seg_idx,
                         seg->target_temp);
            } else if (seg->hold_time == 0) {
                ESP_LOGI(TAG, "Segment %d: reached %.0f°C, advancing", seg_idx, seg->target_temp);
            } else {
                ESP_LOGI(TAG, "Segment %d: holding at %.0f°C for %d min", seg_idx, seg->target_temp, seg->hold_time);
            }
        }

        if (s_holding) {
            float hold_elapsed_s = (float)(now_us) / 1000000.0f - s_segment_hold_start_time_s;
            bool infinite_hold = (seg->hold_time == FIRING_HOLD_INDEFINITE);
            float hold_needed_s = infinite_hold ? 0.0f : (float)seg->hold_time * 60.0f;

            /* FIRING_HOLD_INDEFINITE waits for SKIP_SEGMENT; any finite duration (incl. 0) advances when elapsed. */
            bool hold_done = !infinite_hold && (hold_elapsed_s >= hold_needed_s);

            if (hold_done) {
                /* Hold complete — advance to next segment */
                int next_seg = seg_idx + 1;
                if (next_seg >= s_active_profile.segment_count) {
                    /* Firing complete */
                    safety_set_ssr(0.0f);
                    progress_lock();
                    float peak = s_progress.current_temp;
                    uint32_t dur = s_progress.elapsed_time;
                    s_progress.is_active = false;
                    s_progress.status = FIRING_STATUS_COMPLETE;
                    progress_unlock();
                    history_firing_end(HISTORY_OUTCOME_COMPLETE, peak, dur, 0);
                    save_element_hours();
                    xEventGroupSetBits(safety_get_event_group(), SAFETY_BIT_FIRING_COMPLETE);
                    emit_event(FIRING_EVENT_COMPLETE, peak, dur);
                    ESP_LOGI(TAG, "Firing complete!");
                } else {
                    start_segment(next_seg, current_temp);
                    s_check_start_temp = current_temp;
                    s_check_start_time_us = now_us;
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
                (s_progress.elapsed_time < est_total_s) ? (est_total_s - s_progress.elapsed_time) : 0;
        }
        progress_unlock();

        wait_until_next_tick(&last_wake);
    }
}
