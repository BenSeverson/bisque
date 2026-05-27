#include "ota_manager.h"

/* Host stub: the firing engine queries ota_is_busy() to refuse starting a
   firing or autotune while a firmware update is in flight. No OTA subsystem
   runs under the host tests, so it is never busy. */
bool ota_is_busy(void)
{
    return false;
}
