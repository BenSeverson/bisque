#include "unity.h"
#include "wifi_fallback.h"

#include <string.h>

/* The AP-fallback transitions, driven against a fake radio. Every case below is
   a failure mode of the real thing: a mode switch that errors, an AP config
   that errors, a client that keeps the AP open past STA recovery. On hardware
   those are transient and rare, which is exactly why they went unnoticed —
   each one used to leave the controller in a state only a reboot cleared. */

#define MS_US(ms) ((int64_t)(ms) * 1000)
#define SEC_US(s) ((int64_t)(s) * 1000 * 1000)
#define MIN_US(m) SEC_US((m) * 60)

/* Fallback is entered at a non-zero boot offset so a policy that treats "never
   attempted" as epoch-zero shows up. */
#define FALLBACK_US SEC_US(90)

#define STA_IP "10.0.0.7"

typedef struct {
    int64_t now_us;

    /* Return codes the fake radio hands back (0 = success). */
    int set_ap_mode_rc;
    int apply_ap_config_rc;
    int set_sta_mode_rc;

    int set_ap_mode_calls;
    int apply_ap_config_calls;
    int set_sta_mode_calls;
    int sta_connect_calls;
    int ap_up_calls;
    int ap_down_calls;
} fake_radio_t;

static fake_radio_t s_radio;

static int fake_set_ap_mode(void)
{
    s_radio.set_ap_mode_calls++;
    return s_radio.set_ap_mode_rc;
}

static int fake_apply_ap_config(void)
{
    s_radio.apply_ap_config_calls++;
    return s_radio.apply_ap_config_rc;
}

static int fake_set_sta_mode(void)
{
    s_radio.set_sta_mode_calls++;
    return s_radio.set_sta_mode_rc;
}

static void fake_sta_connect(void)
{
    s_radio.sta_connect_calls++;
}

static void fake_ap_up(void)
{
    s_radio.ap_up_calls++;
}

static void fake_ap_down(void)
{
    s_radio.ap_down_calls++;
}

static int64_t fake_now_us(void)
{
    return s_radio.now_us;
}

static const wifi_fallback_ops_t k_fake_ops = {
    .set_ap_mode = fake_set_ap_mode,
    .apply_ap_config = fake_apply_ap_config,
    .set_sta_mode = fake_set_sta_mode,
    .sta_connect = fake_sta_connect,
    .ap_up = fake_ap_up,
    .ap_down = fake_ap_down,
    .now_us = fake_now_us,
};

static wifi_fallback_t s_fb;

void setUp(void)
{
    memset(&s_radio, 0, sizeof(s_radio));
    s_radio.now_us = FALLBACK_US;
    wifi_fallback_init(&s_fb, &k_fake_ops, true);
}

void tearDown(void)
{
}

/* One worker tick. */
static wifi_retry_action_t tick(bool sta_connected, int ap_clients)
{
    return wifi_fallback_service(&s_fb, sta_connected, ap_clients);
}

/* Tick once a second for `duration_us`, the way the worker task polls. */
static void run_for(int64_t duration_us, bool sta_connected, int ap_clients)
{
    for (int64_t elapsed = 0; elapsed < duration_us; elapsed += SEC_US(1)) {
        s_radio.now_us += SEC_US(1);
        tick(sta_connected, ap_clients);
    }
}

/* The happy path, as a baseline for everything below. */
static void enter_fallback_cleanly(void)
{
    wifi_fallback_request_ap(&s_fb);
    tick(false, 0);
    TEST_ASSERT_TRUE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_EQUAL_INT(1, s_radio.ap_up_calls);
}

/* ── the AP transition must survive its own failures ───────────────────── */

/* A transient esp_wifi_set_mode() error used to be terminal: the single queued
   "enter AP fallback" command had already been consumed, and the service loop
   started with "is the AP up? no → nothing to do". The kiln was then left with
   neither the configured network nor its own provisioning AP until a reboot. */
void test_mode_switch_failure_is_retried_until_it_lands(void)
{
    s_radio.set_ap_mode_rc = -1;
    wifi_fallback_request_ap(&s_fb);

    for (int i = 0; i < 5; i++) {
        s_radio.now_us += SEC_US(1);
        tick(false, 0);
    }
    TEST_ASSERT_FALSE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_EQUAL_INT(0, s_radio.ap_up_calls);
    TEST_ASSERT_GREATER_OR_EQUAL_INT(5, s_radio.set_ap_mode_calls); /* still trying */

    s_radio.set_ap_mode_rc = 0;
    s_radio.now_us += SEC_US(1);
    tick(false, 0);

    TEST_ASSERT_TRUE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_EQUAL_INT(1, s_radio.ap_up_calls);
}

/* Same story one step later: the mode switch succeeded but pushing the SSID and
   PSK did not. The AP was marked active and advertised anyway, so callers were
   told to look for a network that was never configured — and on the
   no-credentials boot path there is no STA link to fall back to. */
void test_ap_is_not_advertised_until_its_config_lands(void)
{
    s_radio.apply_ap_config_rc = -1;
    wifi_fallback_request_ap(&s_fb);

    tick(false, 0);
    TEST_ASSERT_FALSE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_FALSE(wifi_fallback_ap_only(&s_fb, false));
    TEST_ASSERT_EQUAL_STRING(STA_IP, wifi_fallback_reported_ip(&s_fb, false, STA_IP));
    TEST_ASSERT_EQUAL_INT(0, s_radio.ap_up_calls);

    /* The whole sequence is re-attempted, not just the half that failed. */
    s_radio.apply_ap_config_rc = 0;
    s_radio.now_us += SEC_US(1);
    tick(false, 0);

    TEST_ASSERT_TRUE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_EQUAL_INT(2, s_radio.set_ap_mode_calls);
    TEST_ASSERT_EQUAL_STRING(WIFI_FALLBACK_AP_IP, wifi_fallback_reported_ip(&s_fb, false, STA_IP));
}

/* Readiness (the bit app_main waits on before printing the setup-mode banner)
   must not be raised while the AP is still only an intention. */
void test_readiness_is_signalled_once_and_only_after_the_ap_is_up(void)
{
    s_radio.set_ap_mode_rc = -1;
    wifi_fallback_request_ap(&s_fb);
    run_for(SEC_US(10), false, 0);
    TEST_ASSERT_EQUAL_INT(0, s_radio.ap_up_calls);

    s_radio.set_ap_mode_rc = 0;
    run_for(SEC_US(10), false, 0);

    /* Exactly one, however many ticks pass: an idempotent transition. */
    TEST_ASSERT_EQUAL_INT(1, s_radio.ap_up_calls);
}

/* ── recovery ──────────────────────────────────────────────────────────── */

void test_ap_is_dropped_once_the_sta_link_returns(void)
{
    enter_fallback_cleanly();

    s_radio.now_us += SEC_US(1);
    tick(true, 0);

    TEST_ASSERT_FALSE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_EQUAL_INT(1, s_radio.set_sta_mode_calls);
    TEST_ASSERT_EQUAL_INT(1, s_radio.ap_down_calls);
}

void test_ap_is_held_open_while_a_client_is_associated(void)
{
    enter_fallback_cleanly();

    run_for(MIN_US(5), true, 1);

    TEST_ASSERT_TRUE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_EQUAL_INT(0, s_radio.set_sta_mode_calls);
    TEST_ASSERT_EQUAL_INT(0, s_radio.ap_down_calls);
}

/* The backoff has to be re-armed while the link is up. It was not: the state
   still held the pre-recovery timestamp and escalated attempt count, so a
   second outage fired a reconnect on the very next tick — and being that
   overdue also walks straight through the bounded AP-client suppression, which
   is measured in how overdue the attempt is. */
void test_backoff_is_rearmed_while_the_sta_link_is_up(void)
{
    enter_fallback_cleanly();

    /* An hour of fruitless retries pushes the backoff to its 5 min ceiling. */
    run_for(MIN_US(60), false, 0);
    TEST_ASSERT_GREATER_THAN_INT(0, s_radio.sta_connect_calls);

    /* The router comes back, but a phone is sitting on the AP, so the fallback
       stays up for another twenty minutes. */
    run_for(MIN_US(20), true, 1);
    TEST_ASSERT_TRUE(wifi_fallback_ap_active(&s_fb));

    int attempts_before = s_radio.sta_connect_calls;

    /* The router drops again. The next tick must not reconnect: the policy
       should be counting from the link loss, not from an hour ago. */
    s_radio.now_us += SEC_US(1);
    TEST_ASSERT_EQUAL(WIFI_RETRY_NOT_DUE, tick(false, 1));
    TEST_ASSERT_EQUAL_INT(attempts_before, s_radio.sta_connect_calls);

    /* Still nothing most of the way to the base backoff... */
    run_for(MS_US(WIFI_RETRY_BASE_MS) - SEC_US(5), false, 1);
    TEST_ASSERT_EQUAL_INT(attempts_before, s_radio.sta_connect_calls);

    /* ...and when it does come due, the associated client suppresses it, which
       an hour-overdue attempt would have ignored. */
    s_radio.now_us += SEC_US(10);
    TEST_ASSERT_EQUAL(WIFI_RETRY_SUPPRESSED, tick(false, 1));
    TEST_ASSERT_EQUAL_INT(attempts_before, s_radio.sta_connect_calls);
}

/* ── the address we tell people to use ─────────────────────────────────── */

/* An AP client holds the fallback open across a STA recovery; then the router
   drops again. The device is reachable only at 192.168.4.1, but the cached LAN
   address outlived the link and /api/v1/wifi kept advertising it. */
void test_reported_ip_reverts_to_the_ap_when_the_sta_link_drops(void)
{
    enter_fallback_cleanly();
    TEST_ASSERT_EQUAL_STRING(WIFI_FALLBACK_AP_IP, wifi_fallback_reported_ip(&s_fb, false, "0.0.0.0"));

    /* STA back, AP held open by a client: the LAN address is the useful one. */
    run_for(SEC_US(5), true, 1);
    TEST_ASSERT_TRUE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_FALSE(wifi_fallback_ap_only(&s_fb, true));
    TEST_ASSERT_EQUAL_STRING(STA_IP, wifi_fallback_reported_ip(&s_fb, true, STA_IP));

    /* Router drops. Only the AP is reachable now. */
    TEST_ASSERT_TRUE(wifi_fallback_ap_only(&s_fb, false));
    TEST_ASSERT_EQUAL_STRING(WIFI_FALLBACK_AP_IP, wifi_fallback_reported_ip(&s_fb, false, STA_IP));
}

/* ── provisioning-only AP ──────────────────────────────────────────────── */

/* No credentials were ever saved, so there is nothing to reconnect to; the AP
   must simply stay up rather than churning the radio. */
void test_provisioning_only_ap_never_retries_sta(void)
{
    wifi_fallback_init(&s_fb, &k_fake_ops, false);
    enter_fallback_cleanly();

    run_for(MIN_US(60), false, 0);

    TEST_ASSERT_TRUE(wifi_fallback_ap_active(&s_fb));
    TEST_ASSERT_EQUAL_INT(0, s_radio.sta_connect_calls);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_mode_switch_failure_is_retried_until_it_lands);
    RUN_TEST(test_ap_is_not_advertised_until_its_config_lands);
    RUN_TEST(test_readiness_is_signalled_once_and_only_after_the_ap_is_up);
    RUN_TEST(test_ap_is_dropped_once_the_sta_link_returns);
    RUN_TEST(test_ap_is_held_open_while_a_client_is_associated);
    RUN_TEST(test_backoff_is_rearmed_while_the_sta_link_is_up);
    RUN_TEST(test_reported_ip_reverts_to_the_ap_when_the_sta_link_drops);
    RUN_TEST(test_provisioning_only_ap_never_retries_sta);
    return UNITY_END();
}
