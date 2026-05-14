#pragma once

/* Test-only inspection helpers for the host safety stub. The firing engine
 * drives the real safety_*() API declared in safety.h; tests read these
 * accessors to assert what the engine asked for. */

#include "safety.h"

float safety_test_last_duty(void);
bool safety_test_vent_active(void);
void safety_test_reset(void);
