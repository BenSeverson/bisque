#include "history_host.h"

#include <string.h>

static history_test_counts_t s_counts;

esp_err_t history_init(void)
{
    history_test_reset();
    return ESP_OK;
}

void history_firing_start(const char *profile_id, const char *profile_name)
{
    (void)profile_id;
    (void)profile_name;
    s_counts.starts++;
}

void history_record_temp(float temp_c)
{
    (void)temp_c;
    s_counts.samples++;
}

void history_firing_end(history_outcome_t outcome, float peak_temp, uint32_t duration_s, int error_code)
{
    s_counts.ends++;
    s_counts.last_outcome = outcome;
    s_counts.last_peak_temp = peak_temp;
    s_counts.last_duration_s = duration_s;
    s_counts.last_error_code = error_code;
}

int history_get_records(history_record_t *out_records, int max_count)
{
    (void)out_records;
    (void)max_count;
    return 0;
}

FILE *history_open_trace(uint32_t record_id)
{
    (void)record_id;
    return NULL;
}

void history_clear(void)
{
    history_test_reset();
}

const char *history_outcome_to_string(history_outcome_t outcome)
{
    switch (outcome) {
    case HISTORY_OUTCOME_COMPLETE:
        return "complete";
    case HISTORY_OUTCOME_ERROR:
        return "error";
    case HISTORY_OUTCOME_ABORTED:
        return "aborted";
    default:
        return "unknown";
    }
}

void history_test_reset(void)
{
    memset(&s_counts, 0, sizeof(s_counts));
}

history_test_counts_t history_test_counts(void)
{
    return s_counts;
}
