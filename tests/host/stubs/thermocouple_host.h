#pragma once

/* Test-only knobs for the host thermocouple stub. The firing engine reads
 * via the real thermocouple_get_latest() declared in thermocouple.h; tests
 * call thermocouple_test_set() to control what that read returns. */

#include "thermocouple.h"

void thermocouple_test_set(float temperature_c, uint8_t fault);
