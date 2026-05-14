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
#include "firing_history.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "unity.h"

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

    cJSON *root = build_status_json(&prog, &tc);
    TEST_ASSERT_NOT_NULL(root);

    assert_bool_field(root, "isActive");
    assert_string_field(root, "profileId");
    assert_number_field(root, "currentTemp");
    assert_number_field(root, "targetTemp");
    assert_number_field(root, "currentSegment");
    assert_number_field(root, "totalSegments");
    assert_number_field(root, "elapsedTime");
    assert_number_field(root, "estimatedTimeRemaining");
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
    cJSON *root = build_status_json(&prog, &tc);

    /* Top-level currentTemp is zero-clamped on fault (UI shouldn't render the
     * stale last-read temp). Inner thermocouple.temperature still exposes the
     * raw value for diagnostics. */
    TEST_ASSERT_EQUAL_FLOAT(0.0f, cJSON_GetObjectItem(root, "currentTemp")->valuedouble);
    TEST_ASSERT_EQUAL_FLOAT(999.0f,
                            cJSON_GetObjectItem(cJSON_GetObjectItem(root, "thermocouple"), "temperature")->valuedouble);
    TEST_ASSERT_TRUE(cJSON_IsTrue(cJSON_GetObjectItem(cJSON_GetObjectItem(root, "thermocouple"), "openCircuit")));
    TEST_ASSERT_FALSE(cJSON_IsTrue(cJSON_GetObjectItem(cJSON_GetObjectItem(root, "thermocouple"), "shortGnd")));
    cJSON_Delete(root);
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

/* ── build_autotune_status_json ──────────────────────────────────────────── */

static void test_autotune_status_idle(void)
{
    firing_progress_t prog = {.status = FIRING_STATUS_IDLE, .current_temp = 24.0f};
    cJSON *root = build_autotune_status_json(&prog, 2.5f, 0.5f, 1.0f);

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
    cJSON *root = build_autotune_status_json(&prog, 1, 1, 1);
    TEST_ASSERT_EQUAL_STRING("running", cJSON_GetObjectItem(root, "state")->valuestring);
    cJSON_Delete(root);

    prog.status = FIRING_STATUS_HEATING;
    root = build_autotune_status_json(&prog, 1, 1, 1);
    TEST_ASSERT_EQUAL_STRING("stopped", cJSON_GetObjectItem(root, "state")->valuestring);
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
    RUN_TEST(test_profile_shape);
    RUN_TEST(test_settings_shape_redacts_token);
    RUN_TEST(test_settings_apiTokenSet_false_when_empty);
    RUN_TEST(test_history_record_shape);
    RUN_TEST(test_history_outcome_strings);
    RUN_TEST(test_cone_table_shape);
    RUN_TEST(test_autotune_status_idle);
    RUN_TEST(test_autotune_status_running_vs_stopped);
    RUN_TEST(test_thermocouple_diag_shape);
    RUN_TEST(test_firing_status_strings);
    return UNITY_END();
}
