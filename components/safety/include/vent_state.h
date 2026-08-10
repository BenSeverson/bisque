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
 * NOT_FITTED is a distinct state rather than an off/false: a kiln with no vent
 * relay would otherwise show an indicator permanently reading "vent off",
 * reporting on hardware that isn't there. Consumers omit the reading entirely
 * in that case.
 *
 * Note that CONFIG_KILN_PIN_VENT now defaults to GPIO 14 to match the PCB, so
 * NOT_FITTED only appears on builds that explicitly set it back to -1. A build
 * with no vent relay fitted should do exactly that.
 */
typedef enum {
    VENT_STATE_NOT_FITTED = -1,
    VENT_STATE_OFF = 0,
    VENT_STATE_ON = 1,
} vent_state_t;
