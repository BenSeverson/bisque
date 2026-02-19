#include "web_server.h"
#include "firing_engine.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "pid_control.h"
#include "safety.h"
#include "cone_table.h"
#include "firing_history.h"
#include "app_config.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_spiffs.h"
#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_system.h"
#include <inttypes.h>
#include "cJSON.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "api";

/* ── Auth helpers ──────────────────────────────────── */

/**
 * Check Bearer token auth. Returns true if request is authorized.
 * If token is empty in settings, all requests are authorized.
 */
static bool check_auth(httpd_req_t *req)
{
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    /* No token configured → open access */
    if (settings.api_token[0] == '\0') return true;

    /* Check Authorization: Bearer <token> */
    char auth_hdr[96] = {0};
    if (httpd_req_get_hdr_value_str(req, "Authorization", auth_hdr, sizeof(auth_hdr)) == ESP_OK) {
        const char *prefix = "Bearer ";
        size_t prefix_len = strlen(prefix);
        if (strncmp(auth_hdr, prefix, prefix_len) == 0) {
            if (strcmp(auth_hdr + prefix_len, settings.api_token) == 0) return true;
        }
    }

    /* Check ?token= query parameter */
    char token_param[80] = {0};
    if (httpd_req_get_url_query_str(req, token_param, sizeof(token_param)) == ESP_OK) {
        char val[80] = {0};
        if (httpd_query_key_value(token_param, "token", val, sizeof(val)) == ESP_OK) {
            if (strcmp(val, settings.api_token) == 0) return true;
        }
    }

    return false;
}

static bool require_auth(httpd_req_t *req)
{
    if (!check_auth(req)) {
        httpd_resp_set_hdr(req, "WWW-Authenticate", "Bearer realm=\"bisque\"");
        httpd_resp_send_err(req, HTTPD_401_UNAUTHORIZED, "Unauthorized");
        return false;
    }
    return true;
}

/* ── Webhook notification ──────────────────────────── */

void send_webhook_event(const char *event, const char *profile_name, float peak_temp, uint32_t duration_s)
{
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);
    if (!settings.notifications_enabled || settings.webhook_url[0] == '\0') return;

    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "event", event);
    cJSON_AddStringToObject(body, "profileName", profile_name ? profile_name : "");
    cJSON_AddNumberToObject(body, "peakTemp", peak_temp);
    cJSON_AddNumberToObject(body, "durationS", duration_s);
    char *json = cJSON_PrintUnformatted(body);
    cJSON_Delete(body);
    if (!json) return;

    esp_http_client_config_t config = {
        .url = settings.webhook_url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 5000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client) {
        esp_http_client_set_header(client, "Content-Type", "application/json");
        esp_http_client_set_post_field(client, json, strlen(json));
        esp_err_t err = esp_http_client_perform(client);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "Webhook POST failed: %s", esp_err_to_name(err));
        } else {
            ESP_LOGI(TAG, "Webhook sent: %s", event);
        }
        esp_http_client_cleanup(client);
    }
    free(json);
}

/* Helper: read POST body into buffer. Returns length or -1 on error. */
static int read_body(httpd_req_t *req, char *buf, size_t buf_size)
{
    int remaining = req->content_len;
    if (remaining <= 0 || (size_t)remaining >= buf_size) {
        return -1;
    }
    int received = httpd_req_recv(req, buf, remaining);
    if (received <= 0) return -1;
    buf[received] = '\0';
    return received;
}

/* Helper: send JSON response */
static esp_err_t send_json(httpd_req_t *req, cJSON *root)
{
    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "JSON error");
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "application/json");
    httpd_resp_sendstr(req, json);
    free(json);
    return ESP_OK;
}

static const char *status_to_string(firing_status_t s)
{
    switch (s) {
    case FIRING_STATUS_IDLE:     return "idle";
    case FIRING_STATUS_HEATING:  return "heating";
    case FIRING_STATUS_HOLDING:  return "holding";
    case FIRING_STATUS_COOLING:  return "cooling";
    case FIRING_STATUS_COMPLETE: return "complete";
    case FIRING_STATUS_ERROR:    return "error";
    case FIRING_STATUS_PAUSED:   return "paused";
    case FIRING_STATUS_AUTOTUNE: return "autotune";
    default: return "unknown";
    }
}

/* ── GET /api/v1/status ────────────────────────────── */

static esp_err_t handle_get_status(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    firing_progress_t prog;
    firing_engine_get_progress(&prog);

    thermocouple_reading_t tc;
    thermocouple_get_latest(&tc);

    cJSON *root = cJSON_CreateObject();
    cJSON_AddBoolToObject(root, "isActive", prog.is_active);
    cJSON_AddStringToObject(root, "profileId", prog.profile_id);
    cJSON_AddNumberToObject(root, "currentTemp", tc.fault ? 0 : tc.temperature_c);
    cJSON_AddNumberToObject(root, "targetTemp", prog.target_temp);
    cJSON_AddNumberToObject(root, "currentSegment", prog.current_segment);
    cJSON_AddNumberToObject(root, "totalSegments", prog.total_segments);
    cJSON_AddNumberToObject(root, "elapsedTime", prog.elapsed_time);
    cJSON_AddNumberToObject(root, "estimatedTimeRemaining", prog.estimated_remaining);
    cJSON_AddStringToObject(root, "status", status_to_string(prog.status));

    /* Thermocouple details */
    cJSON *tc_obj = cJSON_AddObjectToObject(root, "thermocouple");
    cJSON_AddNumberToObject(tc_obj, "temperature", tc.temperature_c);
    cJSON_AddNumberToObject(tc_obj, "internalTemp", tc.internal_temp_c);
    cJSON_AddBoolToObject(tc_obj, "fault", tc.fault != 0);
    cJSON_AddBoolToObject(tc_obj, "openCircuit", (tc.fault & TC_FAULT_OPEN_CIRCUIT) != 0);
    cJSON_AddBoolToObject(tc_obj, "shortGnd", (tc.fault & TC_FAULT_SHORT_GND) != 0);
    cJSON_AddBoolToObject(tc_obj, "shortVcc", (tc.fault & TC_FAULT_SHORT_VCC) != 0);

    return send_json(req, root);
}

/* ── GET /api/v1/profiles ──────────────────────────── */

static esp_err_t handle_get_profiles(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    int count = firing_engine_list_profiles(ids, FIRING_MAX_PROFILES);

    cJSON *arr = cJSON_CreateArray();
    for (int i = 0; i < count; i++) {
        firing_profile_t profile;
        if (firing_engine_load_profile(ids[i], &profile) == ESP_OK) {
            cJSON *p = cJSON_CreateObject();
            cJSON_AddStringToObject(p, "id", profile.id);
            cJSON_AddStringToObject(p, "name", profile.name);
            cJSON_AddStringToObject(p, "description", profile.description);
            cJSON_AddNumberToObject(p, "maxTemp", profile.max_temp);
            cJSON_AddNumberToObject(p, "estimatedDuration", profile.estimated_duration);

            cJSON *segs = cJSON_AddArrayToObject(p, "segments");
            for (int j = 0; j < profile.segment_count; j++) {
                cJSON *s = cJSON_CreateObject();
                cJSON_AddStringToObject(s, "id", profile.segments[j].id);
                cJSON_AddStringToObject(s, "name", profile.segments[j].name);
                cJSON_AddNumberToObject(s, "rampRate", profile.segments[j].ramp_rate);
                cJSON_AddNumberToObject(s, "targetTemp", profile.segments[j].target_temp);
                cJSON_AddNumberToObject(s, "holdTime", profile.segments[j].hold_time);
                cJSON_AddItemToArray(segs, s);
            }
            cJSON_AddItemToArray(arr, p);
        }
    }

    httpd_resp_set_type(req, "application/json");
    char *json = cJSON_PrintUnformatted(arr);
    cJSON_Delete(arr);
    httpd_resp_sendstr(req, json);
    free(json);
    return ESP_OK;
}

/* ── GET /api/v1/profiles/:id  (and /api/v1/profiles/:id/export) ─────── */

static esp_err_t handle_get_profile(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    /* Extract ID from URI: /api/v1/profiles/<id> or /api/v1/profiles/<id>/export */
    const char *uri = req->uri;
    const char *prefix = "/api/v1/profiles/";
    if (strncmp(uri, prefix, strlen(prefix)) != 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Bad request");
        return ESP_FAIL;
    }
    const char *id_start = uri + strlen(prefix);

    /* Detect /export suffix */
    bool is_export = false;
    char id_buf[FIRING_ID_LEN];
    strncpy(id_buf, id_start, sizeof(id_buf) - 1);
    id_buf[sizeof(id_buf) - 1] = '\0';
    char *q = strchr(id_buf, '?');
    if (q) *q = '\0';

    /* Check if ends with /export */
    char *export_suffix = strstr(id_buf, "/export");
    if (export_suffix) {
        *export_suffix = '\0';
        is_export = true;
    }

    firing_profile_t profile;
    if (firing_engine_load_profile(id_buf, &profile) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Profile not found");
        return ESP_FAIL;
    }

    /* Build profile JSON (shared between GET and export) */
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "id", profile.id);
    cJSON_AddStringToObject(p, "name", profile.name);
    cJSON_AddStringToObject(p, "description", profile.description);
    cJSON_AddNumberToObject(p, "maxTemp", profile.max_temp);
    cJSON_AddNumberToObject(p, "estimatedDuration", profile.estimated_duration);

    cJSON *segs = cJSON_AddArrayToObject(p, "segments");
    for (int j = 0; j < profile.segment_count; j++) {
        cJSON *s = cJSON_CreateObject();
        cJSON_AddStringToObject(s, "id", profile.segments[j].id);
        cJSON_AddStringToObject(s, "name", profile.segments[j].name);
        cJSON_AddNumberToObject(s, "rampRate", profile.segments[j].ramp_rate);
        cJSON_AddNumberToObject(s, "targetTemp", profile.segments[j].target_temp);
        cJSON_AddNumberToObject(s, "holdTime", profile.segments[j].hold_time);
        cJSON_AddItemToArray(segs, s);
    }

    if (is_export) {
        /* For export, set Content-Disposition header to trigger download */
        char disp[80];
        snprintf(disp, sizeof(disp), "attachment; filename=\"%s.json\"", profile.id);
        httpd_resp_set_hdr(req, "Content-Disposition", disp);
    }

    return send_json(req, p);
}

/* ── POST /api/v1/profiles ─────────────────────────── */

static esp_err_t handle_post_profile(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    char buf[2048];
    if (read_body(req, buf, sizeof(buf)) < 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body too large or empty");
        return ESP_FAIL;
    }

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return ESP_FAIL;
    }

    firing_profile_t profile;
    memset(&profile, 0, sizeof(profile));

    cJSON *j;
    j = cJSON_GetObjectItem(root, "id");
    if (j) strncpy(profile.id, j->valuestring, FIRING_ID_LEN - 1);
    j = cJSON_GetObjectItem(root, "name");
    if (j) strncpy(profile.name, j->valuestring, FIRING_NAME_LEN - 1);
    j = cJSON_GetObjectItem(root, "description");
    if (j) strncpy(profile.description, j->valuestring, FIRING_DESC_LEN - 1);
    j = cJSON_GetObjectItem(root, "maxTemp");
    if (j) profile.max_temp = (float)j->valuedouble;
    j = cJSON_GetObjectItem(root, "estimatedDuration");
    if (j) profile.estimated_duration = (uint32_t)j->valuedouble;

    cJSON *segs = cJSON_GetObjectItem(root, "segments");
    if (segs && cJSON_IsArray(segs)) {
        int count = cJSON_GetArraySize(segs);
        if (count > FIRING_MAX_SEGMENTS) count = FIRING_MAX_SEGMENTS;
        profile.segment_count = count;

        for (int i = 0; i < count; i++) {
            cJSON *seg = cJSON_GetArrayItem(segs, i);
            j = cJSON_GetObjectItem(seg, "id");
            if (j) strncpy(profile.segments[i].id, j->valuestring, FIRING_ID_LEN - 1);
            j = cJSON_GetObjectItem(seg, "name");
            if (j) strncpy(profile.segments[i].name, j->valuestring, FIRING_NAME_LEN - 1);
            j = cJSON_GetObjectItem(seg, "rampRate");
            if (j) profile.segments[i].ramp_rate = (float)j->valuedouble;
            j = cJSON_GetObjectItem(seg, "targetTemp");
            if (j) profile.segments[i].target_temp = (float)j->valuedouble;
            j = cJSON_GetObjectItem(seg, "holdTime");
            if (j) profile.segments[i].hold_time = (uint16_t)j->valuedouble;
        }
    }
    cJSON_Delete(root);

    if (profile.id[0] == '\0') {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing profile id");
        return ESP_FAIL;
    }

    esp_err_t err = firing_engine_save_profile(&profile);
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to save");
        return ESP_FAIL;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "id", profile.id);
    return send_json(req, resp);
}

/* ── DELETE /api/v1/profiles/:id ───────────────────── */

static esp_err_t handle_delete_profile(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    const char *prefix = "/api/v1/profiles/";
    const char *id = req->uri + strlen(prefix);

    char id_buf[FIRING_ID_LEN];
    strncpy(id_buf, id, sizeof(id_buf) - 1);
    id_buf[sizeof(id_buf) - 1] = '\0';
    char *q = strchr(id_buf, '?');
    if (q) *q = '\0';

    firing_engine_delete_profile(id_buf);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/firing/start ─────────────────────── */

static esp_err_t handle_firing_start(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    char buf[128];
    if (read_body(req, buf, sizeof(buf)) < 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body required");
        return ESP_FAIL;
    }

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return ESP_FAIL;
    }

    /* Parse delay_minutes (optional) */
    uint32_t delay_minutes = 0;
    cJSON *delay_item = cJSON_GetObjectItem(root, "delayMinutes");
    if (delay_item) delay_minutes = (uint32_t)delay_item->valuedouble;

    cJSON *pid_item = cJSON_GetObjectItem(root, "profileId");
    if (!pid_item || !pid_item->valuestring) {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing profileId");
        return ESP_FAIL;
    }

    firing_profile_t profile;
    if (firing_engine_load_profile(pid_item->valuestring, &profile) != ESP_OK) {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Profile not found");
        return ESP_FAIL;
    }
    cJSON_Delete(root);

    firing_cmd_t cmd = { .type = FIRING_CMD_START };
    cmd.start.profile = profile;
    cmd.start.delay_minutes = delay_minutes;
    QueueHandle_t q = firing_engine_get_cmd_queue();
    if (xQueueSend(q, &cmd, pdMS_TO_TICKS(100)) != pdTRUE) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Queue full");
        return ESP_FAIL;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/firing/stop ──────────────────────── */

static esp_err_t handle_firing_stop(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    firing_cmd_t cmd = { .type = FIRING_CMD_STOP };
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/firing/pause ─────────────────────── */

static esp_err_t handle_firing_pause(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    firing_progress_t prog;
    firing_engine_get_progress(&prog);

    firing_cmd_t cmd;
    cmd.type = (prog.status == FIRING_STATUS_PAUSED) ? FIRING_CMD_RESUME : FIRING_CMD_PAUSE;
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "action",
                            cmd.type == FIRING_CMD_PAUSE ? "paused" : "resumed");
    return send_json(req, resp);
}

/* ── GET /api/v1/settings ──────────────────────────── */

static esp_err_t handle_get_settings(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    cJSON *root = cJSON_CreateObject();
    char unit_str[2] = { settings.temp_unit, '\0' };
    cJSON_AddStringToObject(root, "tempUnit", unit_str);
    cJSON_AddNumberToObject(root, "maxSafeTemp", settings.max_safe_temp);
    cJSON_AddBoolToObject(root, "alarmEnabled", settings.alarm_enabled);
    cJSON_AddBoolToObject(root, "autoShutdown", settings.auto_shutdown);
    cJSON_AddBoolToObject(root, "notificationsEnabled", settings.notifications_enabled);
    cJSON_AddNumberToObject(root, "tcOffsetC", settings.tc_offset_c);
    cJSON_AddStringToObject(root, "webhookUrl", settings.webhook_url);
    /* Don't expose the API token value, just whether it's set */
    cJSON_AddBoolToObject(root, "apiTokenSet", settings.api_token[0] != '\0');
    cJSON_AddNumberToObject(root, "elementWatts", settings.element_watts);
    cJSON_AddNumberToObject(root, "electricityCostKwh", settings.electricity_cost_kwh);

    return send_json(req, root);
}

/* ── POST /api/v1/settings ─────────────────────────── */

static esp_err_t handle_post_settings(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    char buf[768];
    if (read_body(req, buf, sizeof(buf)) < 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body required");
        return ESP_FAIL;
    }

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return ESP_FAIL;
    }

    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    cJSON *j;
    j = cJSON_GetObjectItem(root, "tempUnit");
    if (j && j->valuestring) settings.temp_unit = j->valuestring[0];
    j = cJSON_GetObjectItem(root, "maxSafeTemp");
    if (j) settings.max_safe_temp = (float)j->valuedouble;
    j = cJSON_GetObjectItem(root, "alarmEnabled");
    if (j) settings.alarm_enabled = cJSON_IsTrue(j);
    j = cJSON_GetObjectItem(root, "autoShutdown");
    if (j) settings.auto_shutdown = cJSON_IsTrue(j);
    j = cJSON_GetObjectItem(root, "notificationsEnabled");
    if (j) settings.notifications_enabled = cJSON_IsTrue(j);
    j = cJSON_GetObjectItem(root, "tcOffsetC");
    if (j) settings.tc_offset_c = (float)j->valuedouble;
    j = cJSON_GetObjectItem(root, "webhookUrl");
    if (j && j->valuestring)
        strncpy(settings.webhook_url, j->valuestring, sizeof(settings.webhook_url) - 1);
    j = cJSON_GetObjectItem(root, "apiToken");
    if (j && j->valuestring && j->valuestring[0] != '\0')
        strncpy(settings.api_token, j->valuestring, sizeof(settings.api_token) - 1);
    j = cJSON_GetObjectItem(root, "elementWatts");
    if (j) settings.element_watts = (float)j->valuedouble;
    j = cJSON_GetObjectItem(root, "electricityCostKwh");
    if (j) settings.electricity_cost_kwh = (float)j->valuedouble;

    cJSON_Delete(root);

    firing_engine_set_settings(&settings);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── GET /api/v1/system ────────────────────────────── */

static esp_err_t handle_get_system(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "firmware", APP_FIRMWARE_VERSION);
    cJSON_AddStringToObject(root, "model", "Bisque ESP32-S3");
    cJSON_AddNumberToObject(root, "uptimeSeconds", (double)(esp_timer_get_time() / 1000000LL));
    cJSON_AddNumberToObject(root, "freeHeap", (double)esp_get_free_heap_size());
    cJSON_AddBoolToObject(root, "emergencyStop", safety_is_emergency());
    cJSON_AddNumberToObject(root, "lastErrorCode", (double)firing_engine_get_error_code());
    cJSON_AddNumberToObject(root, "elementHoursS", (double)firing_engine_get_element_hours_s());

    /* SPIFFS info */
    size_t spiffs_total = 0, spiffs_used = 0;
    esp_spiffs_info("storage", &spiffs_total, &spiffs_used);
    cJSON_AddNumberToObject(root, "spiffsTotal", (double)spiffs_total);
    cJSON_AddNumberToObject(root, "spiffsUsed", (double)spiffs_used);

    return send_json(req, root);
}

/* ── POST /api/v1/firing/skip-segment ─────────────── */

static esp_err_t handle_firing_skip_segment(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    firing_cmd_t cmd = { .type = FIRING_CMD_SKIP_SEGMENT };
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/profiles/import ─────────────────── */

static esp_err_t handle_profile_import(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    char buf[2048];
    if (read_body(req, buf, sizeof(buf)) < 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body too large or empty");
        return ESP_FAIL;
    }

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return ESP_FAIL;
    }

    firing_profile_t profile;
    memset(&profile, 0, sizeof(profile));
    cJSON *j;
    j = cJSON_GetObjectItem(root, "id");
    if (j && j->valuestring) strncpy(profile.id, j->valuestring, FIRING_ID_LEN - 1);
    j = cJSON_GetObjectItem(root, "name");
    if (j && j->valuestring) strncpy(profile.name, j->valuestring, FIRING_NAME_LEN - 1);
    j = cJSON_GetObjectItem(root, "description");
    if (j && j->valuestring) strncpy(profile.description, j->valuestring, FIRING_DESC_LEN - 1);
    j = cJSON_GetObjectItem(root, "maxTemp");
    if (j) profile.max_temp = (float)j->valuedouble;
    j = cJSON_GetObjectItem(root, "estimatedDuration");
    if (j) profile.estimated_duration = (uint32_t)j->valuedouble;

    cJSON *segs = cJSON_GetObjectItem(root, "segments");
    if (segs && cJSON_IsArray(segs)) {
        int cnt = cJSON_GetArraySize(segs);
        if (cnt > FIRING_MAX_SEGMENTS) cnt = FIRING_MAX_SEGMENTS;
        profile.segment_count = cnt;
        for (int i = 0; i < cnt; i++) {
            cJSON *seg = cJSON_GetArrayItem(segs, i);
            j = cJSON_GetObjectItem(seg, "id");
            if (j && j->valuestring) strncpy(profile.segments[i].id, j->valuestring, FIRING_ID_LEN - 1);
            j = cJSON_GetObjectItem(seg, "name");
            if (j && j->valuestring) strncpy(profile.segments[i].name, j->valuestring, FIRING_NAME_LEN - 1);
            j = cJSON_GetObjectItem(seg, "rampRate");
            if (j) profile.segments[i].ramp_rate = (float)j->valuedouble;
            j = cJSON_GetObjectItem(seg, "targetTemp");
            if (j) profile.segments[i].target_temp = (float)j->valuedouble;
            j = cJSON_GetObjectItem(seg, "holdTime");
            if (j) profile.segments[i].hold_time = (uint16_t)j->valuedouble;
        }
    }
    cJSON_Delete(root);

    if (profile.id[0] == '\0') {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing profile id");
        return ESP_FAIL;
    }

    esp_err_t err = firing_engine_save_profile(&profile);
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to save");
        return ESP_FAIL;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "id", profile.id);
    return send_json(req, resp);
}

/* ── POST /api/v1/profiles/cone-fire ──────────────── */

static esp_err_t handle_cone_fire(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    char buf[256];
    if (read_body(req, buf, sizeof(buf)) < 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body required");
        return ESP_FAIL;
    }

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return ESP_FAIL;
    }

    int cone_id = CONE_04;
    int speed   = CONE_SPEED_MEDIUM;
    bool preheat    = false;
    bool slow_cool  = false;
    bool save_profile = true;

    cJSON *j;
    j = cJSON_GetObjectItem(root, "coneId");
    if (j) cone_id = (int)j->valuedouble;
    j = cJSON_GetObjectItem(root, "speed");
    if (j) speed = (int)j->valuedouble;
    j = cJSON_GetObjectItem(root, "preheat");
    if (j) preheat = cJSON_IsTrue(j);
    j = cJSON_GetObjectItem(root, "slowCool");
    if (j) slow_cool = cJSON_IsTrue(j);
    j = cJSON_GetObjectItem(root, "save");
    if (j) save_profile = cJSON_IsTrue(j);
    cJSON_Delete(root);

    if (cone_id < 0 || cone_id >= CONE_COUNT) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid coneId");
        return ESP_FAIL;
    }

    firing_profile_t profile;
    esp_err_t err = cone_fire_generate((cone_id_t)cone_id, (cone_speed_t)speed,
                                       preheat, slow_cool, &profile);
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to generate profile");
        return ESP_FAIL;
    }

    if (save_profile) {
        firing_engine_save_profile(&profile);
    }

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "id", profile.id);
    cJSON_AddStringToObject(p, "name", profile.name);
    cJSON_AddStringToObject(p, "description", profile.description);
    cJSON_AddNumberToObject(p, "maxTemp", profile.max_temp);
    cJSON_AddNumberToObject(p, "estimatedDuration", profile.estimated_duration);
    cJSON *segs = cJSON_AddArrayToObject(p, "segments");
    for (int j2 = 0; j2 < profile.segment_count; j2++) {
        cJSON *s = cJSON_CreateObject();
        cJSON_AddStringToObject(s, "id", profile.segments[j2].id);
        cJSON_AddStringToObject(s, "name", profile.segments[j2].name);
        cJSON_AddNumberToObject(s, "rampRate", profile.segments[j2].ramp_rate);
        cJSON_AddNumberToObject(s, "targetTemp", profile.segments[j2].target_temp);
        cJSON_AddNumberToObject(s, "holdTime", profile.segments[j2].hold_time);
        cJSON_AddItemToArray(segs, s);
    }
    return send_json(req, p);
}

/* ── GET /api/v1/history ───────────────────────────── */

static esp_err_t handle_get_history(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    history_record_t records[HISTORY_MAX_RECORDS];
    int count = history_get_records(records, HISTORY_MAX_RECORDS);

    cJSON *arr = cJSON_CreateArray();
    for (int i = 0; i < count; i++) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "id", records[i].id);
        cJSON_AddNumberToObject(item, "startTime", (double)records[i].start_time);
        cJSON_AddStringToObject(item, "profileName", records[i].profile_name);
        cJSON_AddStringToObject(item, "profileId", records[i].profile_id);
        cJSON_AddNumberToObject(item, "peakTemp", records[i].peak_temp_c);
        cJSON_AddNumberToObject(item, "durationS", records[i].duration_s);
        const char *outcomes[] = { "complete", "error", "aborted" };
        cJSON_AddStringToObject(item, "outcome",
            records[i].outcome < 3 ? outcomes[records[i].outcome] : "unknown");
        cJSON_AddNumberToObject(item, "errorCode", records[i].error_code);
        cJSON_AddItemToArray(arr, item);
    }

    httpd_resp_set_type(req, "application/json");
    char *json = cJSON_PrintUnformatted(arr);
    cJSON_Delete(arr);
    httpd_resp_sendstr(req, json);
    free(json);
    return ESP_OK;
}

/* ── GET /api/v1/history/:id/trace ────────────────── */

static esp_err_t handle_get_history_trace(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;

    /* Extract record ID from URI */
    const char *prefix = "/api/v1/history/";
    const char *id_start = req->uri + strlen(prefix);
    uint32_t record_id = (uint32_t)atoi(id_start);

    /* Use a heap buffer since CSV can be large (up to ~50KB) */
    char *buf = malloc(65536);
    if (!buf) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Out of memory");
        return ESP_FAIL;
    }

    esp_err_t err = history_get_trace_csv(record_id, buf, 65536);
    if (err != ESP_OK) {
        free(buf);
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Trace not found");
        return ESP_FAIL;
    }

    char disp[64];
    snprintf(disp, sizeof(disp), "attachment; filename=\"trace_%" PRIu32 ".csv\"", record_id);
    httpd_resp_set_hdr(req, "Content-Disposition", disp);
    httpd_resp_set_type(req, "text/csv");
    httpd_resp_sendstr(req, buf);
    free(buf);
    return ESP_OK;
}

/* ── POST /api/v1/ota ──────────────────────────────── */

static esp_err_t handle_ota_upload(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;

    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (!update_partition) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                            "No OTA partition. Update partitions.csv to enable OTA.");
        return ESP_FAIL;
    }

    esp_ota_handle_t ota_handle = 0;
    esp_err_t err = esp_ota_begin(update_partition, OTA_WITH_SEQUENTIAL_WRITES, &ota_handle);
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "OTA begin failed");
        return ESP_FAIL;
    }

    char *buf = malloc(4096);
    if (!buf) {
        esp_ota_abort(ota_handle);
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Out of memory");
        return ESP_FAIL;
    }

    int remaining = req->content_len;
    bool ota_ok = true;
    while (remaining > 0 && ota_ok) {
        int to_recv = (remaining > 4096) ? 4096 : remaining;
        int received = httpd_req_recv(req, buf, to_recv);
        if (received <= 0) {
            ota_ok = false;
            break;
        }
        if (esp_ota_write(ota_handle, buf, received) != ESP_OK) {
            ota_ok = false;
            break;
        }
        remaining -= received;
    }
    free(buf);

    if (!ota_ok || esp_ota_end(ota_handle) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "OTA write failed");
        return ESP_FAIL;
    }

    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "OTA set boot failed");
        return ESP_FAIL;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "message", "OTA complete. Rebooting...");
    send_json(req, resp);

    /* Small delay then reboot */
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

/* ── POST /api/v1/diagnostics/relay ───────────────── */

static esp_err_t handle_diag_relay(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;

    /* Only allow relay test when not firing */
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    if (prog.is_active) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Cannot test relay during firing");
        return ESP_FAIL;
    }

    char buf[64];
    int duration_s = 2;  /* default 2 seconds */
    if (read_body(req, buf, sizeof(buf)) > 0) {
        cJSON *root = cJSON_Parse(buf);
        if (root) {
            cJSON *j = cJSON_GetObjectItem(root, "durationSeconds");
            if (j) duration_s = (int)j->valuedouble;
            cJSON_Delete(root);
        }
    }
    if (duration_s < 1) duration_s = 1;
    if (duration_s > 10) duration_s = 10;

    ESP_LOGI(TAG, "Relay test: %d seconds", duration_s);
    safety_set_ssr(1.0f);
    vTaskDelay(pdMS_TO_TICKS(duration_s * 1000));
    safety_set_ssr(0.0f);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddNumberToObject(resp, "durationSeconds", duration_s);
    return send_json(req, resp);
}

/* ── GET /api/v1/diagnostics/thermocouple ─────────── */

static esp_err_t handle_diag_thermocouple(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;

    thermocouple_reading_t tc;
    thermocouple_get_latest(&tc);

    int64_t now_us = esp_timer_get_time();
    int64_t age_ms = (tc.timestamp_us > 0) ? ((now_us - tc.timestamp_us) / 1000) : -1;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "temperatureC", tc.temperature_c);
    cJSON_AddNumberToObject(root, "internalTempC", tc.internal_temp_c);
    cJSON_AddBoolToObject(root, "fault", tc.fault != 0);
    cJSON_AddBoolToObject(root, "openCircuit", (tc.fault & TC_FAULT_OPEN_CIRCUIT) != 0);
    cJSON_AddBoolToObject(root, "shortGnd", (tc.fault & TC_FAULT_SHORT_GND) != 0);
    cJSON_AddBoolToObject(root, "shortVcc", (tc.fault & TC_FAULT_SHORT_VCC) != 0);
    cJSON_AddNumberToObject(root, "readingAgeMs", (double)age_ms);

    /* Also return offset-adjusted temperature */
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);
    cJSON_AddNumberToObject(root, "temperatureAdjustedC", tc.temperature_c + settings.tc_offset_c);
    cJSON_AddNumberToObject(root, "tcOffsetC", settings.tc_offset_c);

    return send_json(req, root);
}

/* ── GET /api/v1/cone-table ────────────────────────── */

static esp_err_t handle_get_cone_table(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;

    cJSON *arr = cJSON_CreateArray();
    for (int i = 0; i < CONE_COUNT; i++) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "id", i);
        cJSON_AddStringToObject(item, "name", cone_name((cone_id_t)i));
        cJSON_AddNumberToObject(item, "slowTempC",   cone_target_temp_c((cone_id_t)i, CONE_SPEED_SLOW));
        cJSON_AddNumberToObject(item, "mediumTempC", cone_target_temp_c((cone_id_t)i, CONE_SPEED_MEDIUM));
        cJSON_AddNumberToObject(item, "fastTempC",   cone_target_temp_c((cone_id_t)i, CONE_SPEED_FAST));
        cJSON_AddItemToArray(arr, item);
    }

    httpd_resp_set_type(req, "application/json");
    char *json = cJSON_PrintUnformatted(arr);
    cJSON_Delete(arr);
    httpd_resp_sendstr(req, json);
    free(json);
    return ESP_OK;
}

/* ── POST /api/v1/autotune/start ───────────────────── */

static esp_err_t handle_autotune_start(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    char buf[128];
    if (read_body(req, buf, sizeof(buf)) < 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body required");
        return ESP_FAIL;
    }

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return ESP_FAIL;
    }

    float setpoint = 500.0f, hysteresis = 5.0f;
    cJSON *j = cJSON_GetObjectItem(root, "setpoint");
    if (j) setpoint = (float)j->valuedouble;
    j = cJSON_GetObjectItem(root, "hysteresis");
    if (j) hysteresis = (float)j->valuedouble;
    cJSON_Delete(root);

    /* Validate against max safe temp */
    if (setpoint > safety_get_max_temp()) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Setpoint exceeds max safe temp");
        return ESP_FAIL;
    }

    firing_cmd_t cmd = { .type = FIRING_CMD_AUTOTUNE_START };
    cmd.autotune.setpoint = setpoint;
    cmd.autotune.hysteresis = hysteresis;
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/autotune/stop ────────────────────── */

static esp_err_t handle_autotune_stop(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    firing_cmd_t cmd = { .type = FIRING_CMD_AUTOTUNE_STOP };
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── GET /api/v1/autotune/status ───────────────────── */

static esp_err_t handle_autotune_status(httpd_req_t *req)
{
    if (!require_auth(req)) return ESP_FAIL;
    /* Access autotune state via progress */
    firing_progress_t prog;
    firing_engine_get_progress(&prog);

    /* The autotune struct is internal to firing_engine, so we expose it via the
       progress status + dedicated fields. For now, return the progress-based view. */
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "state",
                            prog.status == FIRING_STATUS_AUTOTUNE ? "running" :
                            prog.status == FIRING_STATUS_IDLE ? "idle" : "stopped");
    cJSON_AddNumberToObject(root, "elapsedTime", prog.elapsed_time);
    cJSON_AddNumberToObject(root, "targetTemp", prog.target_temp);
    cJSON_AddNumberToObject(root, "currentTemp", prog.current_temp);

    /* PID gains (current) */
    float kp, ki, kd;
    pid_load_gains(&kp, &ki, &kd);
    cJSON *gains = cJSON_AddObjectToObject(root, "currentGains");
    cJSON_AddNumberToObject(gains, "kp", kp);
    cJSON_AddNumberToObject(gains, "ki", ki);
    cJSON_AddNumberToObject(gains, "kd", kd);

    return send_json(req, root);
}

/* ── Register All Handlers ─────────────────────────── */

#define REGISTER_API(path, http_method, fn) do { \
    httpd_uri_t u = { .uri = path, .method = http_method, .handler = fn, .user_ctx = NULL }; \
    esp_err_t e = httpd_register_uri_handler(server, &u); \
    if (e != ESP_OK) ESP_LOGW(TAG, "Failed to register %s: %s", path, esp_err_to_name(e)); \
} while(0)

esp_err_t api_handlers_register(httpd_handle_t server)
{
    /* Core endpoints */
    REGISTER_API("/api/v1/status",                   HTTP_GET,    handle_get_status);
    REGISTER_API("/api/v1/profiles",                 HTTP_GET,    handle_get_profiles);
    REGISTER_API("/api/v1/profiles",                 HTTP_POST,   handle_post_profile);
    REGISTER_API("/api/v1/profiles/import",          HTTP_POST,   handle_profile_import);
    REGISTER_API("/api/v1/profiles/cone-fire",       HTTP_POST,   handle_cone_fire);
    REGISTER_API("/api/v1/profiles/*",               HTTP_GET,    handle_get_profile);
    REGISTER_API("/api/v1/profiles/*",               HTTP_DELETE, handle_delete_profile);

    /* Firing control */
    REGISTER_API("/api/v1/firing/start",             HTTP_POST,   handle_firing_start);
    REGISTER_API("/api/v1/firing/stop",              HTTP_POST,   handle_firing_stop);
    REGISTER_API("/api/v1/firing/pause",             HTTP_POST,   handle_firing_pause);
    REGISTER_API("/api/v1/firing/skip-segment",      HTTP_POST,   handle_firing_skip_segment);

    /* Settings + system */
    REGISTER_API("/api/v1/settings",                 HTTP_GET,    handle_get_settings);
    REGISTER_API("/api/v1/settings",                 HTTP_POST,   handle_post_settings);
    REGISTER_API("/api/v1/system",                   HTTP_GET,    handle_get_system);

    /* Auto-tune */
    REGISTER_API("/api/v1/autotune/start",           HTTP_POST,   handle_autotune_start);
    REGISTER_API("/api/v1/autotune/stop",            HTTP_POST,   handle_autotune_stop);
    REGISTER_API("/api/v1/autotune/status",          HTTP_GET,    handle_autotune_status);

    /* Cone table */
    REGISTER_API("/api/v1/cone-table",               HTTP_GET,    handle_get_cone_table);

    /* Firing history */
    REGISTER_API("/api/v1/history",                  HTTP_GET,    handle_get_history);
    REGISTER_API("/api/v1/history/*",                HTTP_GET,    handle_get_history_trace);

    /* OTA */
    REGISTER_API("/api/v1/ota",                      HTTP_POST,   handle_ota_upload);

    /* Diagnostics */
    REGISTER_API("/api/v1/diagnostics/relay",        HTTP_POST,   handle_diag_relay);
    REGISTER_API("/api/v1/diagnostics/thermocouple", HTTP_GET,    handle_diag_thermocouple);

    ESP_LOGI(TAG, "API handlers registered (%d endpoints)", 25);
    return ESP_OK;
}
