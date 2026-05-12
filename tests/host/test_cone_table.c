#include "cone_table.h"
#include "firing_types.h"
#include "unity.h"

#include <stdio.h>
#include <string.h>

void setUp(void)
{
}
void tearDown(void)
{
}

/* ── cone_target_temp_c ─────────────────────────────────────────────────── */

static void test_known_cone_temperatures(void)
{
    /* Spot-check from Orton table. Medium speed values. */
    TEST_ASSERT_EQUAL_FLOAT(1060.0f, cone_target_temp_c(CONE_04, CONE_SPEED_MEDIUM));
    TEST_ASSERT_EQUAL_FLOAT(1222.0f, cone_target_temp_c(CONE_6, CONE_SPEED_MEDIUM));
    TEST_ASSERT_EQUAL_FLOAT(1305.0f, cone_target_temp_c(CONE_10, CONE_SPEED_MEDIUM));
}

static void test_speed_ordering(void)
{
    /* Faster firing → higher cone temperature, for any cone where the speeds
       differ. (A few low-cone entries are equal across speeds.) */
    for (int c = 0; c < CONE_COUNT; c++) {
        float slow = cone_target_temp_c((cone_id_t)c, CONE_SPEED_SLOW);
        float med = cone_target_temp_c((cone_id_t)c, CONE_SPEED_MEDIUM);
        float fast = cone_target_temp_c((cone_id_t)c, CONE_SPEED_FAST);
        TEST_ASSERT_TRUE_MESSAGE(slow <= med, cone_name((cone_id_t)c));
        TEST_ASSERT_TRUE_MESSAGE(med <= fast, cone_name((cone_id_t)c));
    }
}

static void test_out_of_range_returns_zero(void)
{
    TEST_ASSERT_EQUAL_FLOAT(0.0f, cone_target_temp_c((cone_id_t)-1, CONE_SPEED_MEDIUM));
    TEST_ASSERT_EQUAL_FLOAT(0.0f, cone_target_temp_c((cone_id_t)CONE_COUNT, CONE_SPEED_MEDIUM));
}

static void test_invalid_speed_falls_back_to_medium(void)
{
    /* The implementation coerces unknown speeds to MEDIUM. */
    TEST_ASSERT_EQUAL_FLOAT(cone_target_temp_c(CONE_6, CONE_SPEED_MEDIUM),
                            cone_target_temp_c(CONE_6, (cone_speed_t)99));
}

static void test_cone_name_known_values(void)
{
    TEST_ASSERT_EQUAL_STRING("04", cone_name(CONE_04));
    TEST_ASSERT_EQUAL_STRING("6", cone_name(CONE_6));
    TEST_ASSERT_EQUAL_STRING("10", cone_name(CONE_10));
    TEST_ASSERT_EQUAL_STRING("05.5", cone_name(CONE_05_5));
    TEST_ASSERT_EQUAL_STRING("??", cone_name((cone_id_t)-1));
}

/* ── cone_fire_generate ─────────────────────────────────────────────────── */

static void assert_profile_invariants(const firing_profile_t *p, cone_id_t cone, cone_speed_t speed, bool preheat,
                                      bool slow_cool)
{
    char ctx[128];
    snprintf(ctx, sizeof(ctx), "cone=%s speed=%d preheat=%d slow_cool=%d", cone_name(cone), (int)speed, preheat,
             slow_cool);

    /* At least one segment, capped to FIRING_MAX_SEGMENTS. */
    TEST_ASSERT_TRUE_MESSAGE(p->segment_count > 0 && p->segment_count <= FIRING_MAX_SEGMENTS, ctx);

    /* The peak segment reaches the cone's target temperature. */
    float target = cone_target_temp_c(cone, speed);
    TEST_ASSERT_EQUAL_FLOAT_MESSAGE(target, p->max_temp, ctx);

    /* At least one segment reaches the cone peak with the 10-min soak.
       (When the cone target equals an intermediate fixture like the 600°C
       quartz zone, multiple segments share that target_temp; only the
       generator's "Ramp to cone" segment gets the soak.) */
    bool found_peak_with_soak = false;
    for (uint8_t i = 0; i < p->segment_count; i++) {
        if (p->segments[i].target_temp == target && p->segments[i].hold_time == 10) {
            found_peak_with_soak = true;
            break;
        }
    }
    TEST_ASSERT_TRUE_MESSAGE(found_peak_with_soak, ctx);

    /* Optional preheat segment goes first. */
    if (preheat) {
        TEST_ASSERT_EQUAL_FLOAT_MESSAGE(120.0f, p->segments[0].target_temp, ctx);
    }

    /* Slow cool: last segment(s) have negative ramp rates, target_temp ≤ peak. */
    if (slow_cool && target > 650.0f) {
        const firing_segment_t *last = &p->segments[p->segment_count - 1];
        TEST_ASSERT_TRUE_MESSAGE(last->ramp_rate < 0.0f, ctx);
        TEST_ASSERT_TRUE_MESSAGE(last->target_temp <= target, ctx);
    }

    /* Estimated duration is computed, non-zero, within a sane upper bound.
       Cone 6 slow + slow_cool legitimately runs ~24h, so allow 48h. */
    TEST_ASSERT_TRUE_MESSAGE(p->estimated_duration > 0 && p->estimated_duration < 48 * 60, ctx);

    /* No segment may have zero ramp_rate (would never advance). */
    for (uint8_t i = 0; i < p->segment_count; i++) {
        TEST_ASSERT_TRUE_MESSAGE(p->segments[i].ramp_rate != 0.0f, ctx);
    }

    /* Profile ID is NVS-key safe: alphanumeric or dash, no dots or spaces. */
    for (const char *c = p->id; *c; c++) {
        TEST_ASSERT_TRUE_MESSAGE(*c != '.' && *c != ' ', ctx);
    }
}

static void test_generate_every_cone_speed_combo(void)
{
    for (int c = 0; c < CONE_COUNT; c++) {
        for (int s = 0; s <= 2; s++) {
            for (int preheat = 0; preheat <= 1; preheat++) {
                for (int slow_cool = 0; slow_cool <= 1; slow_cool++) {
                    firing_profile_t p;
                    esp_err_t err =
                        cone_fire_generate((cone_id_t)c, (cone_speed_t)s, (bool)preheat, (bool)slow_cool, &p);
                    TEST_ASSERT_EQUAL(ESP_OK, err);
                    assert_profile_invariants(&p, (cone_id_t)c, (cone_speed_t)s, (bool)preheat, (bool)slow_cool);
                }
            }
        }
    }
}

static void test_generate_rejects_null_profile(void)
{
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, cone_fire_generate(CONE_6, CONE_SPEED_MEDIUM, false, false, NULL));
}

static void test_generate_rejects_invalid_cone(void)
{
    firing_profile_t p;
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, cone_fire_generate((cone_id_t)-1, CONE_SPEED_MEDIUM, false, false, &p));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG,
                      cone_fire_generate((cone_id_t)CONE_COUNT, CONE_SPEED_MEDIUM, false, false, &p));
}

static void test_segment_count_grows_with_options(void)
{
    firing_profile_t base, with_preheat, with_slow_cool, with_both;
    TEST_ASSERT_EQUAL(ESP_OK, cone_fire_generate(CONE_6, CONE_SPEED_MEDIUM, false, false, &base));
    TEST_ASSERT_EQUAL(ESP_OK, cone_fire_generate(CONE_6, CONE_SPEED_MEDIUM, true, false, &with_preheat));
    TEST_ASSERT_EQUAL(ESP_OK, cone_fire_generate(CONE_6, CONE_SPEED_MEDIUM, false, true, &with_slow_cool));
    TEST_ASSERT_EQUAL(ESP_OK, cone_fire_generate(CONE_6, CONE_SPEED_MEDIUM, true, true, &with_both));

    /* Preheat adds 1 segment, slow_cool adds 2 (cool to inversion + slow quartz). */
    TEST_ASSERT_EQUAL_UINT8(base.segment_count + 1, with_preheat.segment_count);
    TEST_ASSERT_EQUAL_UINT8(base.segment_count + 2, with_slow_cool.segment_count);
    TEST_ASSERT_EQUAL_UINT8(base.segment_count + 3, with_both.segment_count);
}

static void test_slow_cool_skipped_for_low_temp_cone(void)
{
    /* Cones below ~650°C peak don't get slow-cool segments. CONE_022 peaks ~600°C. */
    firing_profile_t no_cool, with_cool;
    TEST_ASSERT_EQUAL(ESP_OK, cone_fire_generate(CONE_022, CONE_SPEED_MEDIUM, false, false, &no_cool));
    TEST_ASSERT_EQUAL(ESP_OK, cone_fire_generate(CONE_022, CONE_SPEED_MEDIUM, false, true, &with_cool));
    TEST_ASSERT_EQUAL_UINT8(no_cool.segment_count, with_cool.segment_count);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_known_cone_temperatures);
    RUN_TEST(test_speed_ordering);
    RUN_TEST(test_out_of_range_returns_zero);
    RUN_TEST(test_invalid_speed_falls_back_to_medium);
    RUN_TEST(test_cone_name_known_values);
    RUN_TEST(test_generate_every_cone_speed_combo);
    RUN_TEST(test_generate_rejects_null_profile);
    RUN_TEST(test_generate_rejects_invalid_cone);
    RUN_TEST(test_segment_count_grows_with_options);
    RUN_TEST(test_slow_cool_skipped_for_low_temp_cone);
    return UNITY_END();
}
