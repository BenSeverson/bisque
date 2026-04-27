/**
 * Setters that let simulator/main.c drive the mock thermocouple / firing engine /
 * history APIs that mock_esp.c implements. Include this from main.c only — the
 * firmware UI code (dashboard, modals) doesn't need it.
 */
#pragma once

#include "firing_types.h"
#include "thermocouple.h"
#include "firing_history.h"

void mock_set_progress(const firing_progress_t *p);
void mock_set_thermocouple(const thermocouple_reading_t *tc);
void mock_set_error_code(firing_error_code_t code);
void mock_set_last_firing(const history_record_t *r); /* NULL clears */
