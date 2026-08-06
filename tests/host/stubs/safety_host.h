#pragma once

/* Test-only inspection helpers for the host safety stub. The firing engine
 * drives the real safety_*() API declared in safety.h; tests read these
 * accessors to assert what the engine asked for. */

#include "safety.h"

float safety_test_last_duty(void);
/* Number of safety_set_ssr() calls since reset — proves the SSR heartbeat is
   actually re-fed, which a last-value-only accessor cannot show. */
unsigned safety_test_ssr_call_count(void);
bool safety_test_vent_active(void);
/* Place the lid directly, bypassing the debounce (which test_safety_helpers.c
   covers). Setting any state other than NOT_FITTED makes the switch "fitted". */
void safety_test_set_lid(lid_state_t state);
bool safety_test_lid_interlock_armed(void);
void safety_test_reset(void);
