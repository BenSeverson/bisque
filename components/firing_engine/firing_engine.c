#include "firing_engine.h"
#include "firing_engine_internal.h"
#include "app_config.h"
#include "thermocouple.h"
#include "pid_control.h"
#include "safety.h"
#include "firing_history.h"
#include "ota_manager.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <stdio.h>
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

/* Accumulated element-on time (SSR duty > 0), persisted to NVS as whole
 * seconds. The fine-grained accumulator sums raw int64 µs deltas so sub-second
 * per-tick jitter isn't truncated away (the same reason elapsed time uses a µs
 * accumulator); s_element_on_s is published as floor(accum_us / 1e6). */
static uint32_t s_element_on_s = 0;
static uint64_t s_element_on_accum_us = 0;

/* ── Internal helpers ──────────────────────────────── */

/* Map a safety trip cause onto the firing error code shown in the UI. */
static firing_error_code_t firing_err_from_trip(safety_trip_cause_t cause)
{
    switch (cause) {
    case SAFETY_TRIP_TC_FAULT:
        return FIRING_ERR_TC_FAULT;
    case SAFETY_TRIP_OVER_TEMP:
        return FIRING_ERR_OVER_TEMP;
    default:
        return FIRING_ERR_EMERGENCY_STOP;
    }
}

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
    s_settings.temp_unit = 'F';
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
    s_element_on_accum_us = (uint64_t)s_element_on_s * 1000000ULL;

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

char firing_engine_get_temp_unit(void)
{
    settings_lock();
    char unit = s_settings.temp_unit;
    settings_unlock();
    return unit;
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
    safety_set_tc_offset(safe.tc_offset_c);

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

    /* NVS keys are capped at 15 chars, so two different profile IDs can map to
       the same key and would otherwise share one blob — silently overwriting
       each other while both show up in the index. Load the index first and
       reject a save whose key collides with a *different* stored ID. */
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    int count = load_profile_index(handle, ids);

    bool found = false;
    for (int i = 0; i < count; i++) {
        if (strcmp(ids[i], profile->id) == 0) {
            found = true;
            continue;
        }
        char other_key[16];
        make_nvs_key(ids[i], other_key, sizeof(other_key));
        if (strcmp(other_key, key) == 0) {
            nvs_close(handle);
            ESP_LOGW(TAG, "Profile '%s' NVS key collides with existing '%s'; rejecting save", profile->id, ids[i]);
            return ESP_ERR_INVALID_STATE;
        }
    }

    err = nvs_set_blob(handle, key, profile, sizeof(firing_profile_t));
    if (err != ESP_OK) {
        nvs_close(handle);
        return err;
    }

    if (!found && count < FIRING_MAX_PROFILES) {
        snprintf(ids[count], FIRING_ID_LEN, "%s", profile->id);
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

#define RISING_CHECK_INTERVAL_US   (15LL * 60 * 1000000) /* 15 minutes */
#define RELAY_TEST_MAX_S           10                    /* upper bound on the diagnostic SSR pulse */
#define RISING_THRESHOLD_C         10.0f                 /* must rise ≥10°C */
#define RUNAWAY_RATE_MULTIPLIER    2.0f                  /* alert if rate > 2× programmed */
#define HISTORY_SAMPLE_INTERVAL_US (60LL * 1000000)
#define ELEM_SAVE_INTERVAL_US      (5LL * 60 * 1000000) /* save every 5 min */

/* Mutable state for an active firing. Grouped into one struct so a host test
 * harness can snapshot or reset everything in one place. The microsecond
 * accumulator deserves a note: the PID loop's per-tick dt is ~1.0s with
 * jitter; truncating each tick to whole seconds loses ~half of real time on
 * average, so we sum raw int64 us deltas and publish floor(s). */
typedef struct {
    /* Profile being executed (copied in on START). */
    firing_profile_t active_profile;

    /* Per-segment timing. */
    int64_t segment_start_time_us;
    float segment_start_temp;
    float segment_hold_start_time_s;
    bool holding;

    /* Highest temperature seen this firing — reported as the event peak (the
     * value at completion can be well below the peak for cool-down segments). */
    float peak_temp_c;

    /* Elapsed-time accumulator. */
    int64_t elapsed_accum_us;

    /* Delay-start. */
    int64_t delay_start_end_us;
    bool delay_active;

    /* Pause bookkeeping: wall-clock when the active firing was paused. On
     * resume the elapsed pause is added back to every time anchor below so the
     * pause doesn't count as firing time. */
    int64_t pause_start_us;

    /* Status the firing was in when PAUSE latched, restored verbatim by RESUME.
     * Reconstructing it instead (holding ? HOLDING : HEATING) loses both
     * AUTOTUNE — which resumes as a "normal firing" against a stale profile —
     * and COOLING, which resumes as HEATING and re-arms the heating watchdogs
     * against a deliberately falling setpoint. */
    firing_status_t pause_prev_status;

    /* Safety: kiln-not-rising window (also used for runaway baseline). */
    float check_start_temp;
    int64_t check_start_time_us;

    /* History sampling cadence. */
    int64_t last_history_sample_us;

    /* Element-hours flush cadence. */
    int64_t last_elem_save_us;
} firing_state_t;

static firing_state_t s_state;

/* Relay diagnostic pulse deadline (esp_timer µs); 0 = no test. Guarded by
   s_progress_mutex (progress_lock) rather than living in s_state, because it is
   armed synchronously from the httpd task and read/cleared from firing_task.
   The tick remains the only caller of safety_set_ssr() for the pulse, so the
   SSR keeps a single writer. */
static int64_t s_relay_test_end_us = 0;

bool firing_engine_relay_test_active(void)
{
    progress_lock();
    bool active = (s_relay_test_end_us != 0);
    progress_unlock();
    return active;
}

bool firing_engine_relay_test_arm(uint32_t duration_s)
{
    if (duration_s < 1) {
        duration_s = 1;
    }
    if (duration_s > RELAY_TEST_MAX_S) {
        duration_s = RELAY_TEST_MAX_S;
    }
    bool armed = false;
    progress_lock();
    /* is_active is true for a running firing, an armed delayed start, and
       autotune, so this one check excludes all of them. Doing the check and the
       arm in a single critical section makes acceptance synchronous and atomic:
       the caller gets a definitive yes/no with no queue-latency window, and two
       concurrent requests cannot both arm. */
    if (!s_progress.is_active && s_relay_test_end_us == 0) {
        s_relay_test_end_us = esp_timer_get_time() + (int64_t)duration_s * 1000000LL;
        armed = true;
    }
    progress_unlock();
    return armed;
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
    /* Carry the human-readable name too, so webhook payloads report e.g.
       "Bisque Cone 04" rather than the slug "bisque-04". */
    strncpy(evt.profile_name, s_state.active_profile.name, FIRING_NAME_LEN - 1);
    evt.profile_name[FIRING_NAME_LEN - 1] = '\0';

    if (xQueueSend(s_event_queue, &evt, 0) != pdTRUE) {
        ESP_LOGW(TAG, "event queue full, dropping %s", kind == FIRING_EVENT_COMPLETE ? "complete" : "error");
    }
}

static void start_segment(int segment_idx, float current_temp, int64_t now_us)
{
    s_state.segment_start_time_us = now_us;
    s_state.segment_start_temp = current_temp;
    s_state.holding = false;
    s_state.segment_hold_start_time_s = 0;

    /* Re-arm the not-rising / runaway baseline from this segment's actual
       starting conditions. Every entry into a segment must do this: the check
       is suppressed while holding and while cooling, so a baseline carried
       over from a previous segment is stale by construction and will compare
       "now" against a temperature from an unrelated window — tripping a false
       emergency stop on the first tick. Owned here so all three entry points
       (begin_firing, hold-complete advance, SKIP_SEGMENT) get it. */
    s_state.check_start_temp = current_temp;
    s_state.check_start_time_us = now_us;

    firing_segment_t *seg = &s_state.active_profile.segments[segment_idx];
    ESP_LOGI(TAG, "Starting segment %d: '%s' — ramp %.0f°C/hr to %.0f°C, hold %d min", segment_idx, seg->name,
             seg->ramp_rate, seg->target_temp, seg->hold_time);
}

static void begin_firing(float cur_temp, int64_t now_us)
{
    start_segment(0, cur_temp, now_us);
    pid_reset(&s_pid);
    s_state.last_history_sample_us = now_us;
    s_state.peak_temp_c = cur_temp;
    history_firing_start(s_state.active_profile.id, s_state.active_profile.name);
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
    /* Flush element-on time so a manual STOP doesn't drop up to one save
       interval of accumulated hours. */
    save_element_hours();
    progress_lock();
    s_progress.is_active = false;
    s_progress.status = FIRING_STATUS_IDLE;
    /* STOP also cancels a diagnostic relay pulse — /api/v1/firing/stop is the
       operator's way to cut a test short. SSR was already forced off above; the
       tick's relay branch will not re-assert it now that the deadline is clear. */
    s_relay_test_end_us = 0;
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
        bool relay_active = (s_relay_test_end_us != 0);
        progress_unlock();
        if (already_active || s_state.delay_active) {
            ESP_LOGW(TAG, "START rejected: firing already active");
            break;
        }
        if (relay_active) {
            ESP_LOGW(TAG, "START rejected: relay diagnostic test in progress");
            break;
        }

        /* Refuse to start while a firmware update is downloading: an OTA
           install reboots the controller on completion, which would kill the
           firing mid-cycle. The HTTP layer also gates this, but the display
           modal queues START directly and bypasses that path. */
        if (ota_is_busy()) {
            ESP_LOGW(TAG, "START rejected: firmware update in progress");
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

        s_state.active_profile = cmd->start.profile;
        thermocouple_reading_t r;
        thermocouple_get_latest(&r);
        float cur_temp = r.temperature_c;

        kiln_settings_t settings;
        firing_engine_get_settings(&settings);
        cur_temp += settings.tc_offset_c;

        /* Reject a segment whose ramp sign contradicts the direction from its
           start to its target (segment 0 measured against the live kiln temp).
           Such a segment would be mislabelled HEATING/COOLING, and the clamp in
           compute_dynamic_setpoint would drive the setpoint the "wrong" way —
           e.g. a COOLING label disables the not-rising and runaway watchdogs
           while full power heats toward a higher target.

           Only for an immediate start: for a delayed one the kiln is frequently
           still hot from a previous firing and will have cooled by the time the
           delay expires, so judging segment 0 now would reject profiles that are
           perfectly valid when they actually begin. The delay-expiry path below
           runs the same check against the fresh reading instead. Segment-to-
           segment consistency is temperature-independent and is enforced for
           both paths by validate_profile() at save/start time. */
        if (cmd->start.delay_minutes == 0) {
            int bad_seg = firing_first_bad_ramp_sign(&cmd->start.profile, cur_temp);
            if (bad_seg >= 0) {
                ESP_LOGW(TAG, "START rejected: segment %d ramp direction contradicts its target", bad_seg);
                break;
            }
        }

        int64_t now_us = esp_timer_get_time();
        s_state.delay_active = false;
        if (cmd->start.delay_minutes > 0) {
            s_state.delay_start_end_us = now_us + (int64_t)cmd->start.delay_minutes * 60 * 1000000LL;
            s_state.delay_active = true;
            progress_lock();
            s_progress.is_active = true;
            s_progress.status = FIRING_STATUS_IDLE; /* show as idle during delay */
            snprintf(s_progress.profile_id, FIRING_ID_LEN, "%s", s_state.active_profile.id);
            s_progress.current_segment = 0;
            s_progress.total_segments = s_state.active_profile.segment_count;
            s_progress.elapsed_time = 0;
            progress_unlock();
            s_state.elapsed_accum_us = 0;
            ESP_LOGI(TAG, "Firing queued with %u min delay: %s", cmd->start.delay_minutes, s_state.active_profile.name);
        } else {
            progress_lock();
            s_progress.is_active = true;
            snprintf(s_progress.profile_id, FIRING_ID_LEN, "%s", s_state.active_profile.id);
            s_progress.current_segment = 0;
            s_progress.total_segments = s_state.active_profile.segment_count;
            s_progress.elapsed_time = 0;
            progress_unlock();
            s_state.elapsed_accum_us = 0;
            begin_firing(cur_temp, now_us);
            ESP_LOGI(TAG, "Firing started: %s", s_state.active_profile.name);
        }
        s_last_error_code = FIRING_ERR_NONE;
        break;
    }

    case FIRING_CMD_STOP: {
        bool was_active;
        progress_lock();
        was_active = s_progress.is_active;
        uint32_t dur = s_progress.elapsed_time;
        progress_unlock();
        float peak = s_state.peak_temp_c;
        if (was_active) {
            history_firing_end(HISTORY_OUTCOME_ABORTED, peak, dur, 0);
        }
        s_state.delay_active = false;
        do_stop();
        break;
    }

    case FIRING_CMD_PAUSE: {
        /* Nothing to pause while a delayed start is still counting down. */
        if (s_state.delay_active) {
            ESP_LOGW(TAG, "PAUSE ignored: firing has not started (delay armed)");
            break;
        }
        bool did_pause = false;
        progress_lock();
        if (s_progress.is_active && s_progress.status != FIRING_STATUS_PAUSED) {
            s_state.pause_prev_status = s_progress.status;
            s_progress.status = FIRING_STATUS_PAUSED;
            did_pause = true;
        }
        progress_unlock();
        if (did_pause) {
            safety_set_ssr(0.0f);
            s_state.pause_start_us = esp_timer_get_time();
            ESP_LOGI(TAG, "Firing paused");
        }
        break;
    }

    case FIRING_CMD_RESUME: {
        bool did_resume = false;
        bool resumed_autotune = false;
        progress_lock();
        if (s_progress.status == FIRING_STATUS_PAUSED) {
            s_progress.status = s_state.pause_prev_status;
            resumed_autotune = (s_state.pause_prev_status == FIRING_STATUS_AUTOTUNE);
            did_resume = true;
        }
        progress_unlock();
        if (did_resume && resumed_autotune) {
            /* Autotune has no segment ramp, hold timer or not-rising window —
               but it does keep absolute timestamps of its own (the overall
               timeout and each relay half-cycle), so they need the same shift
               the firing anchors below get. Otherwise a paused run trips its
               timeout the instant it resumes, or folds the pause into an
               oscillation period and saves gains derived from it. */
            int64_t paused_us = esp_timer_get_time() - s_state.pause_start_us;
            pid_autotune_shift_time(&s_autotune, paused_us);
            ESP_LOGI(TAG, "Auto-tune resumed");
            break;
        }
        if (did_resume) {
            /* Shift the segment clock and safety windows forward by the paused
             * duration so the ramp setpoint, not-rising window, runaway baseline,
             * and hold timer all resume where they left off. Without this, a long
             * pause makes the engine think the kiln stalled (NOT_RISING) or that
             * the setpoint should jump far ahead. */
            int64_t paused_us = esp_timer_get_time() - s_state.pause_start_us;
            if (paused_us > 0) {
                s_state.segment_start_time_us += paused_us;
                s_state.check_start_time_us += paused_us;
                if (s_state.holding) {
                    s_state.segment_hold_start_time_s += (float)paused_us / 1000000.0f;
                }
            }
            ESP_LOGI(TAG, "Firing resumed");
        }
        break;
    }

    case FIRING_CMD_SKIP_SEGMENT: {
        /* No segment is running yet during a delayed start; skipping here would
           wrongly start_segment() and then begin_firing() would restart it. */
        if (s_state.delay_active) {
            ESP_LOGW(TAG, "SKIP ignored: firing has not started (delay armed)");
            break;
        }
        progress_lock();
        bool active = s_progress.is_active;
        bool paused = (s_progress.status == FIRING_STATUS_PAUSED);
        int seg_idx = s_progress.current_segment;
        int total = s_progress.total_segments;
        float cur = s_progress.current_temp;
        progress_unlock();

        /* Skipping while paused would re-energize the elements without going
           through RESUME's bookkeeping — the operator believes the kiln is off.
           Ignore it, as the delay_active case above does; the user must RESUME
           first, which is an explicit, visible action. */
        if (paused) {
            ESP_LOGW(TAG, "SKIP ignored: firing is paused (resume first)");
            break;
        }

        if (active && seg_idx + 1 < total) {
            int next = seg_idx + 1;
            /* A skip enters the next segment from wherever the kiln actually is,
               not from the previous segment's target — so a segment that is a
               valid descent on paper can be an invalid one from an early skip
               point, landing in exactly the mislabelled-direction state the
               START check exists to prevent. Refuse rather than advance; the
               operator can still STOP. */
            const firing_segment_t *ns = &s_state.active_profile.segments[next];
            float ndelta = ns->target_temp - cur;
            if ((ndelta > 0.5f && ns->ramp_rate < 0.0f) || (ndelta < -0.5f && ns->ramp_rate > 0.0f)) {
                ESP_LOGW(TAG, "SKIP ignored: segment %d ramp direction contradicts the current %.0f°C", next, cur);
                break;
            }
            start_segment(next, cur, esp_timer_get_time());
            progress_lock();
            s_progress.current_segment = next;
            s_progress.status =
                (s_state.active_profile.segments[next].ramp_rate >= 0) ? FIRING_STATUS_HEATING : FIRING_STATUS_COOLING;
            progress_unlock();
            ESP_LOGI(TAG, "Skipped to segment %d", next);
        } else if (active && seg_idx + 1 >= total) {
            /* Skip last segment → firing complete */
            progress_lock();
            uint32_t dur = s_progress.elapsed_time;
            progress_unlock();
            complete_firing(s_state.peak_temp_c, dur, false);
        }
        break;
    }

    case FIRING_CMD_AUTOTUNE_START: {
        /* Same active-firing guard as FIRING_CMD_START. Without it, autotune
           silently replaces a running firing: the profile state is abandoned
           mid-cycle, its open history record is never closed, and the kiln
           free-cools toward the (much lower) autotune setpoint with no error
           surfaced anywhere. */
        progress_lock();
        bool autotune_blocked = s_progress.is_active;
        bool autotune_relay_active = (s_relay_test_end_us != 0);
        progress_unlock();
        if (autotune_blocked || s_state.delay_active) {
            ESP_LOGW(TAG, "AUTOTUNE rejected: firing already active");
            break;
        }
        if (autotune_relay_active) {
            ESP_LOGW(TAG, "AUTOTUNE rejected: relay diagnostic test in progress");
            break;
        }

        /* Same OTA guard as FIRING_CMD_START: autotune energizes the elements
           and a mid-run reboot would leave them in an undefined state. */
        if (ota_is_busy()) {
            ESP_LOGW(TAG, "AUTOTUNE rejected: firmware update in progress");
            break;
        }
        pid_autotune_start(&s_autotune, cmd->autotune.setpoint, cmd->autotune.hysteresis);
        progress_lock();
        s_progress.is_active = true;
        s_progress.status = FIRING_STATUS_AUTOTUNE;
        s_progress.elapsed_time = 0;
        progress_unlock();
        s_state.elapsed_accum_us = 0;
        ESP_LOGI(TAG, "Auto-tune mode started");
        break;
    }

    case FIRING_CMD_AUTOTUNE_STOP:
        pid_autotune_cancel(&s_autotune);
        do_stop();
        break;
    }
}

/* compute_dynamic_setpoint and at_target_predicate live in firing_helpers.c
 * (declared in firing_engine_internal.h) so the host test harness can link
 * just those translation units. */

/* ── Firing tick ────────────────────────────────────
 * Single iteration of the firing loop. firing_task drives this once per
 * second; a host harness can drive it with a virtual clock to fast-forward
 * an entire firing in <1 s for tests. */

/* Wall clock at the previous tick. Owned by firing_tick; firing_task seeds it
 * from esp_timer_get_time() before entering the loop. */
static int64_t s_last_compute_us = 0;

void firing_tick(int64_t now_us)
{
    /* Relay diagnostic pulse. Re-assert the duty every tick so the safety
       task's 3-second SSR heartbeat stays fed for the whole test — a single
       set-and-sleep would latch an emergency stop on any test longer than 3 s.
       The deadline is armed synchronously by firing_engine_relay_test_arm();
       this tick is the sole SSR writer for it. */
    progress_lock();
    int64_t relay_end = s_relay_test_end_us;
    progress_unlock();
    if (relay_end != 0) {
        if (safety_is_emergency() || now_us >= relay_end) {
            progress_lock();
            s_relay_test_end_us = 0;
            progress_unlock();
            safety_set_ssr(0.0f);
            ESP_LOGI(TAG, "Relay diagnostic test finished");
        } else {
            safety_set_ssr(1.0f);
        }
        return;
    }

    /* Handle delay-start countdown */
    if (s_state.delay_active) {
        /* A latched emergency cancels the armed firing before it starts, so it
           never energizes the kiln a tick later and then errors out. No history
           was opened during the delay, so just clear the armed state. */
        if (safety_is_emergency()) {
            s_state.delay_active = false;
            progress_lock();
            s_progress.is_active = false;
            s_progress.status = FIRING_STATUS_ERROR;
            progress_unlock();
            if (s_last_error_code == FIRING_ERR_NONE) {
                s_last_error_code = firing_err_from_trip(safety_get_trip_cause());
            }
            safety_set_ssr(0.0f);
            return;
        }
        if (now_us >= s_state.delay_start_end_us) {
            s_state.delay_active = false;
            thermocouple_reading_t r;
            thermocouple_get_latest(&r);
            kiln_settings_t st;
            firing_engine_get_settings(&st);
            float cur_temp = r.temperature_c + st.tc_offset_c;

            /* The temperature the first segment actually starts from is only
               known now, so this is where segment 0's ramp direction has to be
               checked (START deliberately skipped it for delayed firings). */
            int bad_seg = firing_first_bad_ramp_sign(&s_state.active_profile, cur_temp);
            if (bad_seg >= 0) {
                ESP_LOGE(TAG, "Delayed firing aborted: segment %d ramp direction contradicts its target at %.0f°C",
                         bad_seg, cur_temp);
                s_last_error_code = FIRING_ERR_INVALID_PROFILE;
                safety_set_ssr(0.0f);
                progress_lock();
                s_progress.is_active = false;
                s_progress.status = FIRING_STATUS_ERROR;
                progress_unlock();
                emit_event(FIRING_EVENT_ERROR, s_state.peak_temp_c, 0);
                return;
            }
            begin_firing(cur_temp, now_us);
            /* Reset dt baseline so the PID tick that runs in the rest of this
             * iteration sees dt≈0 (matches pre-refactor behavior). */
            s_last_compute_us = now_us;
            ESP_LOGI(TAG, "Delay expired, firing started: %s", s_state.active_profile.name);
        } else {
            /* Keep vent in sync while waiting for delay to expire. */
            thermocouple_reading_t r;
            thermocouple_get_latest(&r);
            safety_update_vent(true, r.temperature_c);
            return;
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
    int64_t dt_us = now_us - s_last_compute_us;
    float dt_s = (float)dt_us / 1000000.0f;
    s_last_compute_us = now_us;

    /* Check for emergency stop */
    if (safety_is_emergency()) {
        progress_lock();
        if (s_progress.is_active) {
            float peak = s_state.peak_temp_c;
            uint32_t dur = s_progress.elapsed_time;
            s_progress.is_active = false;
            s_progress.status = FIRING_STATUS_ERROR;
            progress_unlock();
            /* Attribute the stop. not-rising/runaway set their code before
               tripping; otherwise translate the safety trip cause (TC fault,
               over-temp) so the UI shows a specific reason. */
            if (s_last_error_code == FIRING_ERR_NONE) {
                s_last_error_code = firing_err_from_trip(safety_get_trip_cause());
            }
            history_firing_end(HISTORY_OUTCOME_ERROR, peak, dur, (int)s_last_error_code);
            emit_event(FIRING_EVENT_ERROR, peak, dur);
        } else {
            progress_unlock();
        }
        safety_set_ssr(0.0f);
        return;
    }

    progress_lock();
    firing_status_t status = s_progress.status;
    bool active = s_progress.is_active;
    int seg_idx = s_progress.current_segment;
    s_progress.current_temp = current_temp;
    progress_unlock();

    /* Track the running peak for the completion/error event. */
    if (active && current_temp > s_state.peak_temp_c) {
        s_state.peak_temp_c = current_temp;
    }

    if (!active || status == FIRING_STATUS_PAUSED || status == FIRING_STATUS_IDLE || status == FIRING_STATUS_COMPLETE ||
        status == FIRING_STATUS_ERROR) {
        if (status != FIRING_STATUS_PAUSED) {
            safety_set_ssr(0.0f);
        }
        return;
    }

    /* Thermocouple fault: a faulted MAX31855 read reports 0°C (see
     * thermocouple_read). Feeding that into the PID against a hot setpoint
     * would command full power, so hold the element off until the reading
     * recovers. safety_task escalates to an emergency stop if the fault
     * persists past APP_TEMP_FAULT_TIMEOUT_MS. */
    if (reading.fault != 0) {
        safety_set_ssr(0.0f);
        return;
    }

    /* Auto-tune mode */
    if (status == FIRING_STATUS_AUTOTUNE) {
        float output;
        bool done = pid_autotune_update(&s_autotune, current_temp, &output);
        safety_set_ssr(output);

        s_state.elapsed_accum_us += dt_us;
        progress_lock();
        s_progress.elapsed_time = (uint32_t)(s_state.elapsed_accum_us / 1000000);
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
        return;
    }

    /* Normal firing: PID control + state machine */
    firing_segment_t *seg = &s_state.active_profile.segments[seg_idx];

    /* ── Safety: kiln-not-rising check ──────────────────────────────── */
    if (status == FIRING_STATUS_HEATING && !s_state.holding) {
        if ((now_us - s_state.check_start_time_us) >= RISING_CHECK_INTERVAL_US) {
            float temp_rise = current_temp - s_state.check_start_temp;
            if (temp_rise < RISING_THRESHOLD_C) {
                ESP_LOGE(TAG, "Kiln not rising: only %.1f°C in 15 min (need %.0f°C)", temp_rise, RISING_THRESHOLD_C);
                s_last_error_code = FIRING_ERR_NOT_RISING;
                safety_emergency_stop();
            }
            /* Reset window */
            s_state.check_start_temp = current_temp;
            s_state.check_start_time_us = now_us;
        }
    }

    /* ── Safety: rate-of-rise runaway check ──────────────────────────── */
    if (status == FIRING_STATUS_HEATING && !s_state.holding && fabsf(seg->ramp_rate) > 0.1f) {
        float elapsed_seg_s = (float)(now_us - s_state.segment_start_time_us) / 1000000.0f;
        if (elapsed_seg_s > 300.0f) { /* Only check after 5 minutes in segment */
            float actual_rate_c_hr = ((current_temp - s_state.segment_start_temp) / elapsed_seg_s) * 3600.0f;
            if (actual_rate_c_hr > seg->ramp_rate * RUNAWAY_RATE_MULTIPLIER &&
                actual_rate_c_hr > 50.0f) { /* Ignore when rate < 50°C/hr (noise) */
                ESP_LOGE(TAG, "Runaway: actual rate %.0f°C/hr vs programmed %.0f°C/hr", actual_rate_c_hr,
                         seg->ramp_rate);
                s_last_error_code = FIRING_ERR_RUNAWAY;
                safety_emergency_stop();
            }
        }
    }

    float setpoint = compute_dynamic_setpoint(seg, s_state.segment_start_temp, s_state.segment_start_time_us, now_us,
                                              s_state.holding);

    /* PID compute */
    float output = pid_compute(&s_pid, setpoint, current_temp, dt_s);
    safety_set_ssr(output);

    /* Accumulate element-on time (sum raw µs so sub-second ticks aren't lost) */
    if (output > 0.0f) {
        s_element_on_accum_us += (uint64_t)dt_us;
        s_element_on_s = (uint32_t)(s_element_on_accum_us / 1000000ULL);
        if ((now_us - s_state.last_elem_save_us) >= ELEM_SAVE_INTERVAL_US) {
            save_element_hours();
            s_state.last_elem_save_us = now_us;
        }
    }

    /* History: record temperature once per minute */
    if ((now_us - s_state.last_history_sample_us) >= HISTORY_SAMPLE_INTERVAL_US) {
        history_record_temp(current_temp);
        s_state.last_history_sample_us = now_us;
    }

    /* Check segment transitions */
    bool reached = at_target_predicate(current_temp, setpoint, seg->target_temp);

    if (!s_state.holding && reached) {
        /* Reached target. hold_time == 0 → pass through (advance next iteration via
           hold_done below). FIRING_HOLD_INDEFINITE → wait for SKIP_SEGMENT. */
        s_state.holding = true;
        s_state.segment_hold_start_time_s = (float)(now_us) / 1000000.0f;
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

    if (s_state.holding) {
        float hold_elapsed_s = (float)(now_us) / 1000000.0f - s_state.segment_hold_start_time_s;
        bool infinite_hold = (seg->hold_time == FIRING_HOLD_INDEFINITE);
        float hold_needed_s = infinite_hold ? 0.0f : (float)seg->hold_time * 60.0f;

        /* FIRING_HOLD_INDEFINITE waits for SKIP_SEGMENT; any finite duration (incl. 0) advances when elapsed. */
        bool hold_done = !infinite_hold && (hold_elapsed_s >= hold_needed_s);

        if (hold_done) {
            /* Hold complete — advance to next segment */
            int next_seg = seg_idx + 1;
            if (next_seg >= s_state.active_profile.segment_count) {
                /* Firing complete */
                safety_set_ssr(0.0f);
                progress_lock();
                uint32_t dur = s_progress.elapsed_time;
                s_progress.is_active = false;
                s_progress.status = FIRING_STATUS_COMPLETE;
                progress_unlock();
                float peak = s_state.peak_temp_c;
                history_firing_end(HISTORY_OUTCOME_COMPLETE, peak, dur, 0);
                save_element_hours();
                xEventGroupSetBits(safety_get_event_group(), SAFETY_BIT_FIRING_COMPLETE);
                emit_event(FIRING_EVENT_COMPLETE, peak, dur);
                ESP_LOGI(TAG, "Firing complete!");
            } else {
                start_segment(next_seg, current_temp, now_us);
                progress_lock();
                s_progress.current_segment = next_seg;
                /* Determine if next segment is heating or cooling */
                if (s_state.active_profile.segments[next_seg].ramp_rate >= 0) {
                    s_progress.status = FIRING_STATUS_HEATING;
                } else {
                    s_progress.status = FIRING_STATUS_COOLING;
                }
                progress_unlock();
            }
        }
    }

    /* Update progress timing */
    s_state.elapsed_accum_us += dt_us;
    progress_lock();
    s_progress.elapsed_time = (uint32_t)(s_state.elapsed_accum_us / 1000000);
    s_progress.target_temp = setpoint;
    /* Live ETA from the current segment/temperature so it stays useful even
       after the kiln runs past the profile's up-front estimate. */
    float hold_elapsed_s = s_state.holding ? ((float)now_us / 1000000.0f - s_state.segment_hold_start_time_s) : 0.0f;
    s_progress.estimated_remaining = firing_remaining_s(&s_state.active_profile, s_progress.current_segment,
                                                        current_temp, s_state.holding, hold_elapsed_s);
    progress_unlock();
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
        if (remaining <= 0) {
            break;
        }
        if (xQueueReceive(s_cmd_queue, &cmd, (TickType_t)remaining) != pdTRUE) {
            break;
        }
        handle_cmd(&cmd);
    }
    *last_wake = deadline;
}

void firing_task(void *param)
{
    (void)param;
    TickType_t last_wake = xTaskGetTickCount();
    s_last_compute_us = esp_timer_get_time();

    ESP_LOGI(TAG, "firing_task started");

    for (;;) {
        firing_tick(esp_timer_get_time());
        wait_until_next_tick(&last_wake);
    }
}

/* ── Test-only entry points ────────────────────────────────
 * Exposed via firing_engine_internal.h so the host harness can drive the
 * engine without spinning up firing_task. Behavior in production is
 * unchanged because the public API still routes through the cmd queue. */

void firing_engine_dispatch_cmd_for_test(const firing_cmd_t *cmd)
{
    if (cmd) {
        handle_cmd(cmd);
    }
}

void firing_engine_reset_for_test(void)
{
    memset(&s_state, 0, sizeof(s_state));
    memset(&s_progress, 0, sizeof(s_progress));
    s_progress.status = FIRING_STATUS_IDLE;
    s_last_error_code = FIRING_ERR_NONE;
    s_element_on_s = 0;
    s_element_on_accum_us = 0;
    s_last_compute_us = 0;
    pid_reset(&s_pid);
    memset(&s_autotune, 0, sizeof(s_autotune));
    s_autotune.state = AUTOTUNE_IDLE;

    /* Drain any pending commands/events left over from a prior test. */
    if (s_cmd_queue) {
        firing_cmd_t cmd;
        while (xQueueReceive(s_cmd_queue, &cmd, 0) == pdTRUE) {
        }
    }
    if (s_event_queue) {
        firing_event_t evt;
        while (xQueueReceive(s_event_queue, &evt, 0) == pdTRUE) {
        }
    }
}
