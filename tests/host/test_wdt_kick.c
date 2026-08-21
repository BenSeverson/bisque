/* Host tests for the hardware watchdog's liveness rule (RB-2, issue #307).
 *
 * The case that matters is the third one: safety_task stops, the heartbeat goes
 * stale, the kick stops, the monostable's window expires and both SSR channels
 * de-energize with no firmware involvement. */
#include "unity.h"
#include "wdt_kick.h"

/* Worst-case monostable window, 100k x 22uF over -40..125 C with tolerance and
 * derating. Mirrors the figure in design.py's watchdog block. */
#define WDT_WINDOW_MIN_MS 1650u

void setUp(void)
{
}
void tearDown(void)
{
}

static void test_fresh_heartbeat_kicks(void)
{
    TEST_ASSERT_TRUE(wdt_kick_allowed(10000, 10000, false));
}

/* safety_task runs at 500 ms; 400 ms late is jitter, not death. */
static void test_jitter_still_kicks(void)
{
    TEST_ASSERT_TRUE(wdt_kick_allowed(10600, 10000, false));
}

/* The case the hardware exists for. */
static void test_stale_heartbeat_stops_the_kick(void)
{
    TEST_ASSERT_FALSE(wdt_kick_allowed(20000, 10000, false));
}

/* A genuinely missed 500 ms cycle lands at 1000 ms and must stop the kick —
 * the timeout tolerates jitter, not a skipped supervision pass. */
static void test_one_missed_cycle_stops_the_kick(void)
{
    TEST_ASSERT_FALSE(wdt_kick_allowed(11000, 10000, false));
}

static void test_emergency_stops_the_kick(void)
{
    TEST_ASSERT_FALSE(wdt_kick_allowed(10000, 10000, true));
}

/* Before safety_task's first pass the element is unsupervised. */
static void test_unset_heartbeat_stops_the_kick(void)
{
    TEST_ASSERT_FALSE(wdt_kick_allowed(10000, 0, false));
}

/* The millisecond counter wraps every 49.7 days. Unsigned subtraction has to
 * carry a firing across that boundary without a spurious trip. */
static void test_wrap_is_not_a_fault(void)
{
    const uint32_t before = 0xFFFFFF00u;                              /* 256 ms before the wrap */
    TEST_ASSERT_TRUE(wdt_kick_allowed(before + 300u, before, false)); /* now wrapped */
    TEST_ASSERT_FALSE(wdt_kick_allowed(before + 2000u, before, false));
}

/* The firmware must conclude it is unhealthy BEFORE the hardware acts, or the
 * elements drop with no logged cause. */
static void test_firmware_notices_before_the_window_expires(void)
{
    TEST_ASSERT_LESS_THAN_UINT32(WDT_WINDOW_MIN_MS, WDT_HEARTBEAT_TIMEOUT_MS + WDT_KICK_PERIOD_MS);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_fresh_heartbeat_kicks);
    RUN_TEST(test_jitter_still_kicks);
    RUN_TEST(test_stale_heartbeat_stops_the_kick);
    RUN_TEST(test_one_missed_cycle_stops_the_kick);
    RUN_TEST(test_emergency_stops_the_kick);
    RUN_TEST(test_unset_heartbeat_stops_the_kick);
    RUN_TEST(test_wrap_is_not_a_fault);
    RUN_TEST(test_firmware_notices_before_the_window_expires);
    return UNITY_END();
}
