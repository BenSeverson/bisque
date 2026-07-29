#pragma once

/*
 * Pure STA-reconnect policy for wifi_manager's AP-fallback mode.
 *
 * Kept free of esp_wifi/esp_event/FreeRTOS so it can be exercised by the host
 * test harness (tests/host/test_wifi_retry_policy.c) — same reason
 * safety_helpers.c exists. wifi_manager.c owns the radio; this file only
 * answers "may I start a STA connect attempt right now?".
 */

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* First retry lands 30 s after entering AP fallback, then doubles. */
#define WIFI_RETRY_BASE_MS 30000U

/* Backoff ceiling. Bounded-but-persistent: the kiln keeps trying forever, but
   never more than once every 5 min, so a router that comes back mid-firing
   costs at most one backoff interval of lost remote monitoring. */
#define WIFI_RETRY_MAX_MS 300000U

/* An associated AP client suppresses retries (a connect attempt makes the STA
   scan, which drags the shared radio off the AP channel and would yank the
   provisioning form out from under whoever is filling it in). Suppression is
   itself bounded: a device that auto-joins "Bisque" and idles there forever
   must not strand the kiln on its own AP, so after this long overdue we
   attempt anyway. */
#define WIFI_RETRY_SUPPRESS_MAX_US (15LL * 60 * 1000 * 1000)

typedef enum {
    WIFI_RETRY_NOT_DUE = 0, /* backoff interval has not elapsed */
    WIFI_RETRY_SUPPRESSED,  /* due, but an AP client is mid-provisioning */
    WIFI_RETRY_ATTEMPT,     /* start a STA connect attempt now */
} wifi_retry_action_t;

typedef struct {
    uint32_t attempt_count;  /* STA attempts made since entering AP fallback */
    int64_t last_attempt_us; /* also the fallback-entry timestamp before the first attempt */
} wifi_retry_state_t;

/* Backoff for the (attempt_count)-th retry, in ms: 30 s doubling to a 5 min cap. */
uint32_t wifi_retry_backoff_ms(uint32_t attempt_count);

/* Arm the policy on entering AP fallback (or after a successful connect). */
void wifi_retry_reset(wifi_retry_state_t *st, int64_t now_us);

/* Decide whether a STA connect attempt may start now. On WIFI_RETRY_ATTEMPT the
   state is advanced (attempt counted, backoff restarted); the other outcomes
   leave it untouched, so a suppressed retry stays overdue and fires as soon as
   the AP client leaves. */
wifi_retry_action_t wifi_retry_step(wifi_retry_state_t *st, bool ap_client_associated, int64_t now_us);

#ifdef __cplusplus
}
#endif
