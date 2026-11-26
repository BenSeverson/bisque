#pragma once

/*
 * Compile-time pin-map checks. Include this from exactly one translation unit
 * that already has sdkconfig.h (main.c does), after app_config.h. It is not
 * part of app_config.h because that header is also compiled by the host tests
 * and the simulator, which have no sdkconfig.
 */

#include "app_config.h"

/* Rev C moved three functions onto each other's old pins: the CT took the
   touch interrupt's, and the touch interrupt took the status LED's. A build
   tree configured for rev B keeps its old values in sdkconfig (a changed
   Kconfig default does not rewrite it) and picks up the new CT default, so
   two functions land on one GPIO. Fail the build rather than drive a WS2812
   waveform into the touch interrupt or hang a pull-up on the ADC node. */
#define APP_PINS_DISTINCT(a, b) ((a) < 0 || (b) < 0 || (a) != (b))
_Static_assert(APP_PINS_DISTINCT(APP_PIN_CT, APP_PIN_TOUCH_IRQ),
               "KILN_PIN_CT and KILN_PIN_TOUCH_IRQ share a GPIO - stale sdkconfig? delete it and rebuild");
_Static_assert(APP_PINS_DISTINCT(APP_PIN_STATUS_LED, APP_PIN_TOUCH_IRQ),
               "KILN_PIN_STATUS_LED and KILN_PIN_TOUCH_IRQ share a GPIO - stale sdkconfig? delete it and rebuild");
_Static_assert(APP_PINS_DISTINCT(APP_PIN_STATUS_LED, APP_PIN_CT),
               "KILN_PIN_STATUS_LED and KILN_PIN_CT share a GPIO - stale sdkconfig? delete it and rebuild");
