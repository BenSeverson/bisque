#pragma once

/**
 * State of the lid/door interlock switch, as reported to the UIs.
 *
 * Deliberately standalone — no esp_err.h, no FreeRTOS — so the three consumers
 * can share one type without dragging the safety driver's dependencies along:
 * the pure JSON builders in web_server/api_json.c (host-buildable by contract),
 * the LVGL dashboard (which the SDL simulator compiles with no ESP-IDF at all),
 * and safety.c itself.
 *
 * NOT_FITTED is a distinct state rather than a "closed": the lid GPIO defaults
 * to -1 (see CONFIG_KILN_PIN_LID_SWITCH), so most kilns have no switch at all,
 * and an indicator permanently reading "lid closed" would be reporting on
 * hardware that isn't there. Consumers omit the reading entirely in that case.
 */
typedef enum {
    LID_STATE_NOT_FITTED = -1,
    LID_STATE_CLOSED = 0,
    LID_STATE_OPEN = 1,
} lid_state_t;
