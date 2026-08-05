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
#include <math.h>
#include <stdbool.h>
#include <string.h>

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

/* Internal helper: add the shared firing-progress fields. Both the REST status
 * response and the WebSocket temp_update frame are built from it, which is what
 * lets a client run the two through one parser. */
static void json_add_progress_fields(cJSON *target, const firing_progress_t *prog, float current_temp, float ssr_duty,
                                     vent_state_t vent)
{
    cJSON_AddBoolToObject(target, "isActive", prog->is_active);
    cJSON_AddStringToObject(target, "profileId", prog->profile_id);
    cJSON_AddNumberToObject(target, "currentTemp", current_temp);
    cJSON_AddNumberToObject(target, "targetTemp", prog->target_temp);
    cJSON_AddNumberToObject(target, "currentSegment", prog->current_segment);
    cJSON_AddNumberToObject(target, "totalSegments", prog->total_segments);
    cJSON_AddNumberToObject(target, "elapsedTime", prog->elapsed_time);
    cJSON_AddNumberToObject(target, "estimatedTimeRemaining", prog->estimated_remaining);
    /* Seconds until an armed delayed start fires, 0 when none is armed. The UI
       could previously show that a firing was *scheduled* but not when it would
       begin, which is the thing worth confirming before leaving a kiln to run
       overnight (#204). */
    cJSON_AddNumberToObject(target, "delayRemaining", prog->delay_remaining);
    /* Element power: the SSR duty the safety layer is actually driving, as a
       whole percent. "Element power: 62%" is what makes a firing legible —
       whether the kiln is maxed out or merely cycling, whether autotune is
       still bang-banging, and (over months, at the same ramp) whether the
       elements are ageing (#180). Whole percent: the output is a 2 s window
       stepped every 100 ms (APP_SSR_WINDOW_MS / SSR_APPLY_PERIOD_US), so the
       element itself only resolves ~5% steps — decimals would be invented
       precision. */
    float duty = ssr_duty;
    if (!(duty > 0.0f)) { /* also catches NaN */
        duty = 0.0f;
    } else if (duty > 1.0f) {
        duty = 1.0f;
    }
    cJSON_AddNumberToObject(target, "dutyPercent", (double)lroundf(duty * 100.0f));
    /* Downdraft vent relay (#184). The key is omitted entirely — rather than
       sent false — on a kiln with no vent GPIO configured, which is the default
       (CONFIG_KILN_PIN_VENT = -1). "Vent: off" and "this kiln has no vent" are
       different facts, and only the firmware knows which one applies; a client
       that saw `false` either way would have to render a dead indicator on
       every kiln that never had the hardware. */
    if (vent != VENT_STATE_NOT_FITTED) {
        cJSON_AddBoolToObject(target, "ventActive", vent == VENT_STATE_ON);
    }
    cJSON_AddStringToObject(target, "status", firing_status_to_string(prog->status));
}

cJSON *build_status_json(const firing_progress_t *prog, const thermocouple_reading_t *tc, float tc_offset_c,
                         float ssr_duty, vent_state_t vent)
{
    cJSON *root = cJSON_CreateObject();
    /* Offset-correct the published temperature (and zero it on fault) so the
       REST status matches the WebSocket temp_update feed. */
    float current_temp = tc->fault ? 0.0f : (tc->temperature_c + tc_offset_c);
    json_add_progress_fields(root, prog, current_temp, ssr_duty, vent);

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

/* Terminal auto-tune outcomes were flattened onto a bare "idle", so a client
 * could not tell "your tuning run finished and gains were saved" from "nothing
 * is running" — the two frames were byte-identical. That ambiguity is what
 * forced the web client into a pending phase plus a grace window that could
 * only ever conclude "unconfirmed" (#216).
 *
 * `running` still comes from the progress status, since that is what the engine
 * updates live. Once the run ends the engine calls do_stop() and the status
 * returns to IDLE, so the *outcome* has to come from the autotune state, which
 * survives until the next start or cancel. */
static const char *autotune_state_to_string(firing_status_t status, autotune_state_t at_state)
{
    if (status == FIRING_STATUS_AUTOTUNE) {
        return "running";
    }
    switch (at_state) {
    case AUTOTUNE_COMPLETE:
        return "complete";
    case AUTOTUNE_FAILED:
        return "failed";
    case AUTOTUNE_IDLE:
        return status == FIRING_STATUS_IDLE ? "idle" : "stopped";
    default:
        /* Mid-run states (heating to setpoint, relay cycling) with the progress
           status already away from AUTOTUNE — a firing took over, or the run was
           stopped between ticks. Neither finished nor running. */
        return "stopped";
    }
}

cJSON *build_autotune_status_json(const firing_progress_t *prog, autotune_state_t at_state, float kp, float ki,
                                  float kd)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "state", autotune_state_to_string(prog->status, at_state));
    cJSON_AddNumberToObject(root, "elapsedTime", prog->elapsed_time);
    cJSON_AddNumberToObject(root, "targetTemp", prog->target_temp);
    cJSON_AddNumberToObject(root, "currentTemp", prog->current_temp);

    cJSON *gains = cJSON_AddObjectToObject(root, "currentGains");
    cJSON_AddNumberToObject(gains, "kp", kp);
    cJSON_AddNumberToObject(gains, "ki", ki);
    cJSON_AddNumberToObject(gains, "kd", kd);
    return root;
}

cJSON *build_pid_json(float kp, float ki, float kd)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "kp", kp);
    cJSON_AddNumberToObject(root, "ki", ki);
    cJSON_AddNumberToObject(root, "kd", kd);

    float def_kp, def_ki, def_kd;
    pid_default_gains(&def_kp, &def_ki, &def_kd);
    cJSON *defaults = cJSON_AddObjectToObject(root, "defaults");
    cJSON_AddNumberToObject(defaults, "kp", def_kp);
    cJSON_AddNumberToObject(defaults, "ki", def_ki);
    cJSON_AddNumberToObject(defaults, "kd", def_kd);

    /* Served rather than mirrored as constants on the client, because a client
       that hardcodes the bounds drifts from the firmware silently: the form goes
       on accepting a value POST /pid then rejects with a bare 400. */
    cJSON *limits = cJSON_AddObjectToObject(root, "limits");
    cJSON_AddNumberToObject(limits, "min", PID_GAIN_MIN);
    cJSON_AddNumberToObject(limits, "max", PID_GAIN_MAX);
    return root;
}

/* ── WebSocket frames ───────────────────────────────────────────────────── */

/* Every frame on the socket is {"type":…,"data":{…}}. Building the envelope in
 * one place keeps a new event from inventing a second shape. */
static cJSON *ws_envelope(const char *type, cJSON **out_data)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", type);
    *out_data = cJSON_AddObjectToObject(root, "data");
    return root;
}

cJSON *build_ws_temp_update_json(const firing_progress_t *prog, float current_temp, float ssr_duty, vent_state_t vent)
{
    cJSON *data;
    cJSON *root = ws_envelope("temp_update", &data);
    json_add_progress_fields(data, prog, current_temp, ssr_duty, vent);
    return root;
}

cJSON *build_ws_ota_event_json(ota_phase_t phase, int percent, const char *err)
{
    cJSON *data;
    cJSON *root;

    switch (phase) {
    case OTA_PHASE_DOWNLOAD:
    case OTA_PHASE_FLASH:
        root = ws_envelope("ota_progress", &data);
        cJSON_AddStringToObject(data, "phase", phase == OTA_PHASE_FLASH ? "flash" : "download");
        cJSON_AddNumberToObject(data, "percent", percent);
        return root;
    case OTA_PHASE_COMPLETE:
        root = ws_envelope("ota_complete", &data);
        cJSON_AddNumberToObject(data, "percent", 100);
        return root;
    case OTA_PHASE_ERROR:
        root = ws_envelope("ota_error", &data);
        /* Never an absent message: the client renders this string, and a
           missing key would leave the update dialog reporting nothing. */
        cJSON_AddStringToObject(data, "message", err ? err : "Update failed");
        return root;
    default:
        return NULL;
    }
}

/* ── Device/system endpoints ────────────────────────────────────────────── */

cJSON *build_system_json(const system_info_json_t *info)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "firmware", info->firmware);
    cJSON_AddStringToObject(root, "model", info->model);
    cJSON_AddNumberToObject(root, "uptimeSeconds", info->uptime_seconds);
    cJSON_AddNumberToObject(root, "freeHeap", (double)info->free_heap);
    cJSON_AddBoolToObject(root, "emergencyStop", info->emergency_stop);
    cJSON_AddNumberToObject(root, "lastErrorCode", (double)info->last_error_code);
    cJSON_AddNumberToObject(root, "elementHoursS", (double)info->element_hours_s);
    cJSON_AddNumberToObject(root, "boardTempC", (double)info->board_temp_c);
    cJSON_AddNumberToObject(root, "spiffsTotal", (double)info->spiffs_total);
    cJSON_AddNumberToObject(root, "spiffsUsed", (double)info->spiffs_used);
    return root;
}

cJSON *build_wifi_status_json(bool connected, bool ap_mode, const char *ip, const char *saved_ssid)
{
    bool has_saved = saved_ssid && saved_ssid[0];

    cJSON *root = cJSON_CreateObject();
    cJSON_AddBoolToObject(root, "connected", connected);
    cJSON_AddBoolToObject(root, "apMode", ap_mode);
    cJSON_AddStringToObject(root, "ip", ip ? ip : "");
    cJSON_AddBoolToObject(root, "hasSavedCredentials", has_saved);
    if (has_saved) {
        cJSON_AddStringToObject(root, "savedSsid", saved_ssid);
    }
    return root;
}

cJSON *build_ota_check_json(const char *current_version, const ota_manifest_t *manifest)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "current", current_version);
    cJSON_AddStringToObject(root, "latest", manifest->version);
    cJSON_AddBoolToObject(root, "updateAvailable", strcmp(current_version, manifest->version) != 0);
    cJSON_AddStringToObject(root, "url", manifest->url);
    cJSON_AddStringToObject(root, "sha256", manifest->sha256);
    cJSON_AddNumberToObject(root, "size", manifest->size);
    cJSON_AddStringToObject(root, "notes", manifest->notes);
    return root;
}

cJSON *build_ota_status_json(const ota_status_json_t *info)
{
    cJSON *root = cJSON_CreateObject();

    if (info->running_label) {
        cJSON *run = cJSON_AddObjectToObject(root, "running");
        cJSON_AddStringToObject(run, "label", info->running_label);
        cJSON_AddNumberToObject(run, "address", (double)info->running_address);
        cJSON_AddNumberToObject(run, "size", (double)info->running_size);

        if (info->running_state) {
            cJSON_AddStringToObject(run, "state", info->running_state);
            /* Sits on the root, not inside `running` — it is what the client
               polls to decide whether to offer "confirm this update". */
            cJSON_AddBoolToObject(root, "pendingVerify", info->pending_verify);
        }
        if (info->running_version) {
            cJSON_AddStringToObject(run, "version", info->running_version);
            cJSON_AddStringToObject(run, "date", info->running_date ? info->running_date : "");
            cJSON_AddStringToObject(run, "time", info->running_time ? info->running_time : "");
            cJSON_AddStringToObject(run, "idfVersion", info->running_idf_version ? info->running_idf_version : "");
        }
    }

    if (info->next_label) {
        cJSON *nxt = cJSON_AddObjectToObject(root, "nextUpdate");
        cJSON_AddStringToObject(nxt, "label", info->next_label);
        cJSON_AddNumberToObject(nxt, "size", (double)info->next_size);
    }

    if (info->boot_partition) {
        cJSON_AddStringToObject(root, "bootPartition", info->boot_partition);
    }

    cJSON_AddBoolToObject(root, "rollbackAvailable", info->rollback_available);
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
