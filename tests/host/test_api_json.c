/**
 * Contract tests for the REST-API JSON builders extracted into api_json.c.
 *
 * Each test drives one builder with a fixture input, parses the resulting JSON
 * back through cJSON, and asserts every key exists with the expected type and
 * value. The same JSON is also written to ${FIXTURE_DIR}/<endpoint>.json (when
 * the BISQUE_FIXTURE_DIR env var is set) so the web_ui contract test can
 * validate it against the frontend's zod schemas — this is the cross-language
 * half of the contract.
 */
#include "api_json.h"
#include "cJSON.h"
#include "cone_table.h"
#include "firing_history.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "unity.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

void setUp(void)
{
}
void tearDown(void)
{
}

/* ── Fixture dumping ─────────────────────────────────────────────────────── */

/* Create dir and every missing parent. mkdir(2) alone doesn't, and CMake hands
 * us a path several levels deep (build/fixtures/api/...). */
static void ensure_dir(const char *path)
{
    char tmp[512];
    snprintf(tmp, sizeof(tmp), "%s", path);
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0755);
            *p = '/';
        }
    }
    mkdir(tmp, 0755);
}

/* Dump JSON to ${BISQUE_FIXTURE_DIR}/<name>.json when that env var is set.
 * Used by CI to feed the JS-side contract validator; ignored locally. */
static void dump_fixture(const char *name, cJSON *root)
{
    const char *dir = getenv("BISQUE_FIXTURE_DIR");
    if (!dir || !dir[0]) {
        return;
    }
    ensure_dir(dir);

    char path[512];
    snprintf(path, sizeof(path), "%s/%s.json", dir, name);
    FILE *f = fopen(path, "w");
    if (!f) {
        fprintf(stderr, "dump_fixture: cannot open %s\n", path);
        return;
    }
    char *json = cJSON_PrintUnformatted(root);
    if (json) {
        fputs(json, f);
        free(json);
    }
    fclose(f);
}

/* Convenience assertions. */
#define ASSERT_HAS_KEY(obj, key) TEST_ASSERT_NOT_NULL_MESSAGE(cJSON_GetObjectItem(obj, key), "missing key: " key)

static void assert_string_field(cJSON *obj, const char *key)
{
    cJSON *j = cJSON_GetObjectItem(obj, key);
    TEST_ASSERT_NOT_NULL_MESSAGE(j, key);
    TEST_ASSERT_TRUE_MESSAGE(cJSON_IsString(j), key);
}
static void assert_number_field(cJSON *obj, const char *key)
{
    cJSON *j = cJSON_GetObjectItem(obj, key);
    TEST_ASSERT_NOT_NULL_MESSAGE(j, key);
    TEST_ASSERT_TRUE_MESSAGE(cJSON_IsNumber(j), key);
}
static void assert_bool_field(cJSON *obj, const char *key)
{
    cJSON *j = cJSON_GetObjectItem(obj, key);
    TEST_ASSERT_NOT_NULL_MESSAGE(j, key);
    TEST_ASSERT_TRUE_MESSAGE(cJSON_IsBool(j), key);
}

/* ── build_status_json ───────────────────────────────────────────────────── */

static void test_status_full_shape(void)
{
    firing_progress_t prog = {
        .is_active = true,
        .current_temp = 723.4f,
        .target_temp = 1063.0f,
        .current_segment = 2,
        .total_segments = 4,
        .elapsed_time = 3600,
        .estimated_remaining = 7200,
        .status = FIRING_STATUS_HEATING,
    };
    strcpy(prog.profile_id, "bisque-cone-04");

    thermocouple_reading_t tc = {
        .temperature_c = 723.4f,
        .internal_temp_c = 28.5f,
        .fault = 0,
        .timestamp_us = 1234567,
    };

    cJSON *root = build_status_json(&prog, &tc, 5.0f, 0.625f, VENT_STATE_ON, LID_STATE_CLOSED);
    TEST_ASSERT_NOT_NULL(root);

    /* Element power, rounded to whole percent (#180). */
    TEST_ASSERT_EQUAL_INT(63, cJSON_GetObjectItem(root, "dutyPercent")->valueint);

    /* Downdraft vent relay (#184). */
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "ventActive")));

    /* currentTemp carries the tc offset so it matches the WebSocket feed; the
       nested thermocouple block keeps the raw reading. */
    TEST_ASSERT_EQUAL_FLOAT(728.4f, cJSON_GetObjectItem(root, "currentTemp")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(723.4f,
                            cJSON_GetObjectItem(cJSON_GetObjectItem(root, "thermocouple"), "temperature")->valuedouble);

    assert_bool_field(root, "isActive");
    assert_string_field(root, "profileId");
    assert_number_field(root, "currentTemp");
    assert_number_field(root, "targetTemp");
    assert_number_field(root, "currentSegment");
    assert_number_field(root, "totalSegments");
    assert_number_field(root, "elapsedTime");
    assert_number_field(root, "estimatedTimeRemaining");
    assert_number_field(root, "dutyPercent");
    assert_bool_field(root, "ventActive");
    assert_string_field(root, "status");

    TEST_ASSERT_EQUAL_STRING("heating", cJSON_GetObjectItem(root, "status")->valuestring);
    TEST_ASSERT_EQUAL_STRING("bisque-cone-04", cJSON_GetObjectItem(root, "profileId")->valuestring);

    cJSON *tc_obj = cJSON_GetObjectItem(root, "thermocouple");
    TEST_ASSERT_NOT_NULL(tc_obj);
    assert_number_field(tc_obj, "temperature");
    assert_number_field(tc_obj, "internalTemp");
    assert_bool_field(tc_obj, "fault");
    assert_bool_field(tc_obj, "openCircuit");
    assert_bool_field(tc_obj, "shortGnd");
    assert_bool_field(tc_obj, "shortVcc");

    dump_fixture("status", root);
    cJSON_Delete(root);
}

static void test_status_zeros_temp_when_fault(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_ERROR};
    thermocouple_reading_t tc = {
        .temperature_c = 999.0f,
        .fault = TC_FAULT_OPEN_CIRCUIT,
    };
    cJSON *root = build_status_json(&prog, &tc, 5.0f, 0.0f, VENT_STATE_OFF, LID_STATE_NOT_FITTED);
    /* Every other status fixture is a healthy heating kiln, so the fault flags
       were only ever serialized false and the frontend's rendering of a raised
       one went unvalidated end to end (#174). */
    dump_fixture("status_faulted", root);

    /* Top-level currentTemp is zero-clamped on fault (UI shouldn't render the
     * stale last-read temp) — the offset is not applied through a fault. Inner
     * thermocouple.temperature still exposes the raw value for diagnostics. */
    TEST_ASSERT_EQUAL_FLOAT(0.0f, cJSON_GetObjectItem(root, "currentTemp")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(999.0f,
                            cJSON_GetObjectItem(cJSON_GetObjectItem(root, "thermocouple"), "temperature")->valuedouble);
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(cJSON_GetObjectItem(root, "thermocouple"), "openCircuit")));
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(cJSON_GetObjectItem(root, "thermocouple"), "shortGnd")));
    TEST_ASSERT_EQUAL_INT(0, cJSON_GetObjectItem(root, "dutyPercent")->valueint);
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(root, "ventActive")));
    cJSON_Delete(root);
}

/* The vent GPIO defaults to disabled (CONFIG_KILN_PIN_VENT = -1), so most kilns
 * have no vent relay to report on. Sending `ventActive: false` for those would
 * be indistinguishable from a fitted vent that happens to be off, and every such
 * kiln would render a permanently dark indicator for hardware it doesn't have.
 * The key is dropped instead, which is what lets the client hide the whole
 * control (#184). */
static void test_status_omits_vent_when_not_fitted(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_HEATING, .target_temp = 500.0f};
    thermocouple_reading_t tc = {.temperature_c = 480.0f};

    cJSON *root = build_status_json(&prog, &tc, 0.0f, 0.5f, VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED);
    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "ventActive"));
    /* Everything else is still there — a missing vent is not a degraded status. */
    assert_number_field(root, "dutyPercent");
    assert_string_field(root, "status");

    dump_fixture("status_no_vent", root);
    cJSON_Delete(root);
}

/* The lid GPIO defaults to disabled (CONFIG_KILN_PIN_LID_SWITCH = -1), so most
 * kilns have no switch to report on. `lidOpen: false` for those would be
 * indistinguishable from a fitted switch that happens to be closed, and every
 * such kiln would render an indicator for hardware it doesn't have. Omit the
 * key entirely instead — the same contract ventActive follows (#83). */
static void test_status_omits_lid_when_not_fitted(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_HEATING, .target_temp = 500.0f};
    thermocouple_reading_t tc = {.temperature_c = 480.0f};

    cJSON *root = build_status_json(&prog, &tc, 0.0f, 0.5f, VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED);
    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "lidOpen"));
    /* Everything else is still there — a missing lid switch is not a degraded
       status. */
    assert_number_field(root, "dutyPercent");
    assert_string_field(root, "status");

    dump_fixture("status_no_lid", root);
    cJSON_Delete(root);
}

/* A kiln that is paused because its lid is up — the pause-mode steady state. */
static void test_status_reports_an_open_lid(void)
{
    firing_progress_t prog = {.is_active = true, .status = FIRING_STATUS_PAUSED, .target_temp = 700.0f};
    thermocouple_reading_t tc = {.temperature_c = 640.0f};

    cJSON *root = build_status_json(&prog, &tc, 0.0f, 0.0f, VENT_STATE_ON, LID_STATE_OPEN);
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "lidOpen")));

    dump_fixture("status_lid_open", root);
    cJSON_Delete(root);
}

/* Fitted and shut must be an explicit false, not an omission — that is the
   distinction the whole not-fitted rule rests on. */
static void test_status_reports_a_closed_lid(void)
{
    firing_progress_t prog = {.is_active = true, .status = FIRING_STATUS_HEATING, .target_temp = 700.0f};
    thermocouple_reading_t tc = {.temperature_c = 640.0f};

    cJSON *root = build_status_json(&prog, &tc, 0.0f, 0.5f, VENT_STATE_ON, LID_STATE_CLOSED);
    cJSON *j = cJSON_GetObjectItem(root, "lidOpen");
    TEST_ASSERT_NOT_NULL(j);
    TEST_ASSERT_TRUE(cJSON_IsFalse(j));
    cJSON_Delete(root);
}

/* dutyPercent is a percentage in the UI — a value outside 0..100 would render
 * as a nonsense "Element power: 140%" or drive a progress bar off its track.
 * safety_get_ssr_duty() already clamps, so this guards the builder against a
 * future caller that doesn't (and against a NaN reaching lroundf, which is
 * undefined). */
static void test_status_clamps_duty(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_HEATING};
    thermocouple_reading_t tc = {.temperature_c = 500.0f};

    cJSON *over = build_status_json(&prog, &tc, 0.0f, 1.4f, VENT_STATE_OFF, LID_STATE_NOT_FITTED);
    TEST_ASSERT_EQUAL_INT(100, cJSON_GetObjectItem(over, "dutyPercent")->valueint);
    cJSON_Delete(over);

    cJSON *under = build_status_json(&prog, &tc, 0.0f, -0.2f, VENT_STATE_OFF, LID_STATE_NOT_FITTED);
    TEST_ASSERT_EQUAL_INT(0, cJSON_GetObjectItem(under, "dutyPercent")->valueint);
    cJSON_Delete(under);

    cJSON *nan_duty = build_status_json(&prog, &tc, 0.0f, NAN, VENT_STATE_OFF, LID_STATE_NOT_FITTED);
    TEST_ASSERT_EQUAL_INT(0, cJSON_GetObjectItem(nan_duty, "dutyPercent")->valueint);
    cJSON_Delete(nan_duty);
}

/* ── build_profile_json ──────────────────────────────────────────────────── */

static firing_profile_t make_fixture_profile(void)
{
    firing_profile_t p = {0};
    strcpy(p.id, "test-bisque");
    strcpy(p.name, "Test Bisque");
    strcpy(p.description, "Two-segment test");
    p.max_temp = 1060.0f;
    p.estimated_duration = 540;
    p.segment_count = 2;
    strcpy(p.segments[0].id, "seg-1");
    strcpy(p.segments[0].name, "Water Smoke");
    p.segments[0].ramp_rate = 80.0f;
    p.segments[0].target_temp = 220.0f;
    p.segments[0].hold_time = 0;
    strcpy(p.segments[1].id, "seg-2");
    strcpy(p.segments[1].name, "Final Ramp");
    p.segments[1].ramp_rate = 150.0f;
    p.segments[1].target_temp = 1060.0f;
    p.segments[1].hold_time = 10;
    return p;
}

static void test_profile_shape(void)
{
    firing_profile_t p = make_fixture_profile();
    cJSON *root = build_profile_json(&p);

    assert_string_field(root, "id");
    assert_string_field(root, "name");
    assert_string_field(root, "description");
    assert_number_field(root, "maxTemp");
    assert_number_field(root, "estimatedDuration");

    cJSON *segs = cJSON_GetObjectItem(root, "segments");
    TEST_ASSERT_NOT_NULL(segs);
    TEST_ASSERT_TRUE(cJSON_IsArray(segs));
    TEST_ASSERT_EQUAL_INT(2, cJSON_GetArraySize(segs));

    cJSON *seg0 = cJSON_GetArrayItem(segs, 0);
    assert_string_field(seg0, "id");
    assert_string_field(seg0, "name");
    assert_number_field(seg0, "rampRate");
    assert_number_field(seg0, "targetTemp");
    assert_number_field(seg0, "holdTime");
    TEST_ASSERT_EQUAL_STRING("Water Smoke", cJSON_GetObjectItem(seg0, "name")->valuestring);
    TEST_ASSERT_EQUAL_FLOAT(80.0f, cJSON_GetObjectItem(seg0, "rampRate")->valuedouble);

    dump_fixture("profile", root);
    cJSON_Delete(root);
}

/* An indefinite hold serializes as the sentinel 0xFFFF, not as an absent or
   negative holdTime. The frontend gives it dedicated handling (utils/profile.ts
   treats HOLD_UNTIL_SKIP as an unschedulable hold), so the value has to survive
   the round trip — and the only profile fixture until now was two ordinary
   timed segments (#174). */
static void test_profile_hold_until_skip(void)
{
    firing_profile_t p = make_fixture_profile();
    p.segments[1].hold_time = FIRING_HOLD_INDEFINITE;

    cJSON *root = build_profile_json(&p);
    cJSON *seg1 = cJSON_GetArrayItem(cJSON_GetObjectItem(root, "segments"), 1);
    TEST_ASSERT_EQUAL_INT(65535, cJSON_GetObjectItem(seg1, "holdTime")->valueint);

    dump_fixture("profile_hold_until_skip", root);
    cJSON_Delete(root);
}

/* GET /history on a device that has never fired. handle_get_history builds the
   array itself, so this pins the shape that loop produces at count == 0: an
   empty array, not null and not an object. The history view renders its empty
   state off exactly that. */
static void test_history_empty_list(void)
{
    cJSON *arr = cJSON_CreateArray();
    TEST_ASSERT_TRUE(cJSON_IsArray(arr));
    TEST_ASSERT_EQUAL_INT(0, cJSON_GetArraySize(arr));
    dump_fixture("history_empty", arr);
    cJSON_Delete(arr);
}

/* ── build_settings_json ─────────────────────────────────────────────────── */

static void test_settings_shape_redacts_token(void)
{
    kiln_settings_t s = {
        .temp_unit = 'C',
        .max_safe_temp = 1300.0f,
        .alarm_enabled = true,
        .auto_shutdown = false,
        .notifications_enabled = true,
        .tc_offset_c = -2.5f,
        .element_watts = 2400.0f,
        .electricity_cost_kwh = 0.18f,
        .lid_mode = LID_MODE_PAUSE,
    };
    strcpy(s.webhook_url, "https://example.test/kiln");
    strcpy(s.api_token, "super-secret-token");

    cJSON *root = build_settings_json(&s);

    assert_string_field(root, "tempUnit");
    assert_number_field(root, "maxSafeTemp");
    assert_bool_field(root, "alarmEnabled");
    assert_bool_field(root, "autoShutdown");
    assert_bool_field(root, "notificationsEnabled");
    assert_number_field(root, "tcOffsetC");
    assert_string_field(root, "webhookUrl");
    assert_bool_field(root, "apiTokenSet");
    assert_number_field(root, "elementWatts");
    assert_number_field(root, "electricityCostKwh");
    assert_string_field(root, "lidMode");

    /* Token value must never appear in the response. */
    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "apiToken"));
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "apiTokenSet")));

    TEST_ASSERT_EQUAL_STRING("C", cJSON_GetObjectItem(root, "tempUnit")->valuestring);
    TEST_ASSERT_EQUAL_FLOAT(-2.5f, cJSON_GetObjectItem(root, "tcOffsetC")->valuedouble);

    dump_fixture("settings", root);
    cJSON_Delete(root);
}

static void test_settings_apiTokenSet_false_when_empty(void)
{
    kiln_settings_t s = {.temp_unit = 'F'};
    cJSON *root = build_settings_json(&s);
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(root, "apiTokenSet")));
    cJSON_Delete(root);
}

/* lidMode is a setting, not a hardware reading, so unlike lidOpen it is always
   present — a client renders the selector whether or not a switch is fitted. */
static void test_settings_always_carry_the_lid_mode(void)
{
    kiln_settings_t s = {.temp_unit = 'C', .max_safe_temp = 1300.0f, .lid_mode = LID_MODE_INTERLOCK};
    cJSON *root = build_settings_json(&s);

    cJSON *j = cJSON_GetObjectItem(root, "lidMode");
    TEST_ASSERT_NOT_NULL(j);
    TEST_ASSERT_TRUE(cJSON_IsString(j));
    TEST_ASSERT_EQUAL_STRING("interlock", cJSON_GetStringValue(j));
    cJSON_Delete(root);
}

static void test_lid_mode_string_round_trip(void)
{
    const lid_mode_t modes[] = {LID_MODE_WARN, LID_MODE_PAUSE, LID_MODE_INTERLOCK};
    for (unsigned i = 0; i < sizeof(modes) / sizeof(modes[0]); i++) {
        lid_mode_t back;
        TEST_ASSERT_TRUE(lid_mode_from_string(lid_mode_to_string(modes[i]), &back));
        TEST_ASSERT_EQUAL_INT(modes[i], back);
    }
    /* An unrecognized mode must be rejected rather than silently defaulted: a
       client typo that quietly disarmed an interlock would be invisible. */
    lid_mode_t unused;
    TEST_ASSERT_FALSE(lid_mode_from_string("ajar", &unused));
    TEST_ASSERT_FALSE(lid_mode_from_string("", &unused));
    TEST_ASSERT_FALSE(lid_mode_from_string(NULL, &unused));
}

/* ── build_history_record_json ───────────────────────────────────────────── */

static void test_history_record_shape(void)
{
    history_record_t rec = {
        .id = 42,
        .start_time = 1700000000,
        .peak_temp_c = 1063.5f,
        .duration_s = 14400,
        .outcome = HISTORY_OUTCOME_COMPLETE,
        .error_code = 0,
    };
    strcpy(rec.profile_name, "Bisque Cone 04");
    strcpy(rec.profile_id, "bisque-cone-04");

    cJSON *root = build_history_record_json(&rec);

    assert_number_field(root, "id");
    assert_number_field(root, "startTime");
    assert_string_field(root, "profileName");
    assert_string_field(root, "profileId");
    assert_number_field(root, "peakTemp");
    assert_number_field(root, "durationS");
    assert_string_field(root, "outcome");
    assert_number_field(root, "errorCode");

    TEST_ASSERT_EQUAL_STRING("complete", cJSON_GetObjectItem(root, "outcome")->valuestring);
    TEST_ASSERT_EQUAL_INT(42, (int)cJSON_GetObjectItem(root, "id")->valuedouble);

    dump_fixture("history_record", root);
    cJSON_Delete(root);
}

static void test_history_outcome_strings(void)
{
    history_record_t rec = {0};
    const struct {
        history_outcome_t v;
        const char *s;
    } cases[] = {
        {HISTORY_OUTCOME_COMPLETE, "complete"},
        {HISTORY_OUTCOME_ERROR, "error"},
        {HISTORY_OUTCOME_ABORTED, "aborted"},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        rec.outcome = cases[i].v;
        cJSON *root = build_history_record_json(&rec);
        TEST_ASSERT_EQUAL_STRING(cases[i].s, cJSON_GetObjectItem(root, "outcome")->valuestring);
        cJSON_Delete(root);
    }
}

/* ── build_cone_table_json ───────────────────────────────────────────────── */

static void test_cone_table_shape(void)
{
    cJSON *arr = build_cone_table_json();
    TEST_ASSERT_TRUE(cJSON_IsArray(arr));
    TEST_ASSERT_TRUE(cJSON_GetArraySize(arr) > 0);

    cJSON *first = cJSON_GetArrayItem(arr, 0);
    assert_number_field(first, "id");
    assert_string_field(first, "name");
    assert_number_field(first, "slowTempC");
    assert_number_field(first, "mediumTempC");
    assert_number_field(first, "fastTempC");

    /* Every entry should have the full key set. */
    for (int i = 0; i < cJSON_GetArraySize(arr); i++) {
        cJSON *e = cJSON_GetArrayItem(arr, i);
        ASSERT_HAS_KEY(e, "id");
        ASSERT_HAS_KEY(e, "name");
        ASSERT_HAS_KEY(e, "slowTempC");
        ASSERT_HAS_KEY(e, "mediumTempC");
        ASSERT_HAS_KEY(e, "fastTempC");
    }

    dump_fixture("cone_table", arr);
    cJSON_Delete(arr);
}

/* ── cone_fire_generate → build_profile_json ─────────────────────────────── */

/* The demo's mock server generates its own cone-fire schedule in TypeScript
 * (web_ui/mock-server/router.ts) rather than calling this code. Its final ramp
 * rates had drifted to {60, 100, 150} against s_speed_ramp's {60, 150, 300}, so
 * the public demo handed out a schedule the device would never fire — and once
 * profiles started naming a nearest cone (#179), a fast cone 6 read as cone 7.
 *
 * All three speeds go into one fixture so the web contract test can pin the
 * mock's whole generated schedule, not just the column the demo happens to
 * default to. Preheat and slow-cool are on so every optional segment is
 * covered. */
static void test_cone_fire_profiles(void)
{
    cJSON *arr = cJSON_CreateArray();
    TEST_ASSERT_NOT_NULL(arr);

    for (int speed = CONE_SPEED_SLOW; speed <= CONE_SPEED_FAST; speed++) {
        firing_profile_t p;
        TEST_ASSERT_EQUAL(ESP_OK, cone_fire_generate(CONE_6, (cone_speed_t)speed, true, true, &p));
        cJSON *root = build_profile_json(&p);
        TEST_ASSERT_NOT_NULL(root);
        cJSON_AddItemToArray(arr, root);
    }

    TEST_ASSERT_EQUAL_INT(3, cJSON_GetArraySize(arr));

    /* Spot-check the field the mock drifted on: the last segment before the
     * cooling ones ramps at the speed's own rate to that column's temperature. */
    const float expected_rate[3] = {60.0f, 150.0f, 300.0f};
    for (int speed = 0; speed < 3; speed++) {
        cJSON *segs = cJSON_GetObjectItem(cJSON_GetArrayItem(arr, speed), "segments");
        TEST_ASSERT_NOT_NULL(segs);
        /* preheat, water smoke, quartz, peak ramp, then two cooling segments */
        TEST_ASSERT_EQUAL_INT(6, cJSON_GetArraySize(segs));
        cJSON *peak = cJSON_GetArrayItem(segs, 3);
        TEST_ASSERT_EQUAL_FLOAT(expected_rate[speed], cJSON_GetObjectItem(peak, "rampRate")->valuedouble);
        TEST_ASSERT_EQUAL_FLOAT(cone_target_temp_c(CONE_6, (cone_speed_t)speed),
                                cJSON_GetObjectItem(peak, "targetTemp")->valuedouble);
    }

    dump_fixture("cone_fire_profiles", arr);
    cJSON_Delete(arr);
}

/* ── build_autotune_status_json ──────────────────────────────────────────── */

static void test_autotune_status_idle(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_IDLE, .current_temp = 24.0f};
    cJSON *root = build_autotune_status_json(&prog, AUTOTUNE_IDLE, 2.5f, 0.5f, 1.0f);

    assert_string_field(root, "state");
    assert_number_field(root, "elapsedTime");
    assert_number_field(root, "targetTemp");
    assert_number_field(root, "currentTemp");

    cJSON *gains = cJSON_GetObjectItem(root, "currentGains");
    TEST_ASSERT_NOT_NULL(gains);
    assert_number_field(gains, "kp");
    assert_number_field(gains, "ki");
    assert_number_field(gains, "kd");

    TEST_ASSERT_EQUAL_STRING("idle", cJSON_GetObjectItem(root, "state")->valuestring);
    TEST_ASSERT_EQUAL_FLOAT(2.5f, cJSON_GetObjectItem(gains, "kp")->valuedouble);

    dump_fixture("autotune_status", root);
    cJSON_Delete(root);
}

static void test_autotune_status_running_vs_stopped(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_AUTOTUNE};
    cJSON *root = build_autotune_status_json(&prog, AUTOTUNE_RELAY_CYCLING, 1, 1, 1);
    TEST_ASSERT_EQUAL_STRING("running", cJSON_GetObjectItem(root, "state")->valuestring);
    cJSON_Delete(root);

    prog.status = FIRING_STATUS_HEATING;
    root = build_autotune_status_json(&prog, AUTOTUNE_IDLE, 1, 1, 1);
    TEST_ASSERT_EQUAL_STRING("stopped", cJSON_GetObjectItem(root, "state")->valuestring);
    cJSON_Delete(root);
}

/* The whole point of #216: a finished run, a failed run, and a never-started
   one used to be byte-identical "idle" frames. The engine calls do_stop() as
   soon as a tune ends, so every one of these carries FIRING_STATUS_IDLE and the
   distinction can only come from the autotune state. */
static void test_autotune_terminal_states_are_distinct(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_IDLE};

    cJSON *root = build_autotune_status_json(&prog, AUTOTUNE_COMPLETE, 1, 1, 1);
    TEST_ASSERT_EQUAL_STRING("complete", cJSON_GetObjectItem(root, "state")->valuestring);
    cJSON_Delete(root);

    root = build_autotune_status_json(&prog, AUTOTUNE_FAILED, 1, 1, 1);
    TEST_ASSERT_EQUAL_STRING("failed", cJSON_GetObjectItem(root, "state")->valuestring);
    cJSON_Delete(root);

    root = build_autotune_status_json(&prog, AUTOTUNE_IDLE, 1, 1, 1);
    TEST_ASSERT_EQUAL_STRING("idle", cJSON_GetObjectItem(root, "state")->valuestring);
    cJSON_Delete(root);
}

/* A tune still running reports "running" whatever its internal phase, and a
   terminal outcome is never masked by a stale progress status. */
static void test_autotune_running_outranks_terminal_state(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_AUTOTUNE};
    for (int s = AUTOTUNE_IDLE; s <= AUTOTUNE_FAILED; s++) {
        cJSON *root = build_autotune_status_json(&prog, (autotune_state_t)s, 1, 1, 1);
        TEST_ASSERT_EQUAL_STRING("running", cJSON_GetObjectItem(root, "state")->valuestring);
        cJSON_Delete(root);
    }
}

/* ── build_pid_json ──────────────────────────────────────────────────────── */

static void test_pid_shape(void)
{
    cJSON *root = build_pid_json(18.0f, 0.12f, 240.0f);

    assert_number_field(root, "kp");
    assert_number_field(root, "ki");
    assert_number_field(root, "kd");
    TEST_ASSERT_EQUAL_FLOAT(18.0f, cJSON_GetObjectItem(root, "kp")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(0.12f, cJSON_GetObjectItem(root, "ki")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(240.0f, cJSON_GetObjectItem(root, "kd")->valuedouble);

    cJSON *defaults = cJSON_GetObjectItem(root, "defaults");
    TEST_ASSERT_NOT_NULL(defaults);
    assert_number_field(defaults, "kp");
    assert_number_field(defaults, "ki");
    assert_number_field(defaults, "kd");

    /* The defaults block must report the firmware's own fallbacks, not echo the
       live gains — a "restore defaults" button built on it would otherwise
       restore whatever was already there. */
    float def_kp, def_ki, def_kd;
    pid_default_gains(&def_kp, &def_ki, &def_kd);
    TEST_ASSERT_EQUAL_FLOAT(def_kp, cJSON_GetObjectItem(defaults, "kp")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(def_ki, cJSON_GetObjectItem(defaults, "ki")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(def_kd, cJSON_GetObjectItem(defaults, "kd")->valuedouble);

    cJSON *limits = cJSON_GetObjectItem(root, "limits");
    TEST_ASSERT_NOT_NULL(limits);
    TEST_ASSERT_EQUAL_FLOAT(PID_GAIN_MIN, cJSON_GetObjectItem(limits, "min")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(PID_GAIN_MAX, cJSON_GetObjectItem(limits, "max")->valuedouble);

    /* The bounds the client is told about have to be bounds the firmware would
       actually accept, or the form validates against a range POST /pid rejects. */
    TEST_ASSERT_TRUE(pid_gains_valid(PID_GAIN_MAX, PID_GAIN_MAX, PID_GAIN_MAX));
    TEST_ASSERT_TRUE(pid_gains_valid(def_kp, def_ki, def_kd));

    dump_fixture("pid", root);
    cJSON_Delete(root);
}

/* ── build_thermocouple_diag_json ────────────────────────────────────────── */

static void test_thermocouple_diag_shape(void)
{
    thermocouple_reading_t tc = {
        .temperature_c = 500.0f,
        .internal_temp_c = 25.0f,
        .fault = TC_FAULT_SHORT_GND,
        .timestamp_us = 100,
    };
    cJSON *root = build_thermocouple_diag_json(&tc, 250, -1.5f);

    assert_number_field(root, "temperatureC");
    assert_number_field(root, "internalTempC");
    assert_bool_field(root, "fault");
    assert_bool_field(root, "openCircuit");
    assert_bool_field(root, "shortGnd");
    assert_bool_field(root, "shortVcc");
    assert_number_field(root, "readingAgeMs");
    assert_number_field(root, "temperatureAdjustedC");
    assert_number_field(root, "tcOffsetC");

    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "shortGnd")));
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(root, "openCircuit")));
    TEST_ASSERT_EQUAL_FLOAT(498.5f, cJSON_GetObjectItem(root, "temperatureAdjustedC")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(-1.5f, cJSON_GetObjectItem(root, "tcOffsetC")->valuedouble);

    dump_fixture("thermocouple_diag", root);
    cJSON_Delete(root);
}

/* ── build_ws_temp_update_json ───────────────────────────────────────────── */

/* The socket's temp_update frame is the highest-frequency payload the firmware
   emits and, until #174, the only one with no fixture at all: it was assembled
   inline in ws_handler.c, which the host build cannot link. Its `data` block is
   the same progress field set GET /status puts at its top level, so this test
   also pins the two together — a client that parses one parses the other. */
static void test_ws_temp_update_shape(void)
{
    firing_progress_t prog = {
        .is_active = true,
        .current_temp = 980.0f,
        .target_temp = 1063.0f,
        .current_segment = 3,
        .total_segments = 4,
        .elapsed_time = 10800,
        .estimated_remaining = 1800,
        .delay_remaining = 0,
        .status = FIRING_STATUS_HOLDING,
    };
    strcpy(prog.profile_id, "bisque-cone-04");

    cJSON *root = build_ws_temp_update_json(&prog, 981.5f, 0.42f, VENT_STATE_ON, LID_STATE_CLOSED);
    TEST_ASSERT_NOT_NULL(root);

    assert_string_field(root, "type");
    TEST_ASSERT_EQUAL_STRING("temp_update", cJSON_GetObjectItem(root, "type")->valuestring);

    cJSON *data = cJSON_GetObjectItem(root, "data");
    TEST_ASSERT_NOT_NULL(data);
    assert_bool_field(data, "isActive");
    assert_string_field(data, "profileId");
    assert_number_field(data, "currentTemp");
    assert_number_field(data, "targetTemp");
    assert_number_field(data, "currentSegment");
    assert_number_field(data, "totalSegments");
    assert_number_field(data, "elapsedTime");
    assert_number_field(data, "estimatedTimeRemaining");
    assert_number_field(data, "delayRemaining");
    assert_number_field(data, "dutyPercent");
    assert_bool_field(data, "ventActive");
    assert_string_field(data, "status");

    TEST_ASSERT_EQUAL_FLOAT(981.5f, cJSON_GetObjectItem(data, "currentTemp")->valuedouble);
    TEST_ASSERT_EQUAL_INT(42, cJSON_GetObjectItem(data, "dutyPercent")->valueint);
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(data, "ventActive")));
    TEST_ASSERT_EQUAL_STRING("holding", cJSON_GetObjectItem(data, "status")->valuestring);

    /* The frame is telemetry only — no thermocouple diagnostics ride along, so
       a client must not be written to expect them here. */
    TEST_ASSERT_NULL(cJSON_GetObjectItem(data, "thermocouple"));

    dump_fixture("ws_temp_update", root);
    cJSON_Delete(root);
}

/* /status and the socket must agree field-for-field on the progress block, or a
   client that renders from both shows different numbers depending on which one
   arrived last. Compares the key sets rather than the values, since /status
   nests an extra thermocouple object the frame deliberately omits. */
static void assert_ws_and_status_agree(vent_state_t vent, lid_state_t lid)
{
    firing_progress_t prog = {.status = FIRING_STATUS_HEATING, .target_temp = 500.0f};
    thermocouple_reading_t tc = {.temperature_c = 480.0f};

    cJSON *status = build_status_json(&prog, &tc, 0.0f, 0.5f, vent, lid);
    cJSON *frame = build_ws_temp_update_json(&prog, 480.0f, 0.5f, vent, lid);
    cJSON *data = cJSON_GetObjectItem(frame, "data");

    for (cJSON *k = data->child; k; k = k->next) {
        TEST_ASSERT_NOT_NULL_MESSAGE(cJSON_GetObjectItem(status, k->string), k->string);
    }
    /* And nothing in /status beyond the block plus its thermocouple object. */
    for (cJSON *k = status->child; k; k = k->next) {
        if (strcmp(k->string, "thermocouple") == 0) {
            continue;
        }
        TEST_ASSERT_NOT_NULL_MESSAGE(cJSON_GetObjectItem(data, k->string), k->string);
    }

    cJSON_Delete(status);
    cJSON_Delete(frame);
}

static void test_ws_temp_update_matches_status_progress_block(void)
{
    assert_ws_and_status_agree(VENT_STATE_ON, LID_STATE_CLOSED);
    /* Repeated with the vent absent: `ventActive` is the first key either
       payload omits conditionally, so "they agree" now has to hold for a key
       that is missing from both, not only for one present in both. */
    assert_ws_and_status_agree(VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED);
    assert_ws_and_status_agree(VENT_STATE_OFF, LID_STATE_OPEN);
}

/* ── build_ws_ota_event_json ─────────────────────────────────────────────── */

static void test_ws_ota_events(void)
{
    cJSON *dl = build_ws_ota_event_json(OTA_PHASE_DOWNLOAD, 37, NULL);
    TEST_ASSERT_EQUAL_STRING("ota_progress", cJSON_GetObjectItem(dl, "type")->valuestring);
    cJSON *dl_data = cJSON_GetObjectItem(dl, "data");
    TEST_ASSERT_EQUAL_STRING("download", cJSON_GetObjectItem(dl_data, "phase")->valuestring);
    TEST_ASSERT_EQUAL_INT(37, cJSON_GetObjectItem(dl_data, "percent")->valueint);
    dump_fixture("ws_ota_progress", dl);
    cJSON_Delete(dl);

    cJSON *fl = build_ws_ota_event_json(OTA_PHASE_FLASH, 80, NULL);
    TEST_ASSERT_EQUAL_STRING("ota_progress", cJSON_GetObjectItem(fl, "type")->valuestring);
    TEST_ASSERT_EQUAL_STRING("flash", cJSON_GetObjectItem(cJSON_GetObjectItem(fl, "data"), "phase")->valuestring);
    cJSON_Delete(fl);

    /* percent is pinned at 100 on completion whatever the caller passes — the
       progress bar must land on full, not on the last download tick. */
    cJSON *done = build_ws_ota_event_json(OTA_PHASE_COMPLETE, 4, NULL);
    TEST_ASSERT_EQUAL_STRING("ota_complete", cJSON_GetObjectItem(done, "type")->valuestring);
    TEST_ASSERT_EQUAL_INT(100, cJSON_GetObjectItem(cJSON_GetObjectItem(done, "data"), "percent")->valueint);
    dump_fixture("ws_ota_complete", done);
    cJSON_Delete(done);

    cJSON *err = build_ws_ota_event_json(OTA_PHASE_ERROR, 0, "SHA256 mismatch");
    TEST_ASSERT_EQUAL_STRING("ota_error", cJSON_GetObjectItem(err, "type")->valuestring);
    TEST_ASSERT_EQUAL_STRING("SHA256 mismatch",
                             cJSON_GetObjectItem(cJSON_GetObjectItem(err, "data"), "message")->valuestring);
    dump_fixture("ws_ota_error", err);
    cJSON_Delete(err);
}

/* A NULL `err` still has to produce a message: the client renders that string,
   and an absent key leaves the update dialog reporting nothing at all. */
static void test_ws_ota_error_always_carries_a_message(void)
{
    cJSON *err = build_ws_ota_event_json(OTA_PHASE_ERROR, 0, NULL);
    cJSON *msg = cJSON_GetObjectItem(cJSON_GetObjectItem(err, "data"), "message");
    TEST_ASSERT_NOT_NULL(msg);
    TEST_ASSERT_TRUE(cJSON_IsString(msg) && msg->valuestring[0] != '\0');
    cJSON_Delete(err);
}

/* OTA_PHASE_IDLE has no frame. NULL (rather than an empty envelope) is what
   tells ws_send_ota_event to send nothing, so a client is never handed a
   message with no `type` to switch on. */
static void test_ws_ota_idle_has_no_frame(void)
{
    TEST_ASSERT_NULL(build_ws_ota_event_json(OTA_PHASE_IDLE, 0, NULL));
    TEST_ASSERT_NULL(build_ws_ota_event_json((ota_phase_t)999, 0, NULL));
}

/* ── build_system_json ───────────────────────────────────────────────────── */

/* GET /system had a zod schema validated against the mock-server only; the
   firmware built the same JSON inline, so mock/firmware drift had nothing
   watching it (#174). */
static void test_system_shape(void)
{
    system_info_json_t info = {
        .firmware = "1.4.2",
        .model = "Bisque ESP32-S3",
        .uptime_seconds = 86412.5,
        .free_heap = 198432,
        .emergency_stop = false,
        .last_error_code = 0,
        .element_hours_s = 151200,
        .board_temp_c = 38.25f,
        .spiffs_total = 917504,
        .spiffs_used = 233472,
    };
    cJSON *root = build_system_json(&info);

    assert_string_field(root, "firmware");
    assert_string_field(root, "model");
    assert_number_field(root, "uptimeSeconds");
    assert_number_field(root, "freeHeap");
    assert_bool_field(root, "emergencyStop");
    assert_number_field(root, "lastErrorCode");
    assert_number_field(root, "elementHoursS");
    assert_number_field(root, "boardTempC");
    assert_number_field(root, "spiffsTotal");
    assert_number_field(root, "spiffsUsed");

    TEST_ASSERT_EQUAL_STRING("1.4.2", cJSON_GetObjectItem(root, "firmware")->valuestring);
    /* Fractional, and it must stay that way: uptime is esp_timer microseconds
       divided by 1e6, so truncating it here would hide a builder that rounded. */
    TEST_ASSERT_EQUAL_FLOAT(86412.5f, cJSON_GetObjectItem(root, "uptimeSeconds")->valuedouble);

    dump_fixture("system", root);
    cJSON_Delete(root);
}

/* The emergency-stop banner and the error badge are driven straight off these
   two, so the faulted state has to serialize as distinctly as the healthy one. */
static void test_system_emergency_state(void)
{
    system_info_json_t info = {
        .firmware = "1.4.2",
        .model = "Bisque ESP32-S3",
        .emergency_stop = true,
        .last_error_code = 7,
    };
    cJSON *root = build_system_json(&info);
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "emergencyStop")));
    TEST_ASSERT_EQUAL_INT(7, cJSON_GetObjectItem(root, "lastErrorCode")->valueint);
    dump_fixture("system_emergency", root);
    cJSON_Delete(root);
}

/* ── build_wifi_status_json ──────────────────────────────────────────────── */

static void test_wifi_connected_shape(void)
{
    cJSON *root = build_wifi_status_json(true, false, "192.168.1.42", "Studio");

    assert_bool_field(root, "connected");
    assert_bool_field(root, "apMode");
    assert_string_field(root, "ip");
    assert_bool_field(root, "hasSavedCredentials");
    assert_string_field(root, "savedSsid");

    TEST_ASSERT_EQUAL_STRING("192.168.1.42", cJSON_GetObjectItem(root, "ip")->valuestring);
    TEST_ASSERT_EQUAL_STRING("Studio", cJSON_GetObjectItem(root, "savedSsid")->valuestring);
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "hasSavedCredentials")));

    dump_fixture("wifi", root);
    cJSON_Delete(root);
}

/* The provisioning state: no credentials stored, so the device is serving its
   own AP. `savedSsid` is absent rather than empty — the setup form keys off the
   key's presence, and an empty string would read as "a network named ''". */
static void test_wifi_ap_mode_omits_saved_ssid(void)
{
    cJSON *root = build_wifi_status_json(false, true, "192.168.4.1", NULL);
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(root, "hasSavedCredentials")));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "savedSsid"));
    dump_fixture("wifi_ap_mode", root);
    cJSON_Delete(root);

    /* An empty SSID is the same case: wifi_manager_load_creds can succeed with
       a blank slot, and that is not a saved network. */
    cJSON *blank = build_wifi_status_json(false, true, "192.168.4.1", "");
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(blank, "hasSavedCredentials")));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(blank, "savedSsid"));
    cJSON_Delete(blank);
}

/* Whatever else changes here, the passphrase must never reach the wire. */
static void test_wifi_never_exposes_password(void)
{
    cJSON *root = build_wifi_status_json(true, false, "192.168.1.42", "Studio");
    char *json = cJSON_PrintUnformatted(root);
    TEST_ASSERT_NULL(strstr(json, "password"));
    TEST_ASSERT_NULL(strstr(json, "passphrase"));
    free(json);
    cJSON_Delete(root);
}

/* ── build_ota_check_json ────────────────────────────────────────────────── */

static void test_ota_check_shape(void)
{
    ota_manifest_t manifest = {.size = 1449984};
    strcpy(manifest.version, "1.5.0");
    strcpy(manifest.url, "https://github.com/BenSeverson/bisque/releases/download/v1.5.0/bisque.bin");
    strcpy(manifest.sha256, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    strcpy(manifest.notes, "Faster autotune convergence");

    cJSON *root = build_ota_check_json("1.4.2", &manifest);

    assert_string_field(root, "current");
    assert_string_field(root, "latest");
    assert_bool_field(root, "updateAvailable");
    assert_string_field(root, "url");
    assert_string_field(root, "sha256");
    assert_number_field(root, "size");
    assert_string_field(root, "notes");

    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "updateAvailable")));
    TEST_ASSERT_EQUAL_STRING("1.5.0", cJSON_GetObjectItem(root, "latest")->valuestring);

    dump_fixture("ota_check", root);
    cJSON_Delete(root);
}

/* An identical version is "no update", not "update to yourself" — the install
   button is drawn straight off this flag. */
static void test_ota_check_up_to_date(void)
{
    ota_manifest_t manifest = {0};
    strcpy(manifest.version, "1.4.2");
    cJSON *root = build_ota_check_json("1.4.2", &manifest);
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(root, "updateAvailable")));
    dump_fixture("ota_check_current", root);
    cJSON_Delete(root);
}

/* ── build_ota_status_json ───────────────────────────────────────────────── */

static void test_ota_status_shape(void)
{
    ota_status_json_t info = {
        .running_label = "ota_0",
        .running_address = 0x110000,
        .running_size = 0x300000,
        .running_state = "pending_verify",
        .pending_verify = true,
        .running_version = "1.5.0",
        .running_date = "Jul 22 2026",
        .running_time = "19:59:07",
        .running_idf_version = "v6.0",
        .next_label = "ota_1",
        .next_size = 0x300000,
        .boot_partition = "ota_0",
        .rollback_available = true,
    };
    cJSON *root = build_ota_status_json(&info);

    cJSON *run = cJSON_GetObjectItem(root, "running");
    TEST_ASSERT_NOT_NULL(run);
    assert_string_field(run, "label");
    assert_number_field(run, "address");
    assert_number_field(run, "size");
    assert_string_field(run, "state");
    assert_string_field(run, "version");
    assert_string_field(run, "date");
    assert_string_field(run, "time");
    assert_string_field(run, "idfVersion");

    cJSON *next = cJSON_GetObjectItem(root, "nextUpdate");
    TEST_ASSERT_NOT_NULL(next);
    assert_string_field(next, "label");
    assert_number_field(next, "size");

    assert_string_field(root, "bootPartition");
    assert_bool_field(root, "pendingVerify");
    assert_bool_field(root, "rollbackAvailable");

    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(root, "pendingVerify")));

    dump_fixture("ota_status", root);
    cJSON_Delete(root);
}

/* Every esp_ota lookup the handler makes can fail independently, and each
   failure drops its key rather than emitting a placeholder. `rollbackAvailable`
   is the one field always present, so a client can rely on that alone. */
static void test_ota_status_omits_unavailable_parts(void)
{
    ota_status_json_t info = {.rollback_available = false};
    cJSON *root = build_ota_status_json(&info);

    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "running"));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "nextUpdate"));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "bootPartition"));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(root, "pendingVerify"));
    assert_bool_field(root, "rollbackAvailable");

    dump_fixture("ota_status_minimal", root);
    cJSON_Delete(root);

    /* A readable partition whose state could not be queried keeps `running` but
       drops both `state` and the pendingVerify flag it gates. */
    ota_status_json_t partial = {.running_label = "factory", .running_size = 0x300000};
    cJSON *p = build_ota_status_json(&partial);
    TEST_ASSERT_NOT_NULL(cJSON_GetObjectItem(p, "running"));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(cJSON_GetObjectItem(p, "running"), "state"));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(cJSON_GetObjectItem(p, "running"), "version"));
    TEST_ASSERT_NULL(cJSON_GetObjectItem(p, "pendingVerify"));
    cJSON_Delete(p);
}

/* ── firing_status_to_string ─────────────────────────────────────────────── */

static void test_firing_status_strings(void)
{
    TEST_ASSERT_EQUAL_STRING("idle", firing_status_to_string(FIRING_STATUS_IDLE));
    TEST_ASSERT_EQUAL_STRING("heating", firing_status_to_string(FIRING_STATUS_HEATING));
    TEST_ASSERT_EQUAL_STRING("holding", firing_status_to_string(FIRING_STATUS_HOLDING));
    TEST_ASSERT_EQUAL_STRING("cooling", firing_status_to_string(FIRING_STATUS_COOLING));
    TEST_ASSERT_EQUAL_STRING("complete", firing_status_to_string(FIRING_STATUS_COMPLETE));
    TEST_ASSERT_EQUAL_STRING("error", firing_status_to_string(FIRING_STATUS_ERROR));
    TEST_ASSERT_EQUAL_STRING("paused", firing_status_to_string(FIRING_STATUS_PAUSED));
    TEST_ASSERT_EQUAL_STRING("autotune", firing_status_to_string(FIRING_STATUS_AUTOTUNE));
    TEST_ASSERT_EQUAL_STRING("unknown", firing_status_to_string((firing_status_t)999));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_status_full_shape);
    RUN_TEST(test_status_zeros_temp_when_fault);
    RUN_TEST(test_status_clamps_duty);
    RUN_TEST(test_status_omits_vent_when_not_fitted);
    RUN_TEST(test_status_omits_lid_when_not_fitted);
    RUN_TEST(test_status_reports_an_open_lid);
    RUN_TEST(test_status_reports_a_closed_lid);
    RUN_TEST(test_settings_always_carry_the_lid_mode);
    RUN_TEST(test_lid_mode_string_round_trip);
    RUN_TEST(test_profile_shape);
    RUN_TEST(test_profile_hold_until_skip);
    RUN_TEST(test_history_empty_list);
    RUN_TEST(test_settings_shape_redacts_token);
    RUN_TEST(test_settings_apiTokenSet_false_when_empty);
    RUN_TEST(test_history_record_shape);
    RUN_TEST(test_history_outcome_strings);
    RUN_TEST(test_cone_table_shape);
    RUN_TEST(test_cone_fire_profiles);
    RUN_TEST(test_autotune_status_idle);
    RUN_TEST(test_autotune_status_running_vs_stopped);
    RUN_TEST(test_autotune_terminal_states_are_distinct);
    RUN_TEST(test_autotune_running_outranks_terminal_state);
    RUN_TEST(test_pid_shape);
    RUN_TEST(test_thermocouple_diag_shape);
    RUN_TEST(test_ws_temp_update_shape);
    RUN_TEST(test_ws_temp_update_matches_status_progress_block);
    RUN_TEST(test_ws_ota_events);
    RUN_TEST(test_ws_ota_error_always_carries_a_message);
    RUN_TEST(test_ws_ota_idle_has_no_frame);
    RUN_TEST(test_system_shape);
    RUN_TEST(test_system_emergency_state);
    RUN_TEST(test_wifi_connected_shape);
    RUN_TEST(test_wifi_ap_mode_omits_saved_ssid);
    RUN_TEST(test_wifi_never_exposes_password);
    RUN_TEST(test_ota_check_shape);
    RUN_TEST(test_ota_check_up_to_date);
    RUN_TEST(test_ota_status_shape);
    RUN_TEST(test_ota_status_omits_unavailable_parts);
    RUN_TEST(test_firing_status_strings);
    return UNITY_END();
}
