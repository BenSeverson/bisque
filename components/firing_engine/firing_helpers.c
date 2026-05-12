#include "firing_engine_internal.h"
#include <math.h>

float compute_dynamic_setpoint(const firing_segment_t *seg, float seg_start_temp, int64_t seg_start_time_us,
                               int64_t now_us, bool holding)
{
    if (holding) {
        return seg->target_temp;
    }
    float elapsed_seg_s = (float)(now_us - seg_start_time_us) / 1000000.0f;
    float ramp_per_sec = seg->ramp_rate / 3600.0f;
    float setpoint = seg_start_temp + ramp_per_sec * elapsed_seg_s;

    if (seg->ramp_rate >= 0) {
        if (setpoint > seg->target_temp) {
            setpoint = seg->target_temp;
        }
    } else {
        if (setpoint < seg->target_temp) {
            setpoint = seg->target_temp;
        }
    }
    return setpoint;
}

bool at_target_predicate(float current_temp, float setpoint, float target_temp)
{
    return fabsf(current_temp - target_temp) < 2.0f && fabsf(setpoint - target_temp) < 0.5f;
}
