#pragma once

#include "firing_types.h"
#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Orton cone target temperatures (°C) for standard pyrometric cones.
 * Three columns: slow (60°C/hr), medium (150°C/hr), fast (300°C/hr).
 * Source: Orton Ceramic Foundation published cone-temperature tables.
 */

typedef enum {
    CONE_022 = 0,
    CONE_021,
    CONE_020,
    CONE_019,
    CONE_018,
    CONE_017,
    CONE_016,
    CONE_015,
    CONE_014,
    CONE_013,
    CONE_012,
    CONE_011,
    CONE_010,
    CONE_09,
    CONE_08,
    CONE_07,
    CONE_06,
    CONE_05_5,
    CONE_05,
    CONE_04,
    CONE_03,
    CONE_02,
    CONE_01,
    CONE_1,
    CONE_2,
    CONE_3,
    CONE_4,
    CONE_5,
    CONE_6,
    CONE_7,
    CONE_8,
    CONE_9,
    CONE_10,
    CONE_11,
    CONE_12,
    CONE_13,
    CONE_14,
    CONE_COUNT,
} cone_id_t;

typedef enum {
    CONE_SPEED_SLOW   = 0,  /* 60°C/hr final segment */
    CONE_SPEED_MEDIUM = 1,  /* 150°C/hr final segment */
    CONE_SPEED_FAST   = 2,  /* 300°C/hr final segment */
} cone_speed_t;

/** Return the display name for a cone (e.g. "022", "04", "6"). */
const char *cone_name(cone_id_t cone);

/** Return the target temperature in °C for a cone + speed combination. */
float cone_target_temp_c(cone_id_t cone, cone_speed_t speed);

/**
 * Generate a ramp/hold firing profile for a given cone + speed.
 *
 * The generated profile contains:
 *   Seg 0 (optional): 80°C/hr preheat to 120°C, hold 30 min (if preheat=true)
 *   Seg N-1: 60°C/hr water-smoke through 573°C quartz inversion
 *   Seg N:   speed-dependent ramp to cone target
 *   Seg N+1 (optional): slow cool through 573°C at 50°C/hr (if slow_cool=true)
 *
 * @param cone        Target cone id.
 * @param speed       Firing speed (slow/medium/fast).
 * @param preheat     Add preheat segment at 120°C.
 * @param slow_cool   Add slow-cool through 573°C on the way down.
 * @param out_profile Caller-provided buffer for the resulting profile.
 */
esp_err_t cone_fire_generate(cone_id_t cone, cone_speed_t speed,
                              bool preheat, bool slow_cool,
                              firing_profile_t *out_profile);

#ifdef __cplusplus
}
#endif
