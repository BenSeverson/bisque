#include "web_server.h"
#include "api_json.h"
#include "auth_helpers.h"
#include "firing_engine.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "pid_control.h"
#include "safety.h"
#include "cone_table.h"
#include "firing_history.h"
#include "wifi_manager.h"
#include "app_config.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_spiffs.h"
#include "esp_ota_ops.h"
#include "esp_app_desc.h"
#include "esp_http_client.h"
#include "ota_manager.h"
#include "esp_system.h"
#include "driver/temperature_sensor.h"
#include <inttypes.h>
#include "cJSON.h"
#include <ctype.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

static const char *TAG = "api";

/* ── Internal temperature sensor ──────────────────── */
static temperature_sensor_handle_t s_board_temp_handle = NULL;

/* ── Auth helpers ──────────────────────────────────── */

/* Longest query string we will read: "token=" plus a fully percent-encoded
 * token (every byte -> %XX) plus the terminator. httpd_query_key_value()
 * returns ESP_ERR_HTTPD_RESULT_TRUNC rather than a partial value, so an
 * undersized buffer here reads as "wrong token", not as a short one. */
#define AUTH_TOKEN_MAX   (sizeof(((kiln_settings_t *)0)->api_token) - 1)
#define AUTH_ENCODED_MAX (AUTH_TOKEN_MAX * 3)
#define AUTH_QUERY_BUF   (sizeof("token=") + AUTH_ENCODED_MAX)

/**
 * Percent-decode `src` into `dst` in place-safe fashion (dst may equal src).
 *
 * `%` followed by two hex digits becomes the byte; anything else is copied
 * verbatim, including a lone `%` or a truncated escape at the end. `+` is
 * *not* treated as a space: that convention belongs to
 * application/x-www-form-urlencoded form bodies, while the web client builds
 * this value with encodeURIComponent(), which emits `%2B` for a literal plus.
 * Decoding `+` here would corrupt a token that genuinely contains one.
 *
 * Returns the decoded length. `dst` must have room for strlen(src) + 1.
 */
static size_t url_decode_inplace(char *dst, const char *src)
{
    size_t w = 0;
    for (size_t r = 0; src[r] != '\0'; r++) {
        if (src[r] == '%' && isxdigit((unsigned char)src[r + 1]) && isxdigit((unsigned char)src[r + 2])) {
            const char hex[3] = {src[r + 1], src[r + 2], '\0'};
            dst[w++] = (char)strtol(hex, NULL, 16);
            r += 2;
        } else {
            dst[w++] = src[r];
        }
    }
    dst[w] = '\0';
    return w;
}

/**
 * Check Bearer token auth. Returns true if request is authorized.
 * If token is empty in settings, all requests are authorized.
 *
 * Declared in web_server.h rather than kept static: the WebSocket handshake
 * callback in ws_handler.c gates on the same rule, and a second copy of it
 * there is a copy that can drift out of step with this one.
 *
 * Both channels use auth_token_equal, which accumulates every byte difference
 * instead of returning at the first one (#81).
 *
 * #81 also proposed dropping the `?token=` query parameter — a credential in a
 * URL reaches proxy logs, browser history and `Referer` headers — on the
 * grounds that every REST client sends the header anyway and the WebSocket
 * handshake did not consult this function at all. That last part stopped being
 * true in #236: the handshake is authenticated now, and a browser cannot set
 * headers on one, so the query parameter is the *only* credential the web
 * client can present on /api/v1/ws. Removing it would lock every browser out
 * of live telemetry. It stays, and the exposure is recorded in the README's
 * network security section rather than pretended away.
 */
bool web_auth_check(httpd_req_t *req)
{
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    /* No token configured → open access */
    if (settings.api_token[0] == '\0') {
        return true;
    }

    /* Check Authorization: Bearer <token> */
    char auth_hdr[96] = {0};
    if (httpd_req_get_hdr_value_str(req, "Authorization", auth_hdr, sizeof(auth_hdr)) == ESP_OK) {
        const char *supplied = NULL;
        if (auth_bearer_token(auth_hdr, &supplied) &&
            auth_token_equal(supplied, settings.api_token, sizeof(settings.api_token))) {
            return true;
        }
    }

    /* Check ?token= query parameter.
     *
     * The value arrives percent-encoded — the web client builds it with
     * encodeURIComponent(), and httpd_query_key_value() memcpy's the raw bytes
     * without decoding (esp_http_server/src/httpd_parse.c:945). Comparing them
     * undecoded rejects every token containing a character encodeURIComponent
     * escapes, which for a base64 token means any `+`, `/` or `=` — so exactly
     * the strong tokens fail while weak alphanumeric ones pass. On the
     * WebSocket handshake that is the whole credential (browsers cannot set
     * headers there), so the symptom is a dashboard that polls fine over REST
     * and never receives a live update. */
    char token_param[AUTH_QUERY_BUF] = {0};
    if (httpd_req_get_url_query_str(req, token_param, sizeof(token_param)) == ESP_OK) {
        char val[AUTH_ENCODED_MAX + 1] = {0};
        if (httpd_query_key_value(token_param, "token", val, sizeof(val)) == ESP_OK) {
            url_decode_inplace(val, val);
            if (auth_token_equal(val, settings.api_token, sizeof(settings.api_token))) {
                return true;
            }
        }
    }

    return false;
}

static bool require_auth(httpd_req_t *req)
{
    if (!web_auth_check(req)) {
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
    if (!settings.notifications_enabled || settings.webhook_url[0] == '\0') {
        return;
    }

    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "event", event);
    cJSON_AddStringToObject(body, "profileName", profile_name ? profile_name : "");
    cJSON_AddNumberToObject(body, "peakTemp", peak_temp);
    cJSON_AddNumberToObject(body, "durationS", duration_s);
    char *json = cJSON_PrintUnformatted(body);
    cJSON_Delete(body);
    if (!json) {
        return;
    }

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
    /* httpd_req_recv may return fewer bytes than asked when the body spans
       multiple TCP segments, so loop until the whole body is read. */
    int total = 0;
    while (total < remaining) {
        int received = httpd_req_recv(req, buf + total, remaining - total);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
        if (received <= 0) {
            return -1;
        }
        total += received;
    }
    buf[total] = '\0';
    return total;
}

/* Helper: read POST body and parse as JSON. On error, sends a 400 response and
   returns NULL. Caller must cJSON_Delete() the returned object on success. */
static cJSON *parse_body_json(httpd_req_t *req, char *buf, size_t buf_size)
{
    if (read_body(req, buf, buf_size) < 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body required or too large");
        return NULL;
    }
    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return NULL;
    }
    return root;
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

/* ── Profile parsing helper (inverse of build_profile_json) ──────────── */

static bool profile_from_json(cJSON *root, firing_profile_t *out)
{
    memset(out, 0, sizeof(*out));

    cJSON *j;
    j = cJSON_GetObjectItem(root, "id");
    if (j && j->valuestring) {
        strncpy(out->id, j->valuestring, FIRING_ID_LEN - 1);
    }
    j = cJSON_GetObjectItem(root, "name");
    if (j && j->valuestring) {
        strncpy(out->name, j->valuestring, FIRING_NAME_LEN - 1);
    }
    j = cJSON_GetObjectItem(root, "description");
    if (j && j->valuestring) {
        strncpy(out->description, j->valuestring, FIRING_DESC_LEN - 1);
    }
    j = cJSON_GetObjectItem(root, "maxTemp");
    if (j) {
        out->max_temp = (float)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "estimatedDuration");
    if (j) {
        out->estimated_duration = (uint32_t)j->valuedouble;
    }

    cJSON *segs = cJSON_GetObjectItem(root, "segments");
    if (segs && cJSON_IsArray(segs)) {
        int count = cJSON_GetArraySize(segs);
        if (count > FIRING_MAX_SEGMENTS) {
            count = FIRING_MAX_SEGMENTS;
        }
        out->segment_count = count;
        for (int i = 0; i < count; i++) {
            cJSON *seg = cJSON_GetArrayItem(segs, i);
            j = cJSON_GetObjectItem(seg, "id");
            if (j && j->valuestring) {
                strncpy(out->segments[i].id, j->valuestring, FIRING_ID_LEN - 1);
            }
            j = cJSON_GetObjectItem(seg, "name");
            if (j && j->valuestring) {
                strncpy(out->segments[i].name, j->valuestring, FIRING_NAME_LEN - 1);
            }
            j = cJSON_GetObjectItem(seg, "rampRate");
            if (j) {
                out->segments[i].ramp_rate = (float)j->valuedouble;
            }
            j = cJSON_GetObjectItem(seg, "targetTemp");
            if (j) {
                out->segments[i].target_temp = (float)j->valuedouble;
            }
            j = cJSON_GetObjectItem(seg, "holdTime");
            if (j) {
                out->segments[i].hold_time = (uint16_t)j->valuedouble;
            }
        }
    }

    return out->id[0] != '\0';
}

/* Validate a profile is safe to fire: bounded segments, finite/in-range
   targets and ramp rates. Writes a human-readable reason into err on
   failure. Returns true if the profile is acceptable. */
static bool validate_profile(const firing_profile_t *p, char *err, size_t errlen)
{
    if (p->segment_count == 0 || p->segment_count > FIRING_MAX_SEGMENTS) {
        snprintf(err, errlen, "Invalid segment_count: %u", p->segment_count);
        return false;
    }
    float max_safe = safety_get_max_temp();
    if (p->max_temp > 0.0f && p->max_temp > max_safe) {
        snprintf(err, errlen, "Profile max_temp %.0f exceeds safe limit %.0f", p->max_temp, max_safe);
        return false;
    }
    for (uint8_t i = 0; i < p->segment_count; i++) {
        const firing_segment_t *s = &p->segments[i];
        if (!isfinite(s->target_temp) || s->target_temp <= 0.0f) {
            snprintf(err, errlen, "Segment %u: invalid target_temp", i);
            return false;
        }
        if (s->target_temp > max_safe) {
            snprintf(err, errlen, "Segment %u target %.0f exceeds safe limit %.0f", i, s->target_temp, max_safe);
            return false;
        }
        if (!isfinite(s->ramp_rate) || s->ramp_rate == 0.0f) {
            snprintf(err, errlen, "Segment %u: invalid ramp_rate", i);
            return false;
        }
    }
    /* Ramp direction must match each segment's target relative to where it
       begins. Segment 0's start is the (unknown-at-save-time) kiln temperature,
       so it is skipped here via a non-finite seed and re-checked at firing
       start; inter-segment inconsistencies are fully determined by the profile
       and caught now. */
    int bad_seg = firing_first_bad_ramp_sign(p, NAN);
    if (bad_seg >= 0) {
        snprintf(err, errlen, "Segment %d: ramp direction contradicts its target", bad_seg);
        return false;
    }
    return true;
}

/* ── GET /api/v1/status ────────────────────────────── */

static esp_err_t handle_get_status(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    firing_progress_t prog;
    firing_engine_get_progress(&prog);

    thermocouple_reading_t tc;
    thermocouple_get_latest(&tc);

    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    return send_json(req, build_status_json(&prog, &tc, settings.tc_offset_c, safety_get_ssr_duty(),
                                            safety_get_vent_state(), safety_get_lid_state()));
}

/* ── GET /api/v1/profiles ──────────────────────────── */

static esp_err_t handle_get_profiles(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    char ids[FIRING_MAX_PROFILES][FIRING_ID_LEN];
    int count = firing_engine_list_profiles(ids, FIRING_MAX_PROFILES);

    cJSON *arr = cJSON_CreateArray();
    for (int i = 0; i < count; i++) {
        firing_profile_t profile;
        if (firing_engine_load_profile(ids[i], &profile) == ESP_OK) {
            cJSON_AddItemToArray(arr, build_profile_json(&profile));
        }
    }

    return send_json(req, arr);
}

/* ── GET /api/v1/profiles/:id  (and /api/v1/profiles/:id/export) ─────── */

static esp_err_t handle_get_profile(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    /* Extract ID from URI: /api/v1/profiles/<id> or /api/v1/profiles/<id>/export */
    const char *uri = req->uri;
    const char *prefix = "/api/v1/profiles/";
    if (strncmp(uri, prefix, strlen(prefix)) != 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Bad request");
        return ESP_FAIL;
    }
    const char *id_start = uri + strlen(prefix);

    /* Find the ID's end on the *full* URI before copying — stop at a query
       string or the "/export" suffix. Doing this on a truncated copy dropped the
       suffix (and mangled the ID) for IDs near FIRING_ID_LEN. */
    bool is_export = false;
    const char *id_end = id_start + strcspn(id_start, "?");
    const char *export_suffix = strstr(id_start, "/export");
    if (export_suffix && export_suffix < id_end) {
        id_end = export_suffix;
        is_export = true;
    }

    size_t id_len = (size_t)(id_end - id_start);
    if (id_len >= FIRING_ID_LEN) {
        id_len = FIRING_ID_LEN - 1;
    }
    char id_buf[FIRING_ID_LEN];
    memcpy(id_buf, id_start, id_len);
    id_buf[id_len] = '\0';

    firing_profile_t profile;
    if (firing_engine_load_profile(id_buf, &profile) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Profile not found");
        return ESP_FAIL;
    }

    /* Build profile JSON (shared between GET and export) */
    cJSON *p = build_profile_json(&profile);

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
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    char buf[2048];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    firing_profile_t profile;
    if (!profile_from_json(root, &profile)) {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing profile id");
        return ESP_FAIL;
    }
    cJSON_Delete(root);

    /* Validate at save time, not only at firing start. Without this an invalid
       profile (zero/negative target, wrong-sign ramp, over-limit) saves with
       200 OK and only fails with an opaque error when the user tries to fire
       it later. */
    char verr[96];
    if (!validate_profile(&profile, verr, sizeof(verr))) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, verr);
        return ESP_FAIL;
    }

    esp_err_t err = firing_engine_save_profile(&profile);
    if (err == ESP_ERR_INVALID_STATE) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Profile id collides with an existing profile");
        return ESP_FAIL;
    }
    if (err == ESP_ERR_NO_MEM) {
        /* Storage limit, not a server fault — report it so the client can tell
           the user to delete a profile rather than showing a generic failure. */
        httpd_resp_set_status(req, "507 Insufficient Storage");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Profile limit reached; delete a profile first");
        return ESP_FAIL;
    }
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
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    const char *prefix = "/api/v1/profiles/";
    const char *id = req->uri + strlen(prefix);

    char id_buf[FIRING_ID_LEN];
    strncpy(id_buf, id, sizeof(id_buf) - 1);
    id_buf[sizeof(id_buf) - 1] = '\0';
    char *q = strchr(id_buf, '?');
    if (q) {
        *q = '\0';
    }

    firing_engine_delete_profile(id_buf);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/*
 * Refuse to start a kiln operation while a firmware update is running — an
 * OTA install downloads in the background and then reboots, which would kill
 * a firing mid-cycle. Sends a 409 response and returns true if blocked.
 */
static bool firing_blocked_by_ota(httpd_req_t *req)
{
    if (ota_is_busy()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Cannot start while a firmware update is in progress");
        return true;
    }
    return false;
}

/* ── POST /api/v1/firing/start ─────────────────────── */

static esp_err_t handle_firing_start(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    if (firing_blocked_by_ota(req)) {
        return ESP_FAIL;
    }
    char buf[128];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    /* Parse delay_minutes (optional) */
    uint32_t delay_minutes = 0;
    const cJSON *delay_item = cJSON_GetObjectItem(root, "delayMinutes");
    if (delay_item) {
        double dm = delay_item->valuedouble;
        const uint32_t max_delay = 7u * 24u * 60u; /* 7 days */
        if (!isfinite(dm) || dm < 0.0 || dm > (double)max_delay) {
            cJSON_Delete(root);
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "delayMinutes out of range");
            return ESP_FAIL;
        }
        delay_minutes = (uint32_t)dm;
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

    /* Reject if a firing (or armed delay) is already active. */
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    if (prog.is_active) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        const char *msg = "Firing already active";
        httpd_resp_send(req, msg, HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }
    /* A relay diagnostic holds the SSR but reports is_active == false; the
       engine would drop a queued START, so reject here for a real 409 instead
       of a false {ok:true}. */
    if (firing_engine_relay_test_active()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_send(req, "Relay test in progress", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }

    /* A firing started into an open lid would sit at zero power with no visible
       cause; answer at the moment of the click instead. warn mode is
       report-only and deliberately does not block. The engine repeats this
       check, so the LCD start path behaves the same way. */
    kiln_settings_t lid_settings;
    firing_engine_get_settings(&lid_settings);
    if (lid_settings.lid_mode != LID_MODE_WARN && safety_get_lid_state() == LID_STATE_OPEN) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_send(req, "Lid is open", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }

    char err[96];
    if (!validate_profile(&profile, err, sizeof(err))) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, err);
        return ESP_FAIL;
    }

    /* validate_profile() cannot judge segment 0's ramp direction — it has no
       start temperature — so for an immediate start do it here, against the
       live reading, rather than letting the engine reject the queued command
       asynchronously and leaving the client showing a firing that never began.
       Delayed starts are deliberately excluded: the kiln is often still hot
       when one is queued and will have cooled by expiry, so the engine runs
       this same check then, against the temperature that actually applies. */
    if (delay_minutes == 0) {
        thermocouple_reading_t start_tc;
        thermocouple_get_latest(&start_tc);
        kiln_settings_t start_settings;
        firing_engine_get_settings(&start_settings);
        int bad_seg = firing_first_bad_ramp_sign(&profile, start_tc.temperature_c + start_settings.tc_offset_c);
        if (bad_seg >= 0) {
            snprintf(err, sizeof(err), "Segment %d: ramp direction contradicts its target at the current temperature",
                     bad_seg);
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, err);
            return ESP_FAIL;
        }
    }

    firing_cmd_t cmd = {.type = FIRING_CMD_START};
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
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    firing_cmd_t cmd = {.type = FIRING_CMD_STOP};
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/firing/pause ─────────────────────── */

static esp_err_t handle_firing_pause(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    firing_progress_t prog;
    firing_engine_get_progress(&prog);

    firing_cmd_t cmd;
    cmd.type = (prog.status == FIRING_STATUS_PAUSED) ? FIRING_CMD_RESUME : FIRING_CMD_PAUSE;
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "action", cmd.type == FIRING_CMD_PAUSE ? "paused" : "resumed");
    return send_json(req, resp);
}

/* ── GET /api/v1/settings ──────────────────────────── */

static esp_err_t handle_get_settings(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    kiln_settings_t settings;
    firing_engine_get_settings(&settings);
    return send_json(req, build_settings_json(&settings));
}

/* ── POST /api/v1/settings ─────────────────────────── */

static esp_err_t handle_post_settings(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    char buf[768];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    cJSON *j;
    j = cJSON_GetObjectItem(root, "tempUnit");
    if (j && j->valuestring) {
        settings.temp_unit = j->valuestring[0];
    }
    j = cJSON_GetObjectItem(root, "maxSafeTemp");
    if (j) {
        settings.max_safe_temp = (float)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "alarmEnabled");
    if (j) {
        settings.alarm_enabled = cJSON_IsTrue(j);
    }
    j = cJSON_GetObjectItem(root, "autoShutdown");
    if (j) {
        settings.auto_shutdown = cJSON_IsTrue(j);
    }
    j = cJSON_GetObjectItem(root, "notificationsEnabled");
    if (j) {
        settings.notifications_enabled = cJSON_IsTrue(j);
    }
    j = cJSON_GetObjectItem(root, "tcOffsetC");
    if (j) {
        settings.tc_offset_c = (float)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "webhookUrl");
    if (j && j->valuestring) {
        strncpy(settings.webhook_url, j->valuestring, sizeof(settings.webhook_url) - 1);
    }
    j = cJSON_GetObjectItem(root, "apiToken");
    if (j && cJSON_IsString(j) && j->valuestring) {
        /* An explicit empty string means "clear the token"; omitting the field
           entirely means "leave it unchanged". Previously an empty string was
           silently ignored, so the UI's Clear action could never actually clear
           it server-side — the client dropped the token, the device kept it,
           and every later request 401'd. */
        if (strlen(j->valuestring) >= sizeof(settings.api_token)) {
            /* Reject rather than truncate: a truncated token would leave the
               client authenticating with the full string the device never
               stored — the same lockout by a different route. */
            cJSON_Delete(root);
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "API token too long");
            return ESP_FAIL;
        }
        strncpy(settings.api_token, j->valuestring, sizeof(settings.api_token) - 1);
        settings.api_token[sizeof(settings.api_token) - 1] = '\0';
    }
    j = cJSON_GetObjectItem(root, "elementWatts");
    if (j) {
        settings.element_watts = (float)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "electricityCostKwh");
    if (j) {
        settings.electricity_cost_kwh = (float)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "lidMode");
    if (cJSON_IsString(j)) {
        lid_mode_t mode;
        /* Reject an unrecognized mode rather than falling back to a default:
           silently landing on "warn" would disarm an interlock its owner
           believes is armed, and the client would see a 200. */
        if (!lid_mode_from_string(cJSON_GetStringValue(j), &mode)) {
            cJSON_Delete(root);
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid lidMode");
            return ESP_FAIL;
        }
        settings.lid_mode = mode;
    }

    cJSON_Delete(root);

    firing_engine_set_settings(&settings);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── GET /api/v1/system ────────────────────────────── */

static esp_err_t handle_get_system(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    /* Internal temperature sensor (board/chip temp) */
    float board_temp = 0;
    if (s_board_temp_handle) {
        temperature_sensor_get_celsius(s_board_temp_handle, &board_temp);
    }

    size_t spiffs_total = 0, spiffs_used = 0;
    esp_spiffs_info("storage", &spiffs_total, &spiffs_used);

    system_info_json_t info = {
        .firmware = esp_app_get_description()->version,
        .model = "Bisque ESP32-S3",
        .uptime_seconds = (double)esp_timer_get_time() / 1000000.0,
        .free_heap = esp_get_free_heap_size(),
        .emergency_stop = safety_is_emergency(),
        .last_error_code = (int)firing_engine_get_error_code(),
        .element_hours_s = firing_engine_get_element_hours_s(),
        .board_temp_c = board_temp,
        .spiffs_total = spiffs_total,
        .spiffs_used = spiffs_used,
    };
    return send_json(req, build_system_json(&info));
}

/* ── POST /api/v1/firing/skip-segment ─────────────── */

static esp_err_t handle_firing_skip_segment(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    firing_cmd_t cmd = {.type = FIRING_CMD_SKIP_SEGMENT};
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── POST /api/v1/profiles/import ─────────────────── */

static esp_err_t handle_profile_import(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    char buf[2048];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    firing_profile_t profile;
    if (!profile_from_json(root, &profile)) {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing profile id");
        return ESP_FAIL;
    }
    cJSON_Delete(root);

    /* Validate at save time, not only at firing start. Without this an invalid
       profile (zero/negative target, wrong-sign ramp, over-limit) saves with
       200 OK and only fails with an opaque error when the user tries to fire
       it later. */
    char verr[96];
    if (!validate_profile(&profile, verr, sizeof(verr))) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, verr);
        return ESP_FAIL;
    }

    esp_err_t err = firing_engine_save_profile(&profile);
    if (err == ESP_ERR_INVALID_STATE) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Profile id collides with an existing profile");
        return ESP_FAIL;
    }
    if (err == ESP_ERR_NO_MEM) {
        /* Storage limit, not a server fault — report it so the client can tell
           the user to delete a profile rather than showing a generic failure. */
        httpd_resp_set_status(req, "507 Insufficient Storage");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Profile limit reached; delete a profile first");
        return ESP_FAIL;
    }
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
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    char buf[256];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    int cone_id = CONE_04;
    int speed = CONE_SPEED_MEDIUM;
    bool preheat = false;
    bool slow_cool = false;
    bool save_profile = true;

    cJSON *j;
    j = cJSON_GetObjectItem(root, "coneId");
    if (j) {
        cone_id = (int)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "speed");
    if (j) {
        speed = (int)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "preheat");
    if (j) {
        preheat = cJSON_IsTrue(j);
    }
    j = cJSON_GetObjectItem(root, "slowCool");
    if (j) {
        slow_cool = cJSON_IsTrue(j);
    }
    j = cJSON_GetObjectItem(root, "save");
    if (j) {
        save_profile = cJSON_IsTrue(j);
    }
    cJSON_Delete(root);

    if (cone_id < 0 || cone_id >= CONE_COUNT) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid coneId");
        return ESP_FAIL;
    }
    /* Mirror the coneId check: a bad speed is a client error, so report it as
       400 rather than letting it fall through to cone_fire_generate's own
       guard and surface as a 500. */
    if (speed < CONE_SPEED_SLOW || speed > CONE_SPEED_FAST) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid speed");
        return ESP_FAIL;
    }

    firing_profile_t profile;
    esp_err_t err = cone_fire_generate((cone_id_t)cone_id, (cone_speed_t)speed, preheat, slow_cool, &profile);
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to generate profile");
        return ESP_FAIL;
    }

    if (save_profile) {
        firing_engine_save_profile(&profile);
    }

    return send_json(req, build_profile_json(&profile));
}

/* ── GET /api/v1/history ───────────────────────────── */

static esp_err_t handle_get_history(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    history_record_t records[HISTORY_MAX_RECORDS];
    int count = history_get_records(records, HISTORY_MAX_RECORDS);

    cJSON *arr = cJSON_CreateArray();
    for (int i = 0; i < count; i++) {
        cJSON_AddItemToArray(arr, build_history_record_json(&records[i]));
    }
    return send_json(req, arr);
}

/* ── GET /api/v1/history/:id/trace ────────────────── */

static esp_err_t handle_get_history_trace(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    /* Extract record ID from URI */
    const char *prefix = "/api/v1/history/";
    const char *id_start = req->uri + strlen(prefix);
    uint32_t record_id = (uint32_t)atoi(id_start);

    FILE *f = history_open_trace(record_id);
    if (!f) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Trace not found");
        return ESP_FAIL;
    }

    char disp[64];
    snprintf(disp, sizeof(disp), "attachment; filename=\"trace_%" PRIu32 ".csv\"", record_id);
    httpd_resp_set_hdr(req, "Content-Disposition", disp);
    httpd_resp_set_type(req, "text/csv");

    /* Stream the CSV in 1 KB chunks to avoid a large transient heap buffer. */
    char buf[1024];
    size_t read_bytes;
    while ((read_bytes = fread(buf, 1, sizeof(buf), f)) > 0) {
        if (httpd_resp_send_chunk(req, buf, read_bytes) != ESP_OK) {
            fclose(f);
            httpd_resp_send_chunk(req, NULL, 0);
            return ESP_FAIL;
        }
    }
    fclose(f);
    httpd_resp_send_chunk(req, NULL, 0);
    return ESP_OK;
}

/* ── OTA firmware update ───────────────────────────── */

/*
 * Refuse firmware updates while a firing is active — an OTA reboots the
 * controller. Sends a 409 response and returns true if blocked.
 */
static bool ota_blocked_by_firing(httpd_req_t *req)
{
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    if (prog.is_active) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Cannot update firmware during a firing");
        return true;
    }
    /* A relay diagnostic holds the SSR on but reports is_active == false, so it
       must be checked separately: a reboot mid-pulse would leave the SSR in an
       undefined state, and an OTA install reboots on completion. */
    if (firing_engine_relay_test_active()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Cannot update firmware during a relay test");
        return true;
    }
    return false;
}

static esp_err_t handle_ota_upload(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    if (ota_blocked_by_firing(req)) {
        return ESP_FAIL;
    }
    /* Claim the OTA-busy flag for the whole upload. This both rejects a
       concurrent manifest install and (because firing-start checks
       ota_is_busy()) blocks a firing from starting mid-upload — the upload
       reboots the controller when it finishes. */
    if (!ota_busy_acquire()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "An OTA operation is already in progress");
        return ESP_FAIL;
    }

    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (!update_partition) {
        ota_busy_release();
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "No update partition available");
        return ESP_FAIL;
    }

    esp_ota_handle_t ota_handle = 0;
    esp_err_t err = esp_ota_begin(update_partition, OTA_WITH_SEQUENTIAL_WRITES, &ota_handle);
    if (err != ESP_OK) {
        ota_busy_release();
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "OTA begin failed");
        return ESP_FAIL;
    }

    char *buf = malloc(4096);
    if (!buf) {
        esp_ota_abort(ota_handle);
        ota_busy_release();
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Out of memory");
        return ESP_FAIL;
    }

    int remaining = req->content_len;
    bool ota_ok = true;
    while (remaining > 0 && ota_ok) {
        int to_recv = (remaining > 4096) ? 4096 : remaining;
        int received = httpd_req_recv(req, buf, to_recv);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
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

    /* On any write/recv failure, abort to release the OTA handle (esp_ota_end
       is only valid on a fully-written image). esp_ota_end frees the handle on
       both success and failure. */
    if (!ota_ok) {
        esp_ota_abort(ota_handle);
        ota_busy_release();
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "OTA write failed");
        return ESP_FAIL;
    }
    if (esp_ota_end(ota_handle) != ESP_OK) {
        ota_busy_release();
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "OTA image verification failed");
        return ESP_FAIL;
    }

    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        ota_busy_release();
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

/* POST /api/v1/ota/check — fetch the release manifest, compare versions. */
static esp_err_t handle_ota_check(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    if (ota_blocked_by_firing(req)) {
        return ESP_FAIL;
    }
    if (ota_is_busy()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "An OTA operation is already in progress");
        return ESP_FAIL;
    }

    ota_manifest_t manifest;
    if (ota_check(&manifest) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Could not fetch update manifest");
        return ESP_FAIL;
    }

    return send_json(req, build_ota_check_json(ota_current_version(), &manifest));
}

/* POST /api/v1/ota/install — fetch latest manifest, then install in background. */
static esp_err_t handle_ota_install(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    if (ota_blocked_by_firing(req)) {
        return ESP_FAIL;
    }
    if (ota_is_busy()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "An OTA operation is already in progress");
        return ESP_FAIL;
    }

    ota_manifest_t manifest;
    if (ota_check(&manifest) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Could not fetch update manifest");
        return ESP_FAIL;
    }
    if (strcmp(ota_current_version(), manifest.version) == 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Already on the latest version");
        return ESP_FAIL;
    }
    if (ota_install_from_manifest(&manifest) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Could not start update");
        return ESP_FAIL;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "version", manifest.version);
    cJSON_AddStringToObject(resp, "message", "Update started. Watch progress over WebSocket.");
    return send_json(req, resp);
}

/* ── POST /api/v1/diagnostics/relay ───────────────── */

static esp_err_t handle_diag_relay(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    char buf[64];
    int duration_s = 2; /* default 2 seconds */
    if (read_body(req, buf, sizeof(buf)) > 0) {
        cJSON *root = cJSON_Parse(buf);
        if (root) {
            cJSON *j = cJSON_GetObjectItem(root, "durationSeconds");
            if (j) {
                duration_s = (int)j->valuedouble;
            }
            cJSON_Delete(root);
        }
    }
    if (duration_s < 1) {
        duration_s = 1;
    }
    if (duration_s > 10) {
        duration_s = 10;
    }

    /* The firing engine owns the pulse and re-asserts the SSR every tick (a
       single set-and-sleep here would block this worker and, worse, let the
       safety task's 3-second heartbeat trip on any test over 3 s). OTA is
       checked here since the engine's arm path does not. */
    if (ota_is_busy()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Firmware update in progress");
        return ESP_FAIL;
    }

    /* Arm synchronously so we can report a real result: firing_engine_relay_
       test_arm() atomically rejects if a firing/delay/autotune or another test
       is active. This avoids the queue-latency window where a firing-start or
       reboot could slip past an is_active/relay check before the pulse began. */
    if (!firing_engine_relay_test_arm((uint32_t)duration_s)) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_sendstr(req, "Kiln busy: a firing or relay test is already active");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "Relay test armed: %d seconds", duration_s);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddNumberToObject(resp, "durationSeconds", duration_s);
    return send_json(req, resp);
}

/* ── GET /api/v1/diagnostics/thermocouple ─────────── */

static esp_err_t handle_diag_thermocouple(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    thermocouple_reading_t tc;
    thermocouple_get_latest(&tc);

    int64_t now_us = esp_timer_get_time();
    int64_t age_ms = (tc.timestamp_us > 0) ? ((now_us - tc.timestamp_us) / 1000) : -1;

    kiln_settings_t settings;
    firing_engine_get_settings(&settings);

    return send_json(req, build_thermocouple_diag_json(&tc, age_ms, settings.tc_offset_c));
}

/* ── GET /api/v1/cone-table ────────────────────────── */

static esp_err_t handle_get_cone_table(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    return send_json(req, build_cone_table_json());
}

/* ── POST /api/v1/autotune/start ───────────────────── */

static esp_err_t handle_autotune_start(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    if (firing_blocked_by_ota(req)) {
        return ESP_FAIL;
    }
    char buf[128];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    float setpoint = 500.0f, hysteresis = 5.0f;
    cJSON *j = cJSON_GetObjectItem(root, "setpoint");
    if (j) {
        setpoint = (float)j->valuedouble;
    }
    j = cJSON_GetObjectItem(root, "hysteresis");
    if (j) {
        hysteresis = (float)j->valuedouble;
    }
    cJSON_Delete(root);

    /* Reject non-finite / non-positive inputs before the range check: `NaN >
       max` is false, so a null/malformed JSON value would otherwise slip
       through to the engine. Mirrors validate_profile's isfinite() checks. */
    if (!isfinite(setpoint) || setpoint <= 0.0f || !isfinite(hysteresis) || hysteresis <= 0.0f) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid setpoint or hysteresis");
        return ESP_FAIL;
    }
    /* Validate against max safe temp */
    if (setpoint > safety_get_max_temp()) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Setpoint exceeds max safe temp");
        return ESP_FAIL;
    }

    /* Reject if a firing (or armed delay) is already active, mirroring
       handle_firing_start. The engine enforces this too, but rejecting here
       gives the caller a 409 instead of an "ok" for a command that will be
       dropped on arrival. */
    firing_progress_t prog;
    firing_engine_get_progress(&prog);
    if (prog.is_active) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_send(req, "Firing already active", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }
    if (firing_engine_relay_test_active()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_send(req, "Relay test in progress", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }

    firing_cmd_t cmd = {.type = FIRING_CMD_AUTOTUNE_START};
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
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    firing_cmd_t cmd = {.type = FIRING_CMD_AUTOTUNE_STOP};
    xQueueSend(firing_engine_get_cmd_queue(), &cmd, pdMS_TO_TICKS(100));

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    return send_json(req, resp);
}

/* ── GET /api/v1/autotune/status ───────────────────── */

static esp_err_t handle_autotune_status(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    /* The progress status reports a *running* tune; the terminal outcome has to
       come from the engine's autotune state, since the engine stops the firing
       the moment a tune ends and the status is back to IDLE by now (#216). */
    firing_progress_t prog;
    autotune_state_t at_state;
    firing_engine_get_autotune_snapshot(&prog, &at_state);

    /* The live gains, not a re-read of NVS: a tune that has just finished has
       already applied its result to the running controller, and a manual edit
       (POST /pid) writes both. Reading the engine keeps this endpoint and
       GET /pid from ever disagreeing. */
    float kp, ki, kd;
    firing_engine_get_pid_gains(&kp, &ki, &kd);
    return send_json(req, build_autotune_status_json(&prog, at_state, kp, ki, kd));
}

/* ── GET /api/v1/pid ───────────────────────────────── */

static esp_err_t handle_get_pid(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    float kp, ki, kd;
    firing_engine_get_pid_gains(&kp, &ki, &kd);
    return send_json(req, build_pid_json(kp, ki, kd));
}

/* ── POST /api/v1/pid ──────────────────────────────── */

/* Read one gain out of the body. Unlike POST /settings, which leans on cJSON's
   valuedouble defaulting to 0 for anything non-numeric, every field here is
   required and type-checked: a typo'd key or a JSON null would otherwise be
   read as a gain of 0, and {0,0,0} is a controller that never heats. */
static bool read_gain(cJSON *root, const char *key, float *out)
{
    cJSON *j = cJSON_GetObjectItem(root, key);
    if (!cJSON_IsNumber(j)) {
        return false;
    }
    *out = (float)j->valuedouble;
    return true;
}

static esp_err_t handle_post_pid(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    char buf[128];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    float kp, ki, kd;
    bool complete = read_gain(root, "kp", &kp) && read_gain(root, "ki", &ki) && read_gain(root, "kd", &kd);
    cJSON_Delete(root);

    if (!complete) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "kp, ki and kd are all required and must be numbers");
        return ESP_FAIL;
    }

    esp_err_t err = firing_engine_set_pid_gains(kp, ki, kd);
    if (err == ESP_ERR_INVALID_ARG) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST,
                            "Gains must be within the published limits, and Kp or Ki must be above zero");
        return ESP_FAIL;
    }
    if (err == ESP_ERR_INVALID_STATE) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "text/plain");
        httpd_resp_send(req, "Kiln is busy: stop the firing or auto-tune first", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }
    if (err != ESP_OK) {
        /* Applied to the live controller but not written to flash — saying "ok"
           here would promise the gains survive a reboot. */
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Gains applied but could not be saved");
        return ESP_FAIL;
    }

    /* Echo the stored gains so a client shows what the controller kept, not
       what it sent — NVS round-trips each gain through an int32 x10000, so a
       value with more precision than that comes back rounded. */
    firing_engine_get_pid_gains(&kp, &ki, &kd);
    return send_json(req, build_pid_json(kp, ki, kd));
}

/* ── GET /api/v1/ota/status ───────────────────────── */

static const char *ota_state_to_string(esp_ota_img_states_t state)
{
    switch (state) {
    case ESP_OTA_IMG_NEW:
        return "new";
    case ESP_OTA_IMG_PENDING_VERIFY:
        return "pending_verify";
    case ESP_OTA_IMG_VALID:
        return "valid";
    case ESP_OTA_IMG_INVALID:
        return "invalid";
    case ESP_OTA_IMG_ABORTED:
        return "aborted";
    case ESP_OTA_IMG_UNDEFINED:
        return "undefined";
    default:
        return "unknown";
    }
}

static esp_err_t handle_ota_status(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_partition_t *next = esp_ota_get_next_update_partition(NULL);
    const esp_partition_t *boot = esp_ota_get_boot_partition();

    /* app_desc must outlive the builder call — it owns the strings the struct
       below points at, so it cannot be scoped to the `if` that fills it. */
    esp_app_desc_t app_desc = {0};
    ota_status_json_t info = {
        .rollback_available = esp_ota_check_rollback_is_possible(),
        .boot_partition = boot ? boot->label : NULL,
    };

    if (running) {
        info.running_label = running->label;
        info.running_address = running->address;
        info.running_size = running->size;

        esp_ota_img_states_t state;
        if (esp_ota_get_state_partition(running, &state) == ESP_OK) {
            info.running_state = ota_state_to_string(state);
            info.pending_verify = (state == ESP_OTA_IMG_PENDING_VERIFY);
        }

        if (esp_ota_get_partition_description(running, &app_desc) == ESP_OK) {
            info.running_version = app_desc.version;
            info.running_date = app_desc.date;
            info.running_time = app_desc.time;
            info.running_idf_version = app_desc.idf_ver;
        }
    }

    if (next) {
        info.next_label = next->label;
        info.next_size = next->size;
    }

    return send_json(req, build_ota_status_json(&info));
}

/* ── POST /api/v1/ota/rollback ────────────────────── */

static esp_err_t handle_ota_rollback(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    if (ota_blocked_by_firing(req)) {
        return ESP_FAIL;
    }

    if (!esp_ota_check_rollback_is_possible()) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Rollback not available");
        return ESP_FAIL;
    }

    esp_err_t err = esp_ota_mark_app_invalid_rollback_and_reboot();
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Rollback failed");
        return ESP_FAIL;
    }

    /* Won't reach here — device reboots */
    return ESP_OK;
}

/* ── POST /api/v1/ota/confirm ─────────────────────── */

static esp_err_t handle_ota_confirm(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (esp_ota_get_state_partition(running, &state) == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY) {
        esp_ota_mark_app_valid_cancel_rollback();
        cJSON *resp = cJSON_CreateObject();
        cJSON_AddBoolToObject(resp, "ok", true);
        cJSON_AddStringToObject(resp, "message", "Firmware confirmed as valid");
        return send_json(req, resp);
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "message", "Firmware already confirmed");
    return send_json(req, resp);
}

/* ── GET /api/v1/wifi ─────────────────────────────── */

static esp_err_t handle_get_wifi(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    char ssid[WIFI_SSID_BUF_LEN] = {0};
    char pass[WIFI_PASS_BUF_LEN] = {0};
    if (wifi_manager_load_creds(ssid, sizeof(ssid), pass, sizeof(pass)) != ESP_OK) {
        ssid[0] = '\0';
    }

    return send_json(req, build_wifi_status_json(wifi_manager_is_connected(), wifi_manager_is_ap_mode(),
                                                 wifi_manager_get_ip(), ssid));
}

/* ── POST /api/v1/wifi ────────────────────────────── */

static esp_err_t handle_post_wifi(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    char buf[256];
    cJSON *root = parse_body_json(req, buf, sizeof(buf));
    if (!root) {
        return ESP_FAIL;
    }

    const cJSON *j_ssid = cJSON_GetObjectItem(root, "ssid");
    if (!j_ssid || !j_ssid->valuestring || j_ssid->valuestring[0] == '\0') {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing ssid");
        return ESP_FAIL;
    }

    const char *ssid = j_ssid->valuestring;
    const cJSON *j_pass = cJSON_GetObjectItem(root, "password");
    const char *pass = (j_pass && j_pass->valuestring) ? j_pass->valuestring : "";

    /* Over-length credentials used to save "successfully" and then fail to load
     * on the next boot, dropping the device into AP mode with no error ever
     * shown (#134). Reject them here so the user finds out at save time. */
    if (strlen(ssid) > WIFI_SSID_MAX_LEN) {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "SSID too long (max 32 characters)");
        return ESP_FAIL;
    }
    if (strlen(pass) > WIFI_PASS_MAX_LEN) {
        cJSON_Delete(root);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Password too long (max 64 characters)");
        return ESP_FAIL;
    }

    esp_err_t err = wifi_manager_save_creds(ssid, pass);
    cJSON_Delete(root);

    if (err == ESP_ERR_INVALID_SIZE) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Credentials too long");
        return ESP_FAIL;
    }
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to save credentials");
        return ESP_FAIL;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "message", "Wi-Fi credentials saved. Reboot to connect.");
    return send_json(req, resp);
}

/* ── DELETE /api/v1/wifi ──────────────────────────── */

static esp_err_t handle_delete_wifi(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }

    wifi_manager_clear_creds();

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "message", "Wi-Fi credentials cleared. Will start in AP mode after reboot.");
    return send_json(req, resp);
}

/* ── POST /api/v1/reboot ──────────────────────────── */

/*
 * Restart the controller. Used after saving Wi-Fi credentials so the device
 * reconnects with the new network without a manual power cycle. Blocked
 * during a firing (a reboot would drop kiln control), mirroring OTA. The
 * response is flushed before the short delay + esp_restart() so the client
 * sees the ack.
 */
static esp_err_t handle_reboot(httpd_req_t *req)
{
    if (!require_auth(req)) {
        return ESP_FAIL;
    }
    if (ota_blocked_by_firing(req)) {
        return ESP_FAIL;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "ok", true);
    cJSON_AddStringToObject(resp, "message", "Rebooting...");
    send_json(req, resp);

    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

/* ── Register All Handlers ─────────────────────────── */

/* Counts successful registrations so the summary log can't drift from the
   actual endpoint count. `registered` is declared in api_handlers_register(). */
#define REGISTER_API(path, http_method, fn)                                                    \
    do {                                                                                       \
        /* NOLINTNEXTLINE(bugprone-macro-parentheses) -- struct init, parens not needed */     \
        httpd_uri_t u = {.uri = path, .method = http_method, .handler = fn, .user_ctx = NULL}; \
        esp_err_t e = httpd_register_uri_handler(server, &u);                                  \
        if (e != ESP_OK)                                                                       \
            ESP_LOGW(TAG, "Failed to register %s: %s", path, esp_err_to_name(e));              \
        else                                                                                   \
            registered++;                                                                      \
    } while (0)

esp_err_t api_handlers_register(httpd_handle_t server)
{
    /* Init internal temperature sensor */
    temperature_sensor_config_t temp_config = TEMPERATURE_SENSOR_CONFIG_DEFAULT(10, 50);
    if (temperature_sensor_install(&temp_config, &s_board_temp_handle) == ESP_OK) {
        temperature_sensor_enable(s_board_temp_handle);
        ESP_LOGI(TAG, "Board temperature sensor initialized");
    } else {
        ESP_LOGW(TAG, "Failed to init board temperature sensor");
        s_board_temp_handle = NULL;
    }

    int registered = 0;

    /* Core endpoints */
    REGISTER_API("/api/v1/status", HTTP_GET, handle_get_status);
    REGISTER_API("/api/v1/profiles", HTTP_GET, handle_get_profiles);
    REGISTER_API("/api/v1/profiles", HTTP_POST, handle_post_profile);
    REGISTER_API("/api/v1/profiles/import", HTTP_POST, handle_profile_import);
    REGISTER_API("/api/v1/profiles/cone-fire", HTTP_POST, handle_cone_fire);
    REGISTER_API("/api/v1/profiles/*", HTTP_GET, handle_get_profile);
    REGISTER_API("/api/v1/profiles/*", HTTP_DELETE, handle_delete_profile);

    /* Firing control */
    REGISTER_API("/api/v1/firing/start", HTTP_POST, handle_firing_start);
    REGISTER_API("/api/v1/firing/stop", HTTP_POST, handle_firing_stop);
    REGISTER_API("/api/v1/firing/pause", HTTP_POST, handle_firing_pause);
    REGISTER_API("/api/v1/firing/skip-segment", HTTP_POST, handle_firing_skip_segment);

    /* Settings + system */
    REGISTER_API("/api/v1/settings", HTTP_GET, handle_get_settings);
    REGISTER_API("/api/v1/settings", HTTP_POST, handle_post_settings);
    REGISTER_API("/api/v1/system", HTTP_GET, handle_get_system);

    /* Auto-tune */
    REGISTER_API("/api/v1/autotune/start", HTTP_POST, handle_autotune_start);
    REGISTER_API("/api/v1/autotune/stop", HTTP_POST, handle_autotune_stop);
    REGISTER_API("/api/v1/autotune/status", HTTP_GET, handle_autotune_status);

    /* PID gains — the manual alternative to running a tune */
    REGISTER_API("/api/v1/pid", HTTP_GET, handle_get_pid);
    REGISTER_API("/api/v1/pid", HTTP_POST, handle_post_pid);

    /* Cone table */
    REGISTER_API("/api/v1/cone-table", HTTP_GET, handle_get_cone_table);

    /* Firing history */
    REGISTER_API("/api/v1/history", HTTP_GET, handle_get_history);
    REGISTER_API("/api/v1/history/*", HTTP_GET, handle_get_history_trace);

    /* OTA */
    REGISTER_API("/api/v1/ota", HTTP_POST, handle_ota_upload);
    REGISTER_API("/api/v1/ota/check", HTTP_POST, handle_ota_check);
    REGISTER_API("/api/v1/ota/install", HTTP_POST, handle_ota_install);
    REGISTER_API("/api/v1/ota/status", HTTP_GET, handle_ota_status);
    REGISTER_API("/api/v1/ota/rollback", HTTP_POST, handle_ota_rollback);
    REGISTER_API("/api/v1/ota/confirm", HTTP_POST, handle_ota_confirm);

    /* Diagnostics */
    REGISTER_API("/api/v1/diagnostics/relay", HTTP_POST, handle_diag_relay);
    REGISTER_API("/api/v1/diagnostics/thermocouple", HTTP_GET, handle_diag_thermocouple);

    /* Wi-Fi configuration */
    REGISTER_API("/api/v1/wifi", HTTP_GET, handle_get_wifi);
    REGISTER_API("/api/v1/wifi", HTTP_POST, handle_post_wifi);
    REGISTER_API("/api/v1/wifi", HTTP_DELETE, handle_delete_wifi);
    REGISTER_API("/api/v1/reboot", HTTP_POST, handle_reboot);

    ESP_LOGI(TAG, "API handlers registered (%d endpoints)", registered);
    return ESP_OK;
}
