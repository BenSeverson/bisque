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
 * web_ui/test/contracts/responseSchemas.ts validates from the frontend side —
 * any drift between this file and the zod schemas is a deliberate API change
 * and should land in the same PR.
 */

#include "cJSON.h"
#include "firing_types.h"
#include "thermocouple.h"
#include "firing_history.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** GET /api/v1/status — firing progress plus thermocouple block. `tc_offset_c`
 *  is applied to the top-level currentTemp so it matches the WebSocket feed; the
 *  nested thermocouple block keeps the raw reading for diagnostics. */
cJSON *build_status_json(const firing_progress_t *prog, const thermocouple_reading_t *tc, float tc_offset_c);

/** GET /api/v1/profiles/:id, POST /api/v1/profiles/cone-fire — one firing profile. */
cJSON *build_profile_json(const firing_profile_t *profile);

/** GET /api/v1/settings — kiln settings; api_token replaced by apiTokenSet bool. */
cJSON *build_settings_json(const kiln_settings_t *settings);

/** GET /api/v1/history element. */
cJSON *build_history_record_json(const history_record_t *rec);

/** GET /api/v1/cone-table — entire cone reference table (no inputs). */
cJSON *build_cone_table_json(void);

/** GET /api/v1/autotune/status. */
cJSON *build_autotune_status_json(const firing_progress_t *prog, float kp, float ki, float kd);

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

#ifdef __cplusplus
}
#endif
