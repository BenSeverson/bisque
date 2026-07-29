#include "wifi_retry_policy.h"

uint32_t wifi_retry_backoff_ms(uint32_t attempt_count)
{
    uint32_t ms = WIFI_RETRY_BASE_MS;
    for (uint32_t i = 0; i < attempt_count && ms < WIFI_RETRY_MAX_MS; i++) {
        ms *= 2;
    }
    return (ms > WIFI_RETRY_MAX_MS) ? WIFI_RETRY_MAX_MS : ms;
}

void wifi_retry_reset(wifi_retry_state_t *st, int64_t now_us)
{
    st->attempt_count = 0;
    st->last_attempt_us = now_us;
}

wifi_retry_action_t wifi_retry_step(wifi_retry_state_t *st, bool ap_client_associated, int64_t now_us)
{
    int64_t due_us = st->last_attempt_us + (int64_t)wifi_retry_backoff_ms(st->attempt_count) * 1000;
    if (now_us < due_us) {
        return WIFI_RETRY_NOT_DUE;
    }

    /* Suppression deliberately leaves the state alone, so the retry stays
       overdue rather than being consumed — it fires on the first poll after the
       client disconnects instead of waiting out a fresh backoff. The same
       property makes the overdue-by amount a free suppression clock, so
       bounding suppression needs no extra field. */
    if (ap_client_associated && (now_us - due_us) < WIFI_RETRY_SUPPRESS_MAX_US) {
        return WIFI_RETRY_SUPPRESSED;
    }

    if (st->attempt_count < UINT32_MAX) {
        st->attempt_count++;
    }
    st->last_attempt_us = now_us;
    return WIFI_RETRY_ATTEMPT;
}
