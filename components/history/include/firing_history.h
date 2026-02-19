#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HISTORY_MAX_RECORDS   20
#define HISTORY_PROFILE_NAME_LEN 48

typedef enum {
    HISTORY_OUTCOME_COMPLETE = 0,
    HISTORY_OUTCOME_ERROR,
    HISTORY_OUTCOME_ABORTED,
} history_outcome_t;

typedef struct {
    uint32_t id;                    /* Monotonic record ID */
    int64_t  start_time;            /* Unix timestamp (0 if NTP not available) */
    char     profile_name[HISTORY_PROFILE_NAME_LEN];
    char     profile_id[40];
    float    peak_temp_c;
    uint32_t duration_s;            /* Total firing duration in seconds */
    history_outcome_t outcome;
    int      error_code;            /* Error code if outcome == ERROR */
} history_record_t;

/**
 * Initialize history subsystem. Creates storage directory on SPIFFS if needed.
 * Must be called after SPIFFS is mounted.
 */
esp_err_t history_init(void);

/**
 * Called when a firing starts. Begins temperature trace recording.
 * @param profile_id   Profile ID string.
 * @param profile_name Profile display name.
 */
void history_firing_start(const char *profile_id, const char *profile_name);

/**
 * Record a temperature sample for the current firing (call every minute from firing_task).
 * @param temp_c Current temperature in °C.
 */
void history_record_temp(float temp_c);

/**
 * Called when a firing completes (or errors/aborts). Saves the record.
 * @param outcome    COMPLETE / ERROR / ABORTED.
 * @param peak_temp  Peak temperature reached.
 * @param duration_s Total elapsed seconds.
 * @param error_code Error code (0 if none).
 */
void history_firing_end(history_outcome_t outcome, float peak_temp,
                        uint32_t duration_s, int error_code);

/**
 * Retrieve the list of stored history records (newest first).
 * @param out_records  Caller-provided array.
 * @param max_count    Size of out_records.
 * @return Number of records returned.
 */
int history_get_records(history_record_t *out_records, int max_count);

/**
 * Write CSV temperature trace for a record to the given buffer.
 * @param record_id  The history record ID.
 * @param buf        Output buffer.
 * @param buf_size   Size of output buffer.
 * @return ESP_OK on success, ESP_ERR_NOT_FOUND if trace missing.
 */
esp_err_t history_get_trace_csv(uint32_t record_id, char *buf, size_t buf_size);

/**
 * Delete all history records and traces.
 */
void history_clear(void);

#ifdef __cplusplus
}
#endif
