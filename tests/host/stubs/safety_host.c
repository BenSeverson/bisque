#include "safety_host.h"

#include "freertos/event_groups.h"

static EventGroupHandle_t s_event_group;
static bool s_emergency;
static float s_max_temp = 1300.0f;
static float s_last_duty;
static bool s_vent_active;
static safety_trip_cause_t s_trip_cause = SAFETY_TRIP_NONE;

static EventGroupHandle_t event_group_get(void)
{
    if (!s_event_group) {
        s_event_group = xEventGroupCreate();
    }
    return s_event_group;
}

esp_err_t safety_init(int ssr_pin, float max_safe_temp)
{
    (void)ssr_pin;
    s_max_temp = max_safe_temp;
    s_emergency = false;
    s_last_duty = 0.0f;
    s_vent_active = false;
    return ESP_OK;
}

void safety_init_io(int alarm_gpio, int vent_gpio)
{
    (void)alarm_gpio;
    (void)vent_gpio;
}

void safety_trigger_alarm(int pattern)
{
    (void)pattern;
}

void safety_update_vent(bool is_firing, float current_temp_c)
{
    /* Mirror the real driver: vent on during firing below 700°C. */
    s_vent_active = is_firing && current_temp_c < 700.0f;
}

EventGroupHandle_t safety_get_event_group(void)
{
    return event_group_get();
}

void safety_emergency_stop_cause(safety_trip_cause_t cause)
{
    s_emergency = true;
    s_last_duty = 0.0f;
    if (s_trip_cause == SAFETY_TRIP_NONE) {
        s_trip_cause = cause;
    }
    xEventGroupSetBits(event_group_get(), SAFETY_BIT_EMERGENCY_STOP);
}

void safety_emergency_stop(void)
{
    safety_emergency_stop_cause(SAFETY_TRIP_OTHER);
}

safety_trip_cause_t safety_get_trip_cause(void)
{
    return s_trip_cause;
}

void safety_clear_emergency(void)
{
    s_emergency = false;
    s_trip_cause = SAFETY_TRIP_NONE;
    xEventGroupClearBits(event_group_get(), SAFETY_BIT_EMERGENCY_STOP);
}

bool safety_is_emergency(void)
{
    return s_emergency;
}

void safety_set_max_temp(float max_safe_temp)
{
    s_max_temp = max_safe_temp;
}

float safety_get_max_temp(void)
{
    return s_max_temp;
}

void safety_set_tc_offset(float offset_c)
{
    (void)offset_c;
}

void safety_set_ssr(float duty)
{
    if (s_emergency) {
        s_last_duty = 0.0f;
        return;
    }
    if (duty < 0.0f) {
        duty = 0.0f;
    }
    if (duty > 1.0f) {
        duty = 1.0f;
    }
    s_last_duty = duty;
}

void safety_task(void *param)
{
    (void)param;
}

/* ── test-only accessors ───────────────────────────────────────────────── */

float safety_test_last_duty(void)
{
    return s_last_duty;
}

bool safety_test_vent_active(void)
{
    return s_vent_active;
}

void safety_test_reset(void)
{
    s_emergency = false;
    s_max_temp = 1300.0f;
    s_last_duty = 0.0f;
    s_vent_active = false;
    s_trip_cause = SAFETY_TRIP_NONE;
    if (s_event_group) {
        xEventGroupClearBits(s_event_group, 0xFFFFFFFFU);
    }
}
