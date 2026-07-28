#include "unity.h"
#include "wifi_retry_policy.h"

void setUp(void)
{
}
void tearDown(void)
{
}

#define MS_US(ms) ((int64_t)(ms) * 1000)
#define SEC_US(s) ((int64_t)(s) * 1000 * 1000)
#define MIN_US(m) SEC_US((m) * 60)

/* Fallback is entered at a non-zero boot offset everywhere below, so a policy
   that accidentally treats "never attempted" as epoch-zero shows up. */
#define FALLBACK_US SEC_US(90)

static wifi_retry_state_t armed_at(int64_t now_us)
{
    wifi_retry_state_t st;
    wifi_retry_reset(&st, now_us);
    return st;
}

/* Run the policy from `from_us` to `to_us` in `step_us` slices, counting the
   attempts it grants. Mirrors how the wifi worker task polls it. */
static int drive(wifi_retry_state_t *st, int64_t from_us, int64_t to_us, int64_t step_us, bool ap_client)
{
    int attempts = 0;
    for (int64_t t = from_us; t <= to_us; t += step_us) {
        if (wifi_retry_step(st, ap_client, t) == WIFI_RETRY_ATTEMPT) {
            attempts++;
        }
    }
    return attempts;
}

/* ── the bug (issue #78): AP fallback is a one-way door ─────────────────── */

/* The whole point: a kiln that fell back to its provisioning AP because the
   router was rebooting must keep trying the configured network. Today it never
   does, and only a power cycle recovers it — mid-firing, that means no remote
   monitoring for the rest of the firing. */
void test_retries_sta_after_ap_fallback(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);

    TEST_ASSERT_EQUAL(WIFI_RETRY_ATTEMPT, wifi_retry_step(&st, false, FALLBACK_US + MS_US(WIFI_RETRY_BASE_MS)));
}

/* And it must keep trying, not give up after a handful. */
void test_retries_are_persistent_over_hours(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);

    int attempts = drive(&st, FALLBACK_US, FALLBACK_US + MIN_US(180), SEC_US(1), false);

    /* 3 h at a 5 min ceiling: ~35 attempts. Assert only that it stays busy. */
    TEST_ASSERT_GREATER_THAN_INT(20, attempts);
}

/* ── cadence: bounded, not a 5 s hammer ─────────────────────────────────── */

void test_first_retry_waits_the_base_backoff(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);

    TEST_ASSERT_EQUAL(WIFI_RETRY_NOT_DUE, wifi_retry_step(&st, false, FALLBACK_US));
    TEST_ASSERT_EQUAL(WIFI_RETRY_NOT_DUE, wifi_retry_step(&st, false, FALLBACK_US + SEC_US(5)));
    TEST_ASSERT_EQUAL(WIFI_RETRY_NOT_DUE, wifi_retry_step(&st, false, FALLBACK_US + MS_US(WIFI_RETRY_BASE_MS) - 1));
    TEST_ASSERT_EQUAL(WIFI_RETRY_ATTEMPT, wifi_retry_step(&st, false, FALLBACK_US + MS_US(WIFI_RETRY_BASE_MS)));
}

void test_backoff_doubles_then_saturates(void)
{
    TEST_ASSERT_EQUAL_UINT32(WIFI_RETRY_BASE_MS, wifi_retry_backoff_ms(0));
    TEST_ASSERT_EQUAL_UINT32(WIFI_RETRY_BASE_MS * 2, wifi_retry_backoff_ms(1));
    TEST_ASSERT_EQUAL_UINT32(WIFI_RETRY_BASE_MS * 4, wifi_retry_backoff_ms(2));

    /* Monotonic non-decreasing, and never past the ceiling — including at the
       saturating attempt_count a long-running kiln would reach. */
    uint32_t prev = 0;
    for (uint32_t i = 0; i < 64; i++) {
        uint32_t ms = wifi_retry_backoff_ms(i);
        TEST_ASSERT_GREATER_OR_EQUAL_UINT32(prev, ms);
        TEST_ASSERT_LESS_OR_EQUAL_UINT32(WIFI_RETRY_MAX_MS, ms);
        prev = ms;
    }
    TEST_ASSERT_EQUAL_UINT32(WIFI_RETRY_MAX_MS, wifi_retry_backoff_ms(64));
    TEST_ASSERT_EQUAL_UINT32(WIFI_RETRY_MAX_MS, wifi_retry_backoff_ms(UINT32_MAX));
}

/* An hour of fallback must not add up to hundreds of radio events. */
void test_cadence_is_not_a_hammer(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);

    int attempts = drive(&st, FALLBACK_US, FALLBACK_US + MIN_US(60), SEC_US(1), false);

    /* 30/60/120/240/300... over an hour ≈ 12. Anything near "every 5 s" (720)
       is radio noise during a firing. */
    TEST_ASSERT_LESS_OR_EQUAL_INT(20, attempts);
}

/* Backoff restarts from the attempt, not from fallback entry — otherwise every
   subsequent poll would re-fire immediately once the first retry came due. */
void test_attempt_restarts_the_interval(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);
    int64_t t = FALLBACK_US + MS_US(WIFI_RETRY_BASE_MS);

    TEST_ASSERT_EQUAL(WIFI_RETRY_ATTEMPT, wifi_retry_step(&st, false, t));
    TEST_ASSERT_EQUAL(WIFI_RETRY_NOT_DUE, wifi_retry_step(&st, false, t + SEC_US(1)));
    TEST_ASSERT_EQUAL(WIFI_RETRY_NOT_DUE, wifi_retry_step(&st, false, t + MS_US(WIFI_RETRY_BASE_MS)));
    TEST_ASSERT_EQUAL(WIFI_RETRY_ATTEMPT, wifi_retry_step(&st, false, t + MS_US(WIFI_RETRY_BASE_MS * 2)));
}

/* ── AP-client suppression ──────────────────────────────────────────────── */

/* Someone is on the AP filling in the provisioning form. A STA connect makes
   the shared radio scan off-channel; do not yank the interface out from under
   them. */
void test_associated_ap_client_suppresses_retry(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);

    TEST_ASSERT_EQUAL(WIFI_RETRY_SUPPRESSED, wifi_retry_step(&st, true, FALLBACK_US + MS_US(WIFI_RETRY_BASE_MS)));
}

/* Suppression must not consume the retry: the moment the client leaves, the
   overdue attempt fires rather than waiting out another backoff. */
void test_suppressed_retry_fires_as_soon_as_client_leaves(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);
    int64_t due = FALLBACK_US + MS_US(WIFI_RETRY_BASE_MS);

    TEST_ASSERT_EQUAL(WIFI_RETRY_SUPPRESSED, wifi_retry_step(&st, true, due));
    TEST_ASSERT_EQUAL(WIFI_RETRY_SUPPRESSED, wifi_retry_step(&st, true, due + SEC_US(10)));
    TEST_ASSERT_EQUAL(WIFI_RETRY_ATTEMPT, wifi_retry_step(&st, false, due + SEC_US(11)));
}

/* A phone that auto-joined "Bisque" and was pocketed must not strand the kiln
   on its own AP forever. */
void test_suppression_is_bounded(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);
    int64_t due = FALLBACK_US + MS_US(WIFI_RETRY_BASE_MS);

    TEST_ASSERT_EQUAL(WIFI_RETRY_SUPPRESSED, wifi_retry_step(&st, true, due + WIFI_RETRY_SUPPRESS_MAX_US - 1));
    TEST_ASSERT_EQUAL(WIFI_RETRY_ATTEMPT, wifi_retry_step(&st, true, due + WIFI_RETRY_SUPPRESS_MAX_US));
}

/* ── reset ──────────────────────────────────────────────────────────────── */

/* After a successful connect the next fallback starts from the short backoff
   again, not from wherever the previous fallback's escalation left off. */
void test_reset_rearms_the_short_backoff(void)
{
    wifi_retry_state_t st = armed_at(FALLBACK_US);
    drive(&st, FALLBACK_US, FALLBACK_US + MIN_US(60), SEC_US(1), false);

    int64_t reconnected = FALLBACK_US + MIN_US(60);
    wifi_retry_reset(&st, reconnected);

    TEST_ASSERT_EQUAL(WIFI_RETRY_NOT_DUE, wifi_retry_step(&st, false, reconnected + MS_US(WIFI_RETRY_BASE_MS) - 1));
    TEST_ASSERT_EQUAL(WIFI_RETRY_ATTEMPT, wifi_retry_step(&st, false, reconnected + MS_US(WIFI_RETRY_BASE_MS)));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_retries_sta_after_ap_fallback);
    RUN_TEST(test_retries_are_persistent_over_hours);
    RUN_TEST(test_first_retry_waits_the_base_backoff);
    RUN_TEST(test_backoff_doubles_then_saturates);
    RUN_TEST(test_cadence_is_not_a_hammer);
    RUN_TEST(test_attempt_restarts_the_interval);
    RUN_TEST(test_associated_ap_client_suppresses_retry);
    RUN_TEST(test_suppressed_retry_fires_as_soon_as_client_leaves);
    RUN_TEST(test_suppression_is_bounded);
    RUN_TEST(test_reset_rearms_the_short_backoff);
    return UNITY_END();
}
