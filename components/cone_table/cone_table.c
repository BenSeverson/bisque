#include "cone_table.h"
#include "esp_log.h"
#include <string.h>
#include <stdio.h>
#include <math.h>

static const char *TAG = "cone_table";

/* ── Orton Cone Temperature Table ───────────────────────────────────────────
 * Columns: [slow 60°C/hr, medium 150°C/hr, fast 300°C/hr]
 * Source: Orton Ceramic Foundation published data.
 * ───────────────────────────────────────────────────────────────────────── */
typedef struct {
    const char *name;
    float temp_c[3];   /* slow, medium, fast */
} cone_entry_t;

static const cone_entry_t s_cone_table[CONE_COUNT] = {
    [CONE_022]  = { "022",  { 586,  590,  605  } },
    [CONE_021]  = { "021",  { 600,  605,  616  } },
    [CONE_020]  = { "020",  { 626,  634,  638  } },
    [CONE_019]  = { "019",  { 656,  671,  678  } },
    [CONE_018]  = { "018",  { 686,  698,  715  } },
    [CONE_017]  = { "017",  { 704,  715,  736  } },
    [CONE_016]  = { "016",  { 742,  748,  769  } },
    [CONE_015]  = { "015",  { 751,  764,  788  } },
    [CONE_014]  = { "014",  { 757,  762,  807  } },
    [CONE_013]  = { "013",  { 807,  815,  837  } },
    [CONE_012]  = { "012",  { 843,  853,  861  } },
    [CONE_011]  = { "011",  { 857,  867,  875  } },
    [CONE_010]  = { "010",  { 891,  894,  903  } },
    [CONE_09]   = { "09",   { 917,  923,  928  } },
    [CONE_08]   = { "08",   { 945,  955,  983  } },
    [CONE_07]   = { "07",   { 973,  984,  1008 } },
    [CONE_06]   = { "06",   { 991,  999,  1023 } },
    [CONE_05_5] = { "05.5", { 1011, 1020, 1043 } },
    [CONE_05]   = { "05",   { 1031, 1046, 1066 } },
    [CONE_04]   = { "04",   { 1050, 1060, 1083 } },
    [CONE_03]   = { "03",   { 1086, 1101, 1115 } },
    [CONE_02]   = { "02",   { 1101, 1120, 1138 } },
    [CONE_01]   = { "01",   { 1117, 1137, 1154 } },
    [CONE_1]    = { "1",    { 1136, 1154, 1162 } },
    [CONE_2]    = { "2",    { 1142, 1162, 1173 } },
    [CONE_3]    = { "3",    { 1152, 1168, 1181 } },
    [CONE_4]    = { "4",    { 1162, 1182, 1196 } },
    [CONE_5]    = { "5",    { 1177, 1196, 1207 } },
    [CONE_6]    = { "6",    { 1201, 1222, 1240 } },
    [CONE_7]    = { "7",    { 1215, 1239, 1255 } },
    [CONE_8]    = { "8",    { 1236, 1252, 1274 } },
    [CONE_9]    = { "9",    { 1260, 1280, 1285 } },
    [CONE_10]   = { "10",   { 1285, 1305, 1315 } },
    [CONE_11]   = { "11",   { 1294, 1315, 1326 } },
    [CONE_12]   = { "12",   { 1306, 1326, 1355 } },
    [CONE_13]   = { "13",   { 1321, 1348, 1380 } },
    [CONE_14]   = { "14",   { 1388, 1395, 1410 } },
};

/* Ramp rates for each speed in °C/hr for the final high-temperature segment */
static const float s_speed_ramp[3] = {
    [CONE_SPEED_SLOW]   = 60.0f,
    [CONE_SPEED_MEDIUM] = 150.0f,
    [CONE_SPEED_FAST]   = 300.0f,
};

static const char *s_speed_names[3] = {
    [CONE_SPEED_SLOW]   = "Slow",
    [CONE_SPEED_MEDIUM] = "Medium",
    [CONE_SPEED_FAST]   = "Fast",
};

/* ── Public API ────────────────────────────────────────────────────────── */

const char *cone_name(cone_id_t cone)
{
    if (cone < 0 || cone >= CONE_COUNT) return "??";
    return s_cone_table[cone].name;
}

float cone_target_temp_c(cone_id_t cone, cone_speed_t speed)
{
    if (cone < 0 || cone >= CONE_COUNT) return 0.0f;
    if (speed < 0 || speed > 2) speed = CONE_SPEED_MEDIUM;
    return s_cone_table[cone].temp_c[speed];
}

esp_err_t cone_fire_generate(cone_id_t cone, cone_speed_t speed,
                              bool preheat, bool slow_cool,
                              firing_profile_t *out_profile)
{
    if (!out_profile || cone < 0 || cone >= CONE_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out_profile, 0, sizeof(*out_profile));

    float target_temp = cone_target_temp_c(cone, speed);
    float ramp_rate   = s_speed_ramp[speed];

    /* Build profile ID: "cone-<name>-<speed>" */
    snprintf(out_profile->id, FIRING_ID_LEN, "cone-%s-%s",
             s_cone_table[cone].name, s_speed_names[speed]);

    /* Replace dots/spaces with dashes for NVS key safety */
    for (char *p = out_profile->id; *p; p++) {
        if (*p == '.' || *p == ' ') *p = '-';
    }

    snprintf(out_profile->name, FIRING_NAME_LEN, "Cone %s (%s)",
             s_cone_table[cone].name, s_speed_names[speed]);

    snprintf(out_profile->description, FIRING_DESC_LEN,
             "Orton cone %s at %s speed (%.0f°C/hr). Target: %.0f°C.",
             s_cone_table[cone].name, s_speed_names[speed], ramp_rate, target_temp);

    int seg = 0;

    /* ── Segment 0: Optional preheat at 120°C ─────────────────────────── */
    if (preheat) {
        snprintf(out_profile->segments[seg].id, FIRING_ID_LEN, "%d", seg + 1);
        snprintf(out_profile->segments[seg].name, FIRING_NAME_LEN, "Preheat");
        out_profile->segments[seg].ramp_rate   = 80.0f;
        out_profile->segments[seg].target_temp = 120.0f;
        out_profile->segments[seg].hold_time   = 30;
        seg++;
    }

    /* ── Segment 1: Slow ramp through water-smoke / quartz zones ──────── */
    /* Ramp at 60°C/hr from preheat temp (or room) to 573°C quartz inversion */
    {
        snprintf(out_profile->segments[seg].id, FIRING_ID_LEN, "%d", seg + 1);
        snprintf(out_profile->segments[seg].name, FIRING_NAME_LEN, "Water smoke");
        out_profile->segments[seg].ramp_rate   = 60.0f;
        out_profile->segments[seg].target_temp = 220.0f;
        out_profile->segments[seg].hold_time   = 0;
        seg++;

        snprintf(out_profile->segments[seg].id, FIRING_ID_LEN, "%d", seg + 1);
        snprintf(out_profile->segments[seg].name, FIRING_NAME_LEN, "Quartz zone");
        out_profile->segments[seg].ramp_rate   = 100.0f;
        out_profile->segments[seg].target_temp = 600.0f;
        out_profile->segments[seg].hold_time   = 0;
        seg++;
    }

    /* ── Segment 2: Speed-dependent ramp to cone target ─────────────────── */
    {
        snprintf(out_profile->segments[seg].id, FIRING_ID_LEN, "%d", seg + 1);
        snprintf(out_profile->segments[seg].name, FIRING_NAME_LEN, "Ramp to cone %s",
                 s_cone_table[cone].name);
        out_profile->segments[seg].ramp_rate   = ramp_rate;
        out_profile->segments[seg].target_temp = target_temp;
        out_profile->segments[seg].hold_time   = 10;  /* 10-min soak at peak */
        seg++;
    }

    /* ── Segment 3: Optional slow-cool through quartz inversion ──────────── */
    if (slow_cool && target_temp > 650.0f) {
        /* Cool normally to 650°C */
        snprintf(out_profile->segments[seg].id, FIRING_ID_LEN, "%d", seg + 1);
        snprintf(out_profile->segments[seg].name, FIRING_NAME_LEN, "Cool to inversion");
        out_profile->segments[seg].ramp_rate   = -150.0f;
        out_profile->segments[seg].target_temp = 650.0f;
        out_profile->segments[seg].hold_time   = 0;
        seg++;

        /* Slow through quartz inversion (573°C) */
        snprintf(out_profile->segments[seg].id, FIRING_ID_LEN, "%d", seg + 1);
        snprintf(out_profile->segments[seg].name, FIRING_NAME_LEN, "Slow quartz inversion");
        out_profile->segments[seg].ramp_rate   = -50.0f;
        out_profile->segments[seg].target_temp = 500.0f;
        out_profile->segments[seg].hold_time   = 0;
        seg++;
    }

    out_profile->segment_count = seg;
    out_profile->max_temp = target_temp;

    /* Estimate duration */
    float total_min = 0.0f;
    float cur_temp = preheat ? 20.0f : 20.0f;
    for (int i = 0; i < seg; i++) {
        float rate = out_profile->segments[i].ramp_rate;
        float diff = out_profile->segments[i].target_temp - cur_temp;
        if (fabsf(rate) > 0.1f) {
            total_min += fabsf(diff / rate) * 60.0f;
        }
        total_min += out_profile->segments[i].hold_time;
        cur_temp = out_profile->segments[i].target_temp;
    }
    out_profile->estimated_duration = (uint32_t)total_min;

    ESP_LOGI(TAG, "Generated cone %s %s profile: %.0f°C, %d segments, ~%d min",
             s_cone_table[cone].name, s_speed_names[speed],
             target_temp, seg, out_profile->estimated_duration);

    return ESP_OK;
}
