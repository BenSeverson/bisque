#pragma once

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Tiny shared-state contract between app_main (publisher) and display_task
 * (consumer). Implemented as two _Atomic variables in splash.c — no mutex
 * needed; the message pointer is always a static string literal so there is
 * no aliasing or lifetime concern.
 *
 * Calls are no-ops if the splash module hasn't been built into the firmware
 * (kept inside the display component so headless builds without a display
 * still link cleanly via weak symbols would be possible — but for now the
 * display component is always present, so this is just for cleanliness). */

void boot_status_set(const char *msg);
const char *boot_status_get(void);
void boot_status_mark_ready(void);
bool boot_status_is_ready(void);

#ifdef __cplusplus
}
#endif
