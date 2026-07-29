#pragma once

/*
 * AP-fallback state machine for wifi_manager's worker task.
 *
 * Owns the "should the provisioning AP be up right now, and is it?" question,
 * plus the paced STA reconnect that gets us back off it. Every radio call and
 * every notification is injected as an op, so — like wifi_retry_policy.c — this
 * file pulls in no esp_wifi/esp_event/FreeRTOS header and is driven directly by
 * the host test harness (tests/host/test_wifi_fallback.c). wifi_manager.c
 * supplies the ops and remains the only place that talks to the radio.
 *
 * The reason the transitions live here rather than inline in the worker is that
 * every one of them can fail, and the failure paths are where the bugs were:
 * a mode switch that failed used to drop the fallback on the floor forever, and
 * an AP config that failed used to be advertised anyway.
 */

#include <stdbool.h>
#include <stdint.h>

#include "wifi_retry_policy.h"

#ifdef __cplusplus
extern "C" {
#endif

/* The address esp_netif's default AP DHCP server always answers on. Reported to
   callers whenever the AP is the only way in. */
#define WIFI_FALLBACK_AP_IP "192.168.4.1"

/* Radio and notification hooks. The int-returning ones use 0 for success so
   this header stays free of esp_err_t; wifi_manager.c logs the real esp_err.
   set_ap_mode/apply_ap_config must be safe to call again after a failure — the
   whole transition is re-attempted from the top. */
typedef struct {
    int (*set_ap_mode)(void);     /* AP, or APSTA when STA is configured */
    int (*apply_ap_config)(void); /* push the provisioning SSID/PSK */
    int (*set_sta_mode)(void);    /* back to plain STA */
    void (*sta_connect)(void);    /* start one STA connect attempt */
    void (*ap_up)(void);          /* AP is genuinely up: publish it, signal readiness */
    void (*ap_down)(void);        /* AP torn down, STA is the way in again */
    int64_t (*now_us)(void);
} wifi_fallback_ops_t;

typedef struct {
    const wifi_fallback_ops_t *ops;
    bool sta_configured;

    /* Intent, deliberately separate from the achieved state below. The command
       that asked for the fallback is consumed once; if the transition fails,
       only a standing intent tells the next tick to try again. */
    bool ap_wanted;

    /* Achieved state. Written here (worker task), read by the event handler. */
    volatile bool ap_active;

    wifi_retry_state_t retry;
} wifi_fallback_t;

void wifi_fallback_init(wifi_fallback_t *fb, const wifi_fallback_ops_t *ops, bool sta_configured);

/* Ask for the provisioning AP. Idempotent; the transition itself happens in
   wifi_fallback_service() and is retried there until it succeeds. */
void wifi_fallback_request_ap(wifi_fallback_t *fb);

/* One worker tick. Drives any pending AP transition, then either the return to
 * plain STA (once nobody is on the AP) or the next paced reconnect attempt.
 *
 * Returns what the retry policy decided, so the caller can log it;
 * WIFI_RETRY_NOT_DUE whenever no retry was evaluated at all. */
wifi_retry_action_t wifi_fallback_service(wifi_fallback_t *fb, bool sta_connected, int ap_clients);

/* Is the AP up at all? (The event handler uses this to decide whether losing
   the STA link should start the fast pre-fallback retries.) */
bool wifi_fallback_ap_active(const wifi_fallback_t *fb);

/* Is the AP the *only* way in? During APSTA recovery the AP is briefly still up
   while the STA already has an IP, and callers (status LED, boot banner,
   /api/v1/wifi) mean this narrower question. */
bool wifi_fallback_ap_only(const wifi_fallback_t *fb, bool sta_connected);

/* The address callers should be told to use. Derived rather than cached, so a
   STA address cannot outlive the link it belongs to. */
const char *wifi_fallback_reported_ip(const wifi_fallback_t *fb, bool sta_connected, const char *sta_ip);

#ifdef __cplusplus
}
#endif
