#include "safety_internal.h"
#include "thermocouple.h"
#include "unity.h"

void setUp(void)
{
}
void tearDown(void)
{
}

#define BOOT_SEED_US (1500LL * 1000) /* safety_task starts 1.5 s after boot */

/* The all-zeroes cached reading that thermocouple_get_latest() returns before
 * temp_read_task has ever written one: fault-free *and* timestamp-free. */
static thermocouple_reading_t unset_reading(void)
{
    thermocouple_reading_t r = {0};
    return r;
}

static thermocouple_reading_t good_reading(int64_t timestamp_us, float temp_c)
{
    thermocouple_reading_t r = {0};
    r.temperature_c = temp_c;
    r.timestamp_us = timestamp_us;
    return r;
}

static thermocouple_reading_t faulted_reading(int64_t timestamp_us)
{
    thermocouple_reading_t r = {0};
    r.fault = TC_FAULT_OPEN_CIRCUIT;
    r.timestamp_us = timestamp_us;
    return r;
}

/* ── the boot race (issue #120) ────────────────────────────────────────── */

/* An unset cached reading must not become the grace-period origin. */
static void test_unset_reading_does_not_clobber_boot_seed(void)
{
    int64_t last_valid = BOOT_SEED_US;
    thermocouple_reading_t r = unset_reading();

    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&r, BOOT_SEED_US, &last_valid));
    TEST_ASSERT_EQUAL_INT64(BOOT_SEED_US, last_valid);
}

/* Full boot timeline: safety_task ticks once on the unset reading (it outranks
 * temp_read_task), then the thermocouple turns out to be unplugged. The trip
 * must wait out APP_TEMP_FAULT_TIMEOUT_MS measured from the boot seed — not
 * from the epoch. Regression for issue #120, where the unset reading reset the
 * origin to 0 and the first faulted sample tripped instantly. */
static void test_tc_fault_at_boot_still_gets_full_grace_period(void)
{
    int64_t last_valid = BOOT_SEED_US;

    thermocouple_reading_t unset = unset_reading();
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&unset, BOOT_SEED_US, &last_valid));

    /* First faulted sample 250 ms later: inside the grace period. */
    thermocouple_reading_t bad = faulted_reading(BOOT_SEED_US + 250LL * 1000);
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE,
                          safety_tc_watchdog_step(&bad, BOOT_SEED_US + 250LL * 1000, &last_valid));

    /* Still inside it just before the timeout expires. */
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE,
                          safety_tc_watchdog_step(&bad, BOOT_SEED_US + TEMP_FAULT_TIMEOUT_US, &last_valid));

    /* And it must still trip once the grace period is genuinely over — the fix
       delays the trip, it must not suppress it. */
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_TRIP,
                          safety_tc_watchdog_step(&bad, BOOT_SEED_US + TEMP_FAULT_TIMEOUT_US + 1, &last_valid));
}

/* ── steady-state behaviour ────────────────────────────────────────────── */

static void test_good_reading_advances_the_origin(void)
{
    int64_t last_valid = BOOT_SEED_US;
    thermocouple_reading_t good = good_reading(60LL * 1000000, 900.0f);

    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&good, 60LL * 1000000, &last_valid));
    TEST_ASSERT_EQUAL_INT64(60LL * 1000000, last_valid);
}

static void test_fault_grace_is_measured_from_last_good_reading(void)
{
    int64_t last_valid = BOOT_SEED_US;
    thermocouple_reading_t good = good_reading(60LL * 1000000, 900.0f);
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&good, 60LL * 1000000, &last_valid));

    /* A fault appearing right after that reading gets the whole window. */
    thermocouple_reading_t bad = faulted_reading(60LL * 1000000 + 250LL * 1000);
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE,
                          safety_tc_watchdog_step(&bad, 60LL * 1000000 + TEMP_FAULT_TIMEOUT_US, &last_valid));
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_TRIP,
                          safety_tc_watchdog_step(&bad, 60LL * 1000000 + TEMP_FAULT_TIMEOUT_US + 1, &last_valid));
}

/* A faulted reading must never advance the origin, or a persistent fault whose
 * timestamp keeps updating would push the deadline out forever. */
static void test_faulted_reading_never_advances_the_origin(void)
{
    int64_t last_valid = BOOT_SEED_US;

    for (int64_t t = BOOT_SEED_US; t <= BOOT_SEED_US + TEMP_FAULT_TIMEOUT_US; t += 500LL * 1000) {
        thermocouple_reading_t bad = faulted_reading(t);
        TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE, safety_tc_watchdog_step(&bad, t, &last_valid));
    }
    TEST_ASSERT_EQUAL_INT64(BOOT_SEED_US, last_valid);

    thermocouple_reading_t bad = faulted_reading(BOOT_SEED_US + TEMP_FAULT_TIMEOUT_US + 1);
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_TRIP,
                          safety_tc_watchdog_step(&bad, BOOT_SEED_US + TEMP_FAULT_TIMEOUT_US + 1, &last_valid));
}

/* A fault that clears inside the grace period must rearm the debounce. */
static void test_recovered_fault_rearms_the_grace_period(void)
{
    int64_t last_valid = BOOT_SEED_US;

    thermocouple_reading_t bad = faulted_reading(BOOT_SEED_US + 1000LL * 1000);
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE,
                          safety_tc_watchdog_step(&bad, BOOT_SEED_US + 1000LL * 1000, &last_valid));

    int64_t recovered_us = BOOT_SEED_US + 2000LL * 1000;
    thermocouple_reading_t good = good_reading(recovered_us, 25.0f);
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&good, recovered_us, &last_valid));

    /* Deadline now hangs off the recovery, not the boot seed. */
    thermocouple_reading_t bad2 = faulted_reading(recovered_us + 100LL * 1000);
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE,
                          safety_tc_watchdog_step(&bad2, recovered_us + TEMP_FAULT_TIMEOUT_US, &last_valid));
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_TRIP,
                          safety_tc_watchdog_step(&bad2, recovered_us + TEMP_FAULT_TIMEOUT_US + 1, &last_valid));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_unset_reading_does_not_clobber_boot_seed);
    RUN_TEST(test_tc_fault_at_boot_still_gets_full_grace_period);
    RUN_TEST(test_good_reading_advances_the_origin);
    RUN_TEST(test_fault_grace_is_measured_from_last_good_reading);
    RUN_TEST(test_faulted_reading_never_advances_the_origin);
    RUN_TEST(test_recovered_fault_rearms_the_grace_period);
    return UNITY_END();
}
