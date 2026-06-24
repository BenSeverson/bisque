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

/* Full planned ramp+hold duration of a segment that begins at `start_temp`. */
static float segment_planned_s(const firing_segment_t *seg, float start_temp)
{
    float total = 0.0f;
    float ramp_per_sec = seg->ramp_rate / 3600.0f;
    if (fabsf(ramp_per_sec) > 0.0001f) {
        total += fabsf((seg->target_temp - start_temp) / ramp_per_sec);
    }
    if (seg->hold_time != FIRING_HOLD_INDEFINITE) {
        total += (float)seg->hold_time * 60.0f;
    }
    return total;
}

uint32_t firing_remaining_s(const firing_profile_t *profile, int current_segment, float current_temp, bool holding,
                            float hold_elapsed_s)
{
    if (!profile || current_segment < 0 || current_segment >= profile->segment_count) {
        return 0;
    }

    float remaining = 0.0f;

    /* Current segment: only the remaining hold if we're already holding,
       otherwise the remaining ramp (from where the kiln actually is) plus the
       full hold. */
    const firing_segment_t *cur = &profile->segments[current_segment];
    float cur_hold_s = (cur->hold_time == FIRING_HOLD_INDEFINITE) ? 0.0f : (float)cur->hold_time * 60.0f;
    if (holding) {
        float hold_left = cur_hold_s - hold_elapsed_s;
        if (hold_left > 0.0f) {
            remaining += hold_left;
        }
    } else {
        float ramp_per_sec = cur->ramp_rate / 3600.0f;
        float delta = cur->target_temp - current_temp;
        /* Count ramp time only while still moving toward the target — an
           overshoot shouldn't add negative time. */
        if (fabsf(ramp_per_sec) > 0.0001f &&
            ((ramp_per_sec > 0.0f && delta > 0.0f) || (ramp_per_sec < 0.0f && delta < 0.0f))) {
            remaining += fabsf(delta / ramp_per_sec);
        }
        remaining += cur_hold_s;
    }

    /* Later segments: full planned duration, each from the previous target. */
    float seg_start = cur->target_temp;
    for (int i = current_segment + 1; i < profile->segment_count; i++) {
        remaining += segment_planned_s(&profile->segments[i], seg_start);
        seg_start = profile->segments[i].target_temp;
    }

    return (uint32_t)remaining;
}
