#pragma once

/**
 * Pure JSON builders for the REST API responses. Each function takes plain
 * data (no httpd_req_t, no global state) and returns a fresh cJSON object the
 * caller owns. The request handlers in api_handlers.c are thin shims that
 * gather inputs (firing_progress, thermocouple reading, settings, …) and
 * delegate to these builders.
 *
 * Splitting the JSON shape out makes it testable on the host without bringing
 * up esp_http_server, and keeps the response contract in one place.
 *
 * The shape each builder produces is the firmware side of the contract that
 * web_ui/src/app/schemas/api.ts validates from the frontend side — and, since
 * the frontend's response types are inferred from those schemas, the shape the
 * whole web UI is compiled against. Any drift between this file and the zod
 * schemas is a deliberate API change and should land in the same PR.
 */

#include "cJSON.h"
#include "firing_types.h"
#include "ota_manager.h"
#include "pid_control.h"
#include "thermocouple.h"
#include "firing_history.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** GET /api/v1/status — firing progress plus thermocouple block. `tc_offset_c`
 *  is applied to the top-level currentTemp so it matches the WebSocket feed; the
 *  nested thermocouple block keeps the raw reading for diagnostics.
 *  `ssr_duty` is the live element duty (0.0–1.0), from safety_get_ssr_duty(). */
cJSON *build_status_json(const firing_progress_t *prog, const thermocouple_reading_t *tc, float tc_offset_c,
                         float ssr_duty);

/** GET /api/v1/profiles/:id, POST /api/v1/profiles/cone-fire — one firing profile. */
cJSON *build_profile_json(const firing_profile_t *profile);

/** GET /api/v1/settings — kiln settings; api_token replaced by apiTokenSet bool. */
cJSON *build_settings_json(const kiln_settings_t *settings);

/** GET /api/v1/history element. */
cJSON *build_history_record_json(const history_record_t *rec);

/** GET /api/v1/cone-table — entire cone reference table (no inputs). */
cJSON *build_cone_table_json(void);

/**
 * GET /api/v1/autotune/status.
 *
 * `state` is one of running | complete | failed | stopped | idle. The terminal
 * outcomes come from `at_state`, not from `prog`: the engine stops the firing as
 * soon as a tune ends, so by the time the client asks, the progress status has
 * already returned to IDLE. Collapsing them onto "idle" is what made a finished
 * run indistinguishable from one that never started (#216).
 */
cJSON *build_autotune_status_json(const firing_progress_t *prog, autotune_state_t at_state, float kp, float ki,
                                  float kd);

/**
 * GET /api/v1/pid — the live PID gains, plus the compile-time defaults and the
 * accepted range so a client can offer "restore defaults" and validate before
 * POSTing without hardcoding either.
 */
cJSON *build_pid_json(float kp, float ki, float kd);

/**
 * GET /api/v1/diagnostics/thermocouple.
 *
 * @param tc            Latest thermocouple reading.
 * @param age_ms        Age of the reading in milliseconds (-1 if never read).
 * @param tc_offset_c   Calibration offset, added to temperatureAdjustedC.
 */
cJSON *build_thermocouple_diag_json(const thermocouple_reading_t *tc, int64_t age_ms, float tc_offset_c);

/** Convert firing_status_t to its lowercase string for JSON. Lives here so
 * host tests don't need to link web_server.c (which pulls in esp_http_server). */
const char *firing_status_to_string(firing_status_t s);

/* ── WebSocket frames ──────────────────────────────────────────────────────
 *
 * The socket carries the same envelope for every event: {"type":…,"data":{…}}.
 * These builders exist for the same reason the REST ones do — temp_update is
 * the highest-frequency payload in the system and was the least contract-tested
 * of any, because ws_handler.c composed it inline against esp_http_server and
 * so could not be driven from the host (#174).
 */

/**
 * `temp_update` — the periodic telemetry frame.
 *
 * `data` carries exactly the shared progress block that GET /status puts at its
 * top level, so a client can feed both through one parser. `current_temp` is
 * already offset-corrected and zeroed on fault by the caller, matching /status.
 */
cJSON *build_ws_temp_update_json(const firing_progress_t *prog, float current_temp, float ssr_duty);

/**
 * `ota_progress` / `ota_complete` / `ota_error`, chosen by `phase`.
 *
 * Returns NULL for a phase with no wire frame (OTA_PHASE_IDLE and anything
 * unrecognized); the caller sends nothing. `err` is only read for
 * OTA_PHASE_ERROR and may be NULL, in which case a generic message is used —
 * the client always gets a `message` string to show.
 */
cJSON *build_ws_ota_event_json(ota_phase_t phase, int percent, const char *err);

/* ── Device/system endpoints ───────────────────────────────────────────────
 *
 * These used to be built inline in api_handlers.c, which made them invisible to
 * the fixture generator: the frontend's schemas were validated against the
 * mock-server alone, so mock/firmware drift had nothing checking it (#174).
 * They take plain data for the same reason every other builder here does.
 */

/** Inputs to build_system_json — one field per key of GET /api/v1/system. */
typedef struct {
    const char *firmware;
    const char *model;
    double uptime_seconds;
    uint32_t free_heap;
    bool emergency_stop;
    int last_error_code;
    uint32_t element_hours_s;
    float board_temp_c;
    size_t spiffs_total;
    size_t spiffs_used;
} system_info_json_t;

/** GET /api/v1/system — firmware build, uptime, heap, storage, board temp. */
cJSON *build_system_json(const system_info_json_t *info);

/**
 * GET /api/v1/wifi.
 *
 * `saved_ssid` is NULL or empty when no credentials are stored; that is what
 * drives `hasSavedCredentials`, and `savedSsid` is omitted entirely in that
 * case rather than sent empty. The password is never part of the response.
 */
cJSON *build_wifi_status_json(bool connected, bool ap_mode, const char *ip, const char *saved_ssid);

/** POST /api/v1/ota/check — running version against the fetched release manifest. */
cJSON *build_ota_check_json(const char *current_version, const ota_manifest_t *manifest);

/**
 * Inputs to build_ota_status_json.
 *
 * Every optional part of the response is a nullable pointer rather than a
 * separate presence flag: the handler reads each fact from a different esp_ota
 * call, any of which can fail, and NULL means "that call did not answer" — the
 * key is then omitted. `running_state` also gates `pendingVerify`, which the
 * firmware only emits when the partition state was readable.
 */
typedef struct {
    const char *running_label; /* NULL → no "running" object at all */
    uint32_t running_address;
    uint32_t running_size;
    const char *running_state;   /* NULL → omit state and pendingVerify */
    bool pending_verify;         /* only meaningful when running_state != NULL */
    const char *running_version; /* NULL → omit version/date/time/idfVersion */
    const char *running_date;
    const char *running_time;
    const char *running_idf_version;
    const char *next_label; /* NULL → no "nextUpdate" object */
    uint32_t next_size;
    const char *boot_partition; /* NULL → omit bootPartition */
    bool rollback_available;
} ota_status_json_t;

/** GET /api/v1/ota/status — partition layout and rollback availability. */
cJSON *build_ota_status_json(const ota_status_json_t *info);

#ifdef __cplusplus
}
#endif
