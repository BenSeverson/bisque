/**
 * Pure JSON builders for the REST API. See api_json.h for the contract.
 *
 * Nothing in here calls esp_http_server, esp_timer, or any global state — every
 * function takes its inputs explicitly, which is what makes the host contract
 * tests in tests/host/test_api_json.c possible.
 */
#include "api_json.h"
#include "thermocouple.h"
#include "cone_table.h"
#include <stdbool.h>

const char *firing_status_to_string(firing_status_t s)
{
    switch (s) {
    case FIRING_STATUS_IDLE:
        return "idle";
    case FIRING_STATUS_HEATING:
        return "heating";
    case FIRING_STATUS_HOLDING:
        return "holding";
    case FIRING_STATUS_COOLING:
        return "cooling";
    case FIRING_STATUS_COMPLETE:
        return "complete";
    case FIRING_STATUS_ERROR:
        return "error";
    case FIRING_STATUS_PAUSED:
        return "paused";
    case FIRING_STATUS_AUTOTUNE:
        return "autotune";
    default:
        return "unknown";
    }
}

/* Internal helper: add the shared firing-progress fields. The WS broadcast path
 * also uses these via json_add_progress_fields() in api_handlers.c — that
 * declaration stays in web_server.h, but the body now lives here so the host
 * tests cover it. */
void json_add_progress_fields(cJSON *target, const firing_progress_t *prog, float current_temp)
{
    cJSON_AddBoolToObject(target, "isActive", prog->is_active);
    cJSON_AddStringToObject(target, "profileId", prog->profile_id);
    cJSON_AddNumberToObject(target, "currentTemp", current_temp);
    cJSON_AddNumberToObject(target, "targetTemp", prog->target_temp);
    cJSON_AddNumberToObject(target, "currentSegment", prog->current_segment);
    cJSON_AddNumberToObject(target, "totalSegments", prog->total_segments);
    cJSON_AddNumberToObject(target, "elapsedTime", prog->elapsed_time);
    cJSON_AddNumberToObject(target, "estimatedTimeRemaining", prog->estimated_remaining);
    cJSON_AddStringToObject(target, "status", firing_status_to_string(prog->status));
}

cJSON *build_status_json(const firing_progress_t *prog, const thermocouple_reading_t *tc)
{
    cJSON *root = cJSON_CreateObject();
    json_add_progress_fields(root, prog, tc->fault ? 0.0f : tc->temperature_c);

    cJSON *tc_obj = cJSON_AddObjectToObject(root, "thermocouple");
    cJSON_AddNumberToObject(tc_obj, "temperature", tc->temperature_c);
    cJSON_AddNumberToObject(tc_obj, "internalTemp", tc->internal_temp_c);
    cJSON_AddBoolToObject(tc_obj, "fault", tc->fault != 0);
    cJSON_AddBoolToObject(tc_obj, "openCircuit", (tc->fault & TC_FAULT_OPEN_CIRCUIT) != 0);
    cJSON_AddBoolToObject(tc_obj, "shortGnd", (tc->fault & TC_FAULT_SHORT_GND) != 0);
    cJSON_AddBoolToObject(tc_obj, "shortVcc", (tc->fault & TC_FAULT_SHORT_VCC) != 0);
    return root;
}

cJSON *build_profile_json(const firing_profile_t *profile)
{
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "id", profile->id);
    cJSON_AddStringToObject(p, "name", profile->name);
    cJSON_AddStringToObject(p, "description", profile->description);
    cJSON_AddNumberToObject(p, "maxTemp", profile->max_temp);
    cJSON_AddNumberToObject(p, "estimatedDuration", profile->estimated_duration);

    cJSON *segs = cJSON_AddArrayToObject(p, "segments");
    for (int i = 0; i < profile->segment_count; i++) {
        cJSON *s = cJSON_CreateObject();
        cJSON_AddStringToObject(s, "id", profile->segments[i].id);
        cJSON_AddStringToObject(s, "name", profile->segments[i].name);
        cJSON_AddNumberToObject(s, "rampRate", profile->segments[i].ramp_rate);
        cJSON_AddNumberToObject(s, "targetTemp", profile->segments[i].target_temp);
        cJSON_AddNumberToObject(s, "holdTime", profile->segments[i].hold_time);
        cJSON_AddItemToArray(segs, s);
    }
    return p;
}

cJSON *build_settings_json(const kiln_settings_t *settings)
{
    cJSON *root = cJSON_CreateObject();
    char unit_str[2] = {settings->temp_unit, '\0'};
    cJSON_AddStringToObject(root, "tempUnit", unit_str);
    cJSON_AddNumberToObject(root, "maxSafeTemp", settings->max_safe_temp);
    cJSON_AddBoolToObject(root, "alarmEnabled", settings->alarm_enabled);
    cJSON_AddBoolToObject(root, "autoShutdown", settings->auto_shutdown);
    cJSON_AddBoolToObject(root, "notificationsEnabled", settings->notifications_enabled);
    cJSON_AddNumberToObject(root, "tcOffsetC", settings->tc_offset_c);
    cJSON_AddStringToObject(root, "webhookUrl", settings->webhook_url);
    /* Don't expose the API token value, just whether it's set */
    cJSON_AddBoolToObject(root, "apiTokenSet", settings->api_token[0] != '\0');
    cJSON_AddNumberToObject(root, "elementWatts", settings->element_watts);
    cJSON_AddNumberToObject(root, "electricityCostKwh", settings->electricity_cost_kwh);
    return root;
}

cJSON *build_history_record_json(const history_record_t *rec)
{
    cJSON *item = cJSON_CreateObject();
    cJSON_AddNumberToObject(item, "id", rec->id);
    cJSON_AddNumberToObject(item, "startTime", (double)rec->start_time);
    cJSON_AddStringToObject(item, "profileName", rec->profile_name);
    cJSON_AddStringToObject(item, "profileId", rec->profile_id);
    cJSON_AddNumberToObject(item, "peakTemp", rec->peak_temp_c);
    cJSON_AddNumberToObject(item, "durationS", rec->duration_s);
    cJSON_AddStringToObject(item, "outcome", history_outcome_to_string(rec->outcome));
    cJSON_AddNumberToObject(item, "errorCode", rec->error_code);
    return item;
}

cJSON *build_cone_table_json(void)
{
    cJSON *arr = cJSON_CreateArray();
    for (int i = 0; i < CONE_COUNT; i++) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "id", i);
        cJSON_AddStringToObject(item, "name", cone_name((cone_id_t)i));
        cJSON_AddNumberToObject(item, "slowTempC", cone_target_temp_c((cone_id_t)i, CONE_SPEED_SLOW));
        cJSON_AddNumberToObject(item, "mediumTempC", cone_target_temp_c((cone_id_t)i, CONE_SPEED_MEDIUM));
        cJSON_AddNumberToObject(item, "fastTempC", cone_target_temp_c((cone_id_t)i, CONE_SPEED_FAST));
        cJSON_AddItemToArray(arr, item);
    }
    return arr;
}

cJSON *build_autotune_status_json(const firing_progress_t *prog, float kp, float ki, float kd)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "state",
                            prog->status == FIRING_STATUS_AUTOTUNE ? "running"
                            : prog->status == FIRING_STATUS_IDLE   ? "idle"
                                                                   : "stopped");
    cJSON_AddNumberToObject(root, "elapsedTime", prog->elapsed_time);
    cJSON_AddNumberToObject(root, "targetTemp", prog->target_temp);
    cJSON_AddNumberToObject(root, "currentTemp", prog->current_temp);

    cJSON *gains = cJSON_AddObjectToObject(root, "currentGains");
    cJSON_AddNumberToObject(gains, "kp", kp);
    cJSON_AddNumberToObject(gains, "ki", ki);
    cJSON_AddNumberToObject(gains, "kd", kd);
    return root;
}

cJSON *build_thermocouple_diag_json(const thermocouple_reading_t *tc, int64_t age_ms, float tc_offset_c)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "temperatureC", tc->temperature_c);
    cJSON_AddNumberToObject(root, "internalTempC", tc->internal_temp_c);
    cJSON_AddBoolToObject(root, "fault", tc->fault != 0);
    cJSON_AddBoolToObject(root, "openCircuit", (tc->fault & TC_FAULT_OPEN_CIRCUIT) != 0);
    cJSON_AddBoolToObject(root, "shortGnd", (tc->fault & TC_FAULT_SHORT_GND) != 0);
    cJSON_AddBoolToObject(root, "shortVcc", (tc->fault & TC_FAULT_SHORT_VCC) != 0);
    cJSON_AddNumberToObject(root, "readingAgeMs", (double)age_ms);
    cJSON_AddNumberToObject(root, "temperatureAdjustedC", tc->temperature_c + tc_offset_c);
    cJSON_AddNumberToObject(root, "tcOffsetC", tc_offset_c);
    return root;
}
