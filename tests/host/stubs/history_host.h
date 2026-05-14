#pragma once

/* Test-only inspection helpers for the host history stub. */

#include "firing_history.h"

typedef struct {
    int starts;
    int samples;
    int ends;
    history_outcome_t last_outcome;
    float last_peak_temp;
    uint32_t last_duration_s;
    int last_error_code;
} history_test_counts_t;

void history_test_reset(void);
history_test_counts_t history_test_counts(void);
