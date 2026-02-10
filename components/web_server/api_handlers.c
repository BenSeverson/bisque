#include "web_server.h"
#include "firing_engine.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "pid_control.h"
#include "safety.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "cJSON.h"
#include <string.h>

static const char *TAG = "api";

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

/* ── GET /api/v1/profiles/:id ──────────────────────── */

static esp_err_t handle_get_profile(httpd_req_t *req)
{
    /* Extract ID from URI: /api/v1/profiles/<id> */
    const char *uri = req->uri;
    const char *prefix = "/api/v1/profiles/";
    if (strncmp(uri, prefix, strlen(prefix)) != 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Bad request");
        return ESP_FAIL;
    }
    const char *id = uri + strlen(prefix);

    /* Strip query string */
    char id_buf[FIRING_ID_LEN];
    strncpy(id_buf, id, sizeof(id_buf) - 1);
    id_buf[sizeof(id_buf) - 1] = '\0';
    char *q = strchr(id_buf, '?');
    if (q) *q = '\0';

    firing_profile_t profile;
    if (firing_engine_load_profile(id_buf, &profile) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Profile not found");
        return ESP_FAIL;
    }

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

    return send_json(req, p);
}

/* ── POST /api/v1/profiles ─────────────────────────── */

static esp_err_t handle_post_profile(httpd_req_t *req)
{
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
    firing_cmd_t cmd = { .type = FIRING_CMD_STOP };
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/firing/pause ─────────────────────── */

static esp_err_t handle_firing_pause(httpd_req_t *req)
{
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
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    cJSON *root = cJSON_CreateObject();
    char unit_str[2] = { settings.temp_unit, '\0' };
    cJSON_AddStringToObject(root, "tempUnit", unit_str);
    cJSON_AddNumberToObject(root, "maxSafeTemp", settings.max_safe_temp);
    cJSON_AddBoolToObject(root, "alarmEnabled", settings.alarm_enabled);
    cJSON_AddBoolToObject(root, "autoShutdown", settings.auto_shutdown);
    cJSON_AddBoolToObject(root, "notificationsEnabled", settings.notifications_enabled);

    return send_json(req, root);
}

/* ── POST /api/v1/settings ─────────────────────────── */

static esp_err_t handle_post_settings(httpd_req_t *req)
{
    char buf[512];
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

    cJSON_Delete(root);

    firing_engine_set_settings(&settings);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── GET /api/v1/system ────────────────────────────── */

static esp_err_t handle_get_system(httpd_req_t *req)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "firmware", "1.0.0");
    cJSON_AddStringToObject(root, "model", "Bisque ESP32-S3");
    cJSON_AddNumberToObject(root, "uptimeSeconds", (double)(esp_timer_get_time() / 1000000LL));
    cJSON_AddNumberToObject(root, "freeHeap", (double)esp_get_free_heap_size());
    cJSON_AddBoolToObject(root, "emergencyStop", safety_is_emergency());
    return send_json(req, root);
}

/* ── POST /api/v1/autotune/start ───────────────────── */

static esp_err_t handle_autotune_start(httpd_req_t *req)
{
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
    firing_cmd_t cmd = { .type = FIRING_CMD_AUTOTUNE_STOP };
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── GET /api/v1/autotune/status ───────────────────── */

static esp_err_t handle_autotune_status(httpd_req_t *req)
{
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
    REGISTER_API("/api/v1/status",          HTTP_GET,    handle_get_status);
    REGISTER_API("/api/v1/profiles",        HTTP_GET,    handle_get_profiles);
    REGISTER_API("/api/v1/profiles/*",      HTTP_GET,    handle_get_profile);
    REGISTER_API("/api/v1/profiles",        HTTP_POST,   handle_post_profile);
    REGISTER_API("/api/v1/profiles/*",      HTTP_DELETE, handle_delete_profile);
    REGISTER_API("/api/v1/firing/start",    HTTP_POST,   handle_firing_start);
    REGISTER_API("/api/v1/firing/stop",     HTTP_POST,   handle_firing_stop);
    REGISTER_API("/api/v1/firing/pause",    HTTP_POST,   handle_firing_pause);
    REGISTER_API("/api/v1/settings",        HTTP_GET,    handle_get_settings);
    REGISTER_API("/api/v1/settings",        HTTP_POST,   handle_post_settings);
    REGISTER_API("/api/v1/system",          HTTP_GET,    handle_get_system);
    REGISTER_API("/api/v1/autotune/start",  HTTP_POST,   handle_autotune_start);
    REGISTER_API("/api/v1/autotune/stop",   HTTP_POST,   handle_autotune_stop);
    REGISTER_API("/api/v1/autotune/status", HTTP_GET,    handle_autotune_status);

    ESP_LOGI(TAG, "API handlers registered (14 endpoints)");
    return ESP_OK;
}
