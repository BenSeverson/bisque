#pragma once

/**
 * State of the downdraft vent relay, as reported to the UIs.
 *
 * Deliberately standalone — no esp_err.h, no FreeRTOS — so the three consumers
 * can share one type without dragging the safety driver's dependencies along:
 * the pure JSON builders in web_server/api_json.c (host-buildable by contract),
 * the LVGL dashboard (which the SDL simulator compiles with no ESP-IDF at all),
 * and safety.c itself.
 *
 * NOT_FITTED is a distinct state rather than an off/false: the vent GPIO
 * defaults to -1 (see CONFIG_KILN_PIN_VENT), so most kilns have no vent relay
 * at all, and an indicator permanently reading "vent off" would be reporting on
 * hardware that isn't there. Consumers omit the reading entirely in that case.
 */
typedef enum {
    VENT_STATE_NOT_FITTED = -1,
    VENT_STATE_OFF = 0,
    VENT_STATE_ON = 1,
} vent_state_t;
