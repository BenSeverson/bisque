#include "safety_host.h"

#include "freertos/event_groups.h"

static EventGroupHandle_t s_event_group;
static bool s_emergency;
static float s_max_temp = 1300.0f;
static float s_last_duty;
static unsigned s_ssr_calls;
static bool s_vent_active;
/* The stub defaults to a vent being fitted — the case a test has something to
   assert about. The real driver decides from the GPIO, which safety_init_io()
   below mirrors for a test that wants the vent-less default kiln. */
static bool s_vent_fitted = true;
/* Unlike the vent, the lid stub defaults to NOT_FITTED — the case where there is
   nothing to assert unless a test opts in via safety_test_set_lid(). Note this
   is no longer the production default: CONFIG_KILN_PIN_LID_SWITCH defaults to
   GPIO 4 to match the rev B PCB, and -1 is the opt-out for a build with no
   switch. */
static lid_state_t s_lid_state = LID_STATE_NOT_FITTED;
static bool s_lid_interlock_armed;
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

void safety_init_io(int alarm_gpio, int vent_gpio, int lid_gpio)
{
    (void)alarm_gpio;
    s_vent_fitted = vent_gpio >= 0;
    s_vent_active = false;
    s_lid_state = (lid_gpio >= 0) ? LID_STATE_CLOSED : LID_STATE_NOT_FITTED;
}

void safety_trigger_alarm(int pattern)
{
    (void)pattern;
}

void safety_update_vent(bool is_firing, float current_temp_c)
{
    /* Mirror the real driver: vent on during firing below 700°C, and never
       while an emergency stop is latched. */
    if (!s_vent_fitted) {
        return;
    }
    s_vent_active = !s_emergency && is_firing && current_temp_c < 700.0f;
}

vent_state_t safety_get_vent_state(void)
{
    if (!s_vent_fitted) {
        return VENT_STATE_NOT_FITTED;
    }
    return s_vent_active ? VENT_STATE_ON : VENT_STATE_OFF;
}

lid_state_t safety_get_lid_state(void)
{
    return s_lid_state;
}

void safety_set_lid_interlock_armed(bool armed)
{
    s_lid_interlock_armed = armed;
}

EventGroupHandle_t safety_get_event_group(void)
{
    return event_group_get();
}

void safety_emergency_stop_cause(safety_trip_cause_t cause)
{
    s_emergency = true;
    s_last_duty = 0.0f;
    /* The real driver cuts the vent relay here too, and a scenario test that
       asserts on the vent after a trip must see the same thing. */
    s_vent_active = false;
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
    s_ssr_calls++;
    /* Mirror ssr_window_apply()'s gate: an armed interlock against an open lid
       holds the output off just as an emergency stop does, so a scenario test
       sees the same duty the device would drive. */
    if (s_emergency || (s_lid_interlock_armed && s_lid_state == LID_STATE_OPEN)) {
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

float safety_get_ssr_duty(void)
{
    return s_last_duty;
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

unsigned safety_test_ssr_call_count(void)
{
    return s_ssr_calls;
}

bool safety_test_vent_active(void)
{
    return s_vent_active;
}

/* Test hook: place the lid directly, bypassing debounce. The debounce itself is
   covered by test_safety_helpers.c; scenario tests care about the settled
   state. Setting a state also marks the switch as fitted. */
void safety_test_set_lid(lid_state_t state)
{
    s_lid_state = state;
}

bool safety_test_lid_interlock_armed(void)
{
    return s_lid_interlock_armed;
}

void safety_test_reset(void)
{
    s_emergency = false;
    s_max_temp = 1300.0f;
    s_last_duty = 0.0f;
    s_ssr_calls = 0;
    s_vent_active = false;
    s_vent_fitted = true;
    s_lid_state = LID_STATE_NOT_FITTED;
    s_lid_interlock_armed = false;
    s_trip_cause = SAFETY_TRIP_NONE;
    if (s_event_group) {
        xEventGroupClearBits(s_event_group, 0xFFFFFFFFU);
    }
}
