#include "safety_internal.h"

safety_tc_state_t safety_tc_watchdog_step(const thermocouple_reading_t *reading, int64_t now_us,
                                          int64_t *last_valid_reading_us)
{
    if (reading->fault != 0) {
        return ((now_us - *last_valid_reading_us) > TEMP_FAULT_TIMEOUT_US) ? SAFETY_TC_FAULT_TRIP
                                                                           : SAFETY_TC_FAULT_GRACE;
    }

    /* Only adopt a timestamp that a producer actually wrote. The zero-initialized
       cached reading looks fault-free with timestamp_us == 0; adopting it would
       reset the grace-period origin to the epoch and make the very next faulted
       sample trip instantly. */
    if (reading->timestamp_us > 0) {
        *last_valid_reading_us = reading->timestamp_us;
        return SAFETY_TC_OK;
    }

    /* No producer has ever written the cache. thermocouple_read() only updates it
       on success, so a total failure — SPI never comes up, sensor absent, or
       temp_read_task not running at all — leaves it all zeroes, which otherwise
       reads as a healthy 0 degC forever. safety_task's own stale-reading check
       cannot cover this: it is gated on timestamp_us > 0, which is precisely the
       case missing here. Without this branch nothing ever tripped and a firing
       could run with no temperature feedback (issue #215).

       Measured from the same boot seed as the fault debounce, so a producer that
       is merely slow to start still gets the full grace period. */
    return ((now_us - *last_valid_reading_us) > TEMP_FAULT_TIMEOUT_US) ? SAFETY_TC_FAULT_TRIP : SAFETY_TC_FAULT_GRACE;
}

lid_state_t safety_lid_debounce_step(lid_debounce_t *d, bool raw_open)
{
    if (raw_open) {
        /* Believed immediately, and the close counter restarts from zero so a
           bounce partway through closing cannot bank credit toward "shut". */
        d->close_samples = 0;
        d->state = LID_STATE_OPEN;
        return d->state;
    }

    if (d->close_samples < LID_CLOSE_DEBOUNCE_SAMPLES) {
        d->close_samples++;
    }
    if (d->close_samples >= LID_CLOSE_DEBOUNCE_SAMPLES) {
        d->state = LID_STATE_CLOSED;
    }
    return d->state;
}
