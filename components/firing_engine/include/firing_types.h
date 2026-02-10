#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FIRING_MAX_SEGMENTS   16
#define FIRING_MAX_PROFILES   20
#define FIRING_NAME_LEN       48
#define FIRING_DESC_LEN       128
#define FIRING_ID_LEN         40

/* Matches web_ui/src/app/types/kiln.ts FiringSegment */
typedef struct {
    char    id[FIRING_ID_LEN];
    char    name[FIRING_NAME_LEN];
    float   ramp_rate;       /* °C per hour (positive = heating, negative = cooling) */
    float   target_temp;     /* °C */
    uint16_t hold_time;      /* minutes */
} firing_segment_t;

/* Matches FiringProfile */
typedef struct {
    char    id[FIRING_ID_LEN];
    char    name[FIRING_NAME_LEN];
    char    description[FIRING_DESC_LEN];
    firing_segment_t segments[FIRING_MAX_SEGMENTS];
    uint8_t segment_count;
    float   max_temp;           /* °C — max across all segments */
    uint32_t estimated_duration; /* minutes */
} firing_profile_t;

/* Firing status enum */
typedef enum {
    FIRING_STATUS_IDLE = 0,
    FIRING_STATUS_HEATING,
    FIRING_STATUS_HOLDING,
    FIRING_STATUS_COOLING,
    FIRING_STATUS_COMPLETE,
    FIRING_STATUS_ERROR,
    FIRING_STATUS_PAUSED,
    FIRING_STATUS_AUTOTUNE,
} firing_status_t;

/* Matches FiringProgress (live state) */
typedef struct {
    bool            is_active;
    char            profile_id[FIRING_ID_LEN];
    float           current_temp;
    float           target_temp;
    uint8_t         current_segment;
    uint8_t         total_segments;
    uint32_t        elapsed_time;           /* seconds */
    uint32_t        estimated_remaining;    /* seconds */
    firing_status_t status;
} firing_progress_t;

/* Matches KilnSettings */
typedef struct {
    char    temp_unit;         /* 'C' or 'F' */
    float   max_safe_temp;     /* °C */
    bool    alarm_enabled;
    bool    auto_shutdown;
    bool    notifications_enabled;
} kiln_settings_t;

/* Commands sent from web API to firing_task */
typedef enum {
    FIRING_CMD_START,
    FIRING_CMD_STOP,
    FIRING_CMD_PAUSE,
    FIRING_CMD_RESUME,
    FIRING_CMD_AUTOTUNE_START,
    FIRING_CMD_AUTOTUNE_STOP,
} firing_cmd_type_t;

typedef struct {
    firing_cmd_type_t type;
    union {
        struct {
            firing_profile_t profile;   /* For START */
        } start;
        struct {
            float setpoint;             /* For AUTOTUNE_START */
            float hysteresis;
        } autotune;
    };
} firing_cmd_t;

#ifdef __cplusplus
}
#endif
