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

    /* GRACE, not OK: there is no reading yet, so the sensor cannot be called
       healthy (see #215). The invariant under test is the seed below. */
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE, safety_tc_watchdog_step(&r, BOOT_SEED_US, &last_valid));
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
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE, safety_tc_watchdog_step(&unset, BOOT_SEED_US, &last_valid));

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

/* ── Total failure: no reading ever arrives (issue #215) ─────────────────── */

/* If thermocouple_read() fails outright — SPI never comes up, sensor absent —
 * temp_read_task never writes the cache, so it stays all zeroes: fault == 0 and
 * timestamp_us == 0. That reads as a healthy 0 degC. The separate stale-reading
 * check in safety_task cannot help, because it is gated on timestamp_us > 0,
 * which is exactly the case absent here. So nothing tripped, ever, and a firing
 * would run with no temperature feedback at all. */
static void test_no_reading_ever_is_grace_then_trip(void)
{
    thermocouple_reading_t never_written = {0};
    int64_t origin = 1500000; /* safety_task's boot seed */
    int64_t last = origin;

    /* Inside the window: waiting for the producer, NOT healthy. Reporting OK
       here would clear the fault bit and run the over-temp check against a
       fabricated 0 degC — asserting the sensor is fine when no reading exists
       is the same lie this issue is about. */
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE, safety_tc_watchdog_step(&never_written, origin + 1000, &last));

    /* Past it: the producer is never coming. This must trip. */
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_TRIP,
                          safety_tc_watchdog_step(&never_written, origin + TEMP_FAULT_TIMEOUT_US + 1, &last));
}

/* A producer that starts late still cancels the deadline — the trip is for
 * "no data ever", not "slow to boot". */
static void test_late_first_reading_cancels_the_no_data_trip(void)
{
    thermocouple_reading_t never_written = {0};
    int64_t origin = 1500000;
    int64_t last = origin;

    TEST_ASSERT_EQUAL_INT(SAFETY_TC_FAULT_GRACE, safety_tc_watchdog_step(&never_written, origin + 2000000, &last));

    thermocouple_reading_t good = {.temperature_c = 25.0f, .timestamp_us = origin + 2500000};
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&good, origin + 2600000, &last));
    TEST_ASSERT_EQUAL_INT64(good.timestamp_us, last);

    /* Well past the original deadline, but readings are flowing now. */
    thermocouple_reading_t good2 = {.temperature_c = 26.0f, .timestamp_us = origin + TEMP_FAULT_TIMEOUT_US + 3000000};
    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&good2, good2.timestamp_us + 1000, &last));
}

/* The no-data deadline must not fire once real readings exist but have gone
 * stale — that is the stale-reading check's job, and it reports the same cause.
 * Here the cache holds a real (if old) reading, so this helper stays OK. */
static void test_stale_but_real_reading_is_not_the_no_data_case(void)
{
    int64_t origin = 1500000;
    int64_t last = origin;
    thermocouple_reading_t old_good = {.temperature_c = 900.0f, .timestamp_us = origin + 1000};

    TEST_ASSERT_EQUAL_INT(SAFETY_TC_OK, safety_tc_watchdog_step(&old_good, origin + TEMP_FAULT_TIMEOUT_US * 3, &last));
}

/* ── Lid polarity ────────────────────────────────────────────────────────── */

/* The default is normally-closed wiring against the internal pull-up: the shut
   lid holds the contact closed and pulls the input LOW, so lid-open is the
   pulled-up HIGH. This shipped inverted once — the mapping was inline in
   safety.c, which the host build does not compile, so nothing could catch it. */
static void test_default_polarity_is_normally_closed(void)
{
    TEST_ASSERT_TRUE_MESSAGE(safety_lid_level_is_open(1, false), "HIGH must read as lid open on NC wiring");
    TEST_ASSERT_FALSE_MESSAGE(safety_lid_level_is_open(0, false), "LOW is the shut lid holding the contact closed");
}

/* The whole point of that default: anything that breaks the circuit floats the
   input up to the pull-up, which must read OPEN and cut the heat. */
static void test_broken_wire_fails_safe_on_the_default(void)
{
    /* A pulled connector, a cut wire and a dead switch all present as HIGH. */
    TEST_ASSERT_TRUE_MESSAGE(safety_lid_level_is_open(1, false), "a broken lid circuit must fail safe to OPEN");
}

/* The opt-in inversion, for a switch that pulls low when the lid opens. */
static void test_open_is_low_inverts_the_mapping(void)
{
    TEST_ASSERT_TRUE(safety_lid_level_is_open(0, true));
    TEST_ASSERT_FALSE(safety_lid_level_is_open(1, true));
}

/* ── Lid debounce ────────────────────────────────────────────────────────── */

static void test_lid_open_is_believed_immediately(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    /* Get to a settled closed state first. */
    safety_lid_debounce_step(&d, false);
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, safety_lid_debounce_step(&d, false));
    /* One open sample is enough — no debounce on the way to cutting heat. */
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, true));
}

static void test_lid_close_requires_two_consecutive_samples(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, false));
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, safety_lid_debounce_step(&d, false));
}

/* A switch that bounces while closing must not accumulate credit across the
   bounce — otherwise two closed samples separated by an open one would declare
   the lid shut while it is still moving. */
static void test_lid_bounce_resets_the_close_counter(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, false));
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, true));
    TEST_ASSERT_EQUAL_INT(LID_STATE_OPEN, safety_lid_debounce_step(&d, false));
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, safety_lid_debounce_step(&d, false));
}

/* Staying closed must not overflow or change state on long runs. */
static void test_lid_stays_closed_while_closed(void)
{
    lid_debounce_t d = {.state = LID_STATE_OPEN, .close_samples = 0};
    for (int i = 0; i < 100; i++) {
        safety_lid_debounce_step(&d, false);
    }
    TEST_ASSERT_EQUAL_INT(LID_STATE_CLOSED, d.state);
    TEST_ASSERT_TRUE(d.close_samples >= LID_CLOSE_DEBOUNCE_SAMPLES);
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
    RUN_TEST(test_no_reading_ever_is_grace_then_trip);
    RUN_TEST(test_late_first_reading_cancels_the_no_data_trip);
    RUN_TEST(test_stale_but_real_reading_is_not_the_no_data_case);
    RUN_TEST(test_default_polarity_is_normally_closed);
    RUN_TEST(test_broken_wire_fails_safe_on_the_default);
    RUN_TEST(test_open_is_low_inverts_the_mapping);
    RUN_TEST(test_lid_open_is_believed_immediately);
    RUN_TEST(test_lid_close_requires_two_consecutive_samples);
    RUN_TEST(test_lid_bounce_resets_the_close_counter);
    RUN_TEST(test_lid_stays_closed_while_closed);
    return UNITY_END();
}
