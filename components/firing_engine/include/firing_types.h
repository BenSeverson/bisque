#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FIRING_MAX_SEGMENTS 16
#define FIRING_MAX_PROFILES 20
#define FIRING_NAME_LEN     48
#define FIRING_DESC_LEN     128
#define FIRING_ID_LEN       40

/* Sentinel for hold_time meaning "hold until skip" (operator advances manually).
   0 means no hold (advance immediately on reaching target). */
#define FIRING_HOLD_INDEFINITE 0xFFFF

/* Matches web_ui/src/app/types/kiln.ts FiringSegment */
typedef struct {
    char id[FIRING_ID_LEN];
    char name[FIRING_NAME_LEN];
    float ramp_rate;    /* °C per hour (positive = heating, negative = cooling) */
    float target_temp;  /* °C */
    uint16_t hold_time; /* minutes */
} firing_segment_t;

/* Matches FiringProfile */
typedef struct {
    char id[FIRING_ID_LEN];
    char name[FIRING_NAME_LEN];
    char description[FIRING_DESC_LEN];
    firing_segment_t segments[FIRING_MAX_SEGMENTS];
    uint8_t segment_count;
    float max_temp;              /* °C — max across all segments */
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
    bool is_active;
    char profile_id[FIRING_ID_LEN];
    float current_temp;
    float target_temp;
    uint8_t current_segment;
    uint8_t total_segments;
    uint32_t elapsed_time;        /* seconds */
    uint32_t estimated_remaining; /* seconds */
    /* Seconds until an armed delayed start fires; 0 when none is armed. The
       engine has always known this (delay_start_end_us) but never published it,
       so the UI could show that a firing was scheduled without showing when —
       and confirming *when* is the thing worth checking before leaving a kiln
       unattended overnight (#204). */
    uint32_t delay_remaining;
    firing_status_t status;
} firing_progress_t;

/* Matches KilnSettings */
/* What an open lid does to a running firing. The mechanism is the same in every
 * case — the element is de-energized — and only the program-clock policy
 * differs, which is why this is one setting rather than a build-time fork.
 *
 * PAUSE is the ceramic-kiln convention: opening the lid mid-firing is abnormal,
 * so the program clock stops with the heat and the segment does not run ahead
 * while the kiln sheds temperature.
 *
 * INTERLOCK is the heat-treat / knife-oven convention: opening the door at full
 * temperature is the normal workflow (pull the blade, quench it), so the program
 * must keep running and only the elements cut out.
 */
typedef enum {
    LID_MODE_WARN = 0,  /* report the lid position, take no control action */
    LID_MODE_PAUSE,     /* elements off, program clock held, auto-resume on close */
    LID_MODE_INTERLOCK, /* elements off, program clock keeps running */
} lid_mode_t;

typedef struct {
    char temp_unit;      /* 'C' or 'F' */
    float max_safe_temp; /* °C */
    bool alarm_enabled;
    bool auto_shutdown;
    bool notifications_enabled;
    float tc_offset_c;          /* Thermocouple calibration offset in °C */
    char webhook_url[128];      /* Webhook URL for push notifications (empty = disabled) */
    char api_token[64];         /* API bearer token (empty = auth disabled) */
    float element_watts;        /* Kiln element power for cost estimation */
    float electricity_cost_kwh; /* Electricity cost per kWh */
    lid_mode_t lid_mode;        /* behaviour when the lid switch reads open */
} kiln_settings_t;

/* Commands sent from web API to firing_task */
typedef enum {
    FIRING_CMD_START,
    FIRING_CMD_STOP,
    FIRING_CMD_PAUSE,
    FIRING_CMD_RESUME,
    FIRING_CMD_SKIP_SEGMENT,
    FIRING_CMD_AUTOTUNE_START,
    FIRING_CMD_AUTOTUNE_STOP,
} firing_cmd_type_t;

typedef struct {
    firing_cmd_type_t type;
    union {
        struct {
            firing_profile_t profile; /* For START */
            uint32_t delay_minutes;   /* Delay before firing begins (0 = immediate) */
        } start;
        struct {
            float setpoint; /* For AUTOTUNE_START */
            float hysteresis;
        } autotune;
    };
} firing_cmd_t;

/* Error codes for firing errors */
typedef enum {
    FIRING_ERR_NONE = 0,
    FIRING_ERR_TC_FAULT,        /* Thermocouple fault */
    FIRING_ERR_OVER_TEMP,       /* Over-temperature */
    FIRING_ERR_NOT_RISING,      /* Kiln not rising: <10°C in 15 min while heating */
    FIRING_ERR_RUNAWAY,         /* Rate-of-rise runaway: temp rising >2x programmed rate */
    FIRING_ERR_EMERGENCY_STOP,  /* Emergency stop */
    FIRING_ERR_INVALID_PROFILE, /* Profile unfireable from the actual start temperature */
} firing_error_code_t;

#ifdef __cplusplus
}
#endif
