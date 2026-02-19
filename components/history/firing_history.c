#include "firing_history.h"
#include "esp_log.h"
#include "esp_spiffs.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <inttypes.h>
#include <time.h>

static const char *TAG = "history";

#define HISTORY_JSON_PATH  "/www/history.json"
#define TRACE_PATH_FMT     "/www/trc_%" PRIu32 ".csv"
#define TRACE_PATH_LEN     32

/* Active firing session */
static bool s_recording = false;
static history_record_t s_current;
static FILE *s_trace_file = NULL;
static uint32_t s_trace_sample_count = 0;
static SemaphoreHandle_t s_mutex = NULL;

/* Monotonic ID counter, loaded from history on init */
static uint32_t s_next_id = 1;

/* ── Internal helpers ─────────────────────────────────────────────────── */

static void lock(void)   { if (s_mutex) xSemaphoreTake(s_mutex, portMAX_DELAY); }
static void unlock(void) { if (s_mutex) xSemaphoreGive(s_mutex); }

static void make_trace_path(uint32_t id, char *buf, size_t size)
{
    snprintf(buf, size, TRACE_PATH_FMT, id);
}

static esp_err_t load_records_from_json(history_record_t *records, int max_count, int *out_count)
{
    *out_count = 0;
    FILE *f = fopen(HISTORY_JSON_PATH, "r");
    if (!f) return ESP_ERR_NOT_FOUND;

    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    rewind(f);
    if (sz <= 0 || sz > 32768) {
        fclose(f);
        return ESP_ERR_INVALID_SIZE;
    }

    char *buf = malloc(sz + 1);
    if (!buf) { fclose(f); return ESP_ERR_NO_MEM; }
    fread(buf, 1, sz, f);
    buf[sz] = '\0';
    fclose(f);

    cJSON *arr = cJSON_Parse(buf);
    free(buf);
    if (!arr || !cJSON_IsArray(arr)) {
        if (arr) cJSON_Delete(arr);
        return ESP_ERR_INVALID_RESPONSE;
    }

    int count = cJSON_GetArraySize(arr);
    if (count > max_count) count = max_count;

    for (int i = 0; i < count; i++) {
        cJSON *item = cJSON_GetArrayItem(arr, i);
        cJSON *j;

        j = cJSON_GetObjectItem(item, "id");
        if (j) records[i].id = (uint32_t)j->valuedouble;
        j = cJSON_GetObjectItem(item, "startTime");
        if (j) records[i].start_time = (int64_t)j->valuedouble;
        j = cJSON_GetObjectItem(item, "profileName");
        if (j && j->valuestring)
            strncpy(records[i].profile_name, j->valuestring, HISTORY_PROFILE_NAME_LEN - 1);
        j = cJSON_GetObjectItem(item, "profileId");
        if (j && j->valuestring)
            strncpy(records[i].profile_id, j->valuestring, sizeof(records[i].profile_id) - 1);
        j = cJSON_GetObjectItem(item, "peakTemp");
        if (j) records[i].peak_temp_c = (float)j->valuedouble;
        j = cJSON_GetObjectItem(item, "durationS");
        if (j) records[i].duration_s = (uint32_t)j->valuedouble;
        j = cJSON_GetObjectItem(item, "outcome");
        if (j) records[i].outcome = (history_outcome_t)(int)j->valuedouble;
        j = cJSON_GetObjectItem(item, "errorCode");
        if (j) records[i].error_code = (int)j->valuedouble;
    }

    cJSON_Delete(arr);
    *out_count = count;
    return ESP_OK;
}

static esp_err_t save_records_to_json(const history_record_t *records, int count)
{
    cJSON *arr = cJSON_CreateArray();
    if (!arr) return ESP_ERR_NO_MEM;

    for (int i = 0; i < count; i++) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "id", records[i].id);
        cJSON_AddNumberToObject(item, "startTime", (double)records[i].start_time);
        cJSON_AddStringToObject(item, "profileName", records[i].profile_name);
        cJSON_AddStringToObject(item, "profileId", records[i].profile_id);
        cJSON_AddNumberToObject(item, "peakTemp", records[i].peak_temp_c);
        cJSON_AddNumberToObject(item, "durationS", records[i].duration_s);
        cJSON_AddNumberToObject(item, "outcome", records[i].outcome);
        cJSON_AddNumberToObject(item, "errorCode", records[i].error_code);
        cJSON_AddItemToArray(arr, item);
    }

    char *json = cJSON_PrintUnformatted(arr);
    cJSON_Delete(arr);
    if (!json) return ESP_ERR_NO_MEM;

    FILE *f = fopen(HISTORY_JSON_PATH, "w");
    if (!f) {
        free(json);
        return ESP_FAIL;
    }
    fputs(json, f);
    fclose(f);
    free(json);
    return ESP_OK;
}

/* ── Public API ───────────────────────────────────────────────────────── */

esp_err_t history_init(void)
{
    s_mutex = xSemaphoreCreateMutex();
    if (!s_mutex) return ESP_ERR_NO_MEM;

    /* Load existing records to determine next ID */
    history_record_t tmp[HISTORY_MAX_RECORDS];
    int count = 0;
    load_records_from_json(tmp, HISTORY_MAX_RECORDS, &count);
    if (count > 0) {
        s_next_id = tmp[0].id + 1;
    }

    ESP_LOGI(TAG, "History initialized: %d existing records, next_id=%u", count, s_next_id);
    return ESP_OK;
}

void history_firing_start(const char *profile_id, const char *profile_name)
{
    lock();
    memset(&s_current, 0, sizeof(s_current));
    s_current.id = s_next_id++;
    s_current.start_time = (int64_t)time(NULL);
    if (profile_id)   strncpy(s_current.profile_id,   profile_id,   sizeof(s_current.profile_id)   - 1);
    if (profile_name) strncpy(s_current.profile_name, profile_name, HISTORY_PROFILE_NAME_LEN - 1);

    /* Open trace file */
    char trace_path[TRACE_PATH_LEN];
    make_trace_path(s_current.id, trace_path, sizeof(trace_path));
    s_trace_file = fopen(trace_path, "w");
    if (s_trace_file) {
        fputs("time_s,temp_c\n", s_trace_file);
    }
    s_trace_sample_count = 0;
    s_recording = true;
    unlock();
    ESP_LOGI(TAG, "Firing started: id=%u, profile=%s", s_current.id, profile_name ? profile_name : "?");
}

void history_record_temp(float temp_c)
{
    lock();
    if (s_recording && s_trace_file) {
        fprintf(s_trace_file, "%" PRIu32 ",%.1f\n",
                s_trace_sample_count * 60,  /* time in seconds (1 sample per minute) */
                temp_c);
        fflush(s_trace_file);
        s_trace_sample_count++;

        if (temp_c > s_current.peak_temp_c) {
            s_current.peak_temp_c = temp_c;
        }
    }
    unlock();
}

void history_firing_end(history_outcome_t outcome, float peak_temp,
                        uint32_t duration_s, int error_code)
{
    lock();
    if (!s_recording) {
        unlock();
        return;
    }

    s_current.outcome    = outcome;
    s_current.peak_temp_c = (peak_temp > s_current.peak_temp_c) ? peak_temp : s_current.peak_temp_c;
    s_current.duration_s = duration_s;
    s_current.error_code = error_code;

    if (s_trace_file) {
        fclose(s_trace_file);
        s_trace_file = NULL;
    }
    s_recording = false;

    /* Load existing records, prepend new one, trim to max, save */
    history_record_t records[HISTORY_MAX_RECORDS];
    int count = 0;
    load_records_from_json(records, HISTORY_MAX_RECORDS - 1, &count);

    /* Shift existing records down, prepend new */
    memmove(&records[1], &records[0], count * sizeof(history_record_t));
    records[0] = s_current;
    count++;
    if (count > HISTORY_MAX_RECORDS) count = HISTORY_MAX_RECORDS;

    /* Delete oldest trace if we exceeded the limit */
    if (count == HISTORY_MAX_RECORDS) {
        char old_trace[TRACE_PATH_LEN];
        make_trace_path(records[count - 1].id, old_trace, sizeof(old_trace));
        remove(old_trace);
    }

    save_records_to_json(records, count);
    unlock();

    const char *outcome_str = outcome == HISTORY_OUTCOME_COMPLETE ? "complete" :
                              outcome == HISTORY_OUTCOME_ERROR    ? "error"    : "aborted";
    ESP_LOGI(TAG, "Firing ended: %s, peak=%.0f°C, %u s",
             outcome_str, s_current.peak_temp_c, duration_s);
}

int history_get_records(history_record_t *out_records, int max_count)
{
    int count = 0;
    lock();
    load_records_from_json(out_records, max_count, &count);
    unlock();
    return count;
}

esp_err_t history_get_trace_csv(uint32_t record_id, char *buf, size_t buf_size)
{
    char trace_path[TRACE_PATH_LEN];
    make_trace_path(record_id, trace_path, sizeof(trace_path));

    FILE *f = fopen(trace_path, "r");
    if (!f) return ESP_ERR_NOT_FOUND;

    size_t n = fread(buf, 1, buf_size - 1, f);
    buf[n] = '\0';
    fclose(f);
    return ESP_OK;
}

void history_clear(void)
{
    lock();
    history_record_t records[HISTORY_MAX_RECORDS];
    int count = 0;
    load_records_from_json(records, HISTORY_MAX_RECORDS, &count);
    for (int i = 0; i < count; i++) {
        char trace_path[TRACE_PATH_LEN];
        make_trace_path(records[i].id, trace_path, sizeof(trace_path));
        remove(trace_path);
    }
    remove(HISTORY_JSON_PATH);
    unlock();
}
