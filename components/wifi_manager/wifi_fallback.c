#include "wifi_fallback.h"

void wifi_fallback_init(wifi_fallback_t *fb, const wifi_fallback_ops_t *ops, bool sta_configured)
{
    fb->ops = ops;
    fb->sta_configured = sta_configured;
    fb->ap_wanted = false;
    fb->ap_active = false;
    wifi_retry_reset(&fb->retry, 0);
}

void wifi_fallback_request_ap(wifi_fallback_t *fb)
{
    fb->ap_wanted = true;
}

/* Bring the provisioning AP up alongside (not instead of) the STA interface.
   APSTA keeps the STA interface available for the retry loop, so recovery never
   requires tearing the AP down.

   Both steps must land before the AP counts as active: telling callers an AP is
   available when esp_wifi_set_config() failed points them at whatever SSID the
   interface happened to be holding — on the no-credentials boot path there is
   no STA link to fall back on either. Returns false to leave ap_wanted standing
   so the next tick retries the whole sequence. */
static bool enter_ap(wifi_fallback_t *fb)
{
    if (fb->ops->set_ap_mode() != 0) {
        return false;
    }
    if (fb->ops->apply_ap_config() != 0) {
        return false;
    }

    fb->ap_active = true;
    wifi_retry_reset(&fb->retry, fb->ops->now_us());
    fb->ops->ap_up();
    return true;
}

/* The configured network came back. Drop the AP and return to the plain STA
   steady state — but only when nobody is associated, so a user who joined the
   AP in the seconds since the successful retry is not cut off mid-form. */
static void leave_ap(wifi_fallback_t *fb, int ap_clients)
{
    if (ap_clients > 0) {
        return;
    }
    if (fb->ops->set_sta_mode() != 0) {
        return;
    }

    fb->ap_wanted = false;
    fb->ap_active = false;
    fb->ops->ap_down();
}

wifi_retry_action_t wifi_fallback_service(wifi_fallback_t *fb, bool sta_connected, int ap_clients)
{
    if (fb->ap_wanted && !fb->ap_active && !enter_ap(fb)) {
        return WIFI_RETRY_NOT_DUE; /* transition failed; try again next tick */
    }
    if (!fb->ap_active) {
        return WIFI_RETRY_NOT_DUE;
    }

    if (sta_connected) {
        /* Re-arm on every tick the link is up. An AP client keeps the fallback
           open past recovery, and without this the policy would still be
           carrying the pre-recovery timestamp and escalated attempt count — so
           a second outage would fire a reconnect instantly, and being that
           overdue also defeats the bounded AP-client suppression. */
        wifi_retry_reset(&fb->retry, fb->ops->now_us());
        leave_ap(fb, ap_clients);
        return WIFI_RETRY_NOT_DUE;
    }

    if (!fb->sta_configured) {
        return WIFI_RETRY_NOT_DUE; /* provisioning-only AP; nothing to reconnect to */
    }

    wifi_retry_action_t action = wifi_retry_step(&fb->retry, ap_clients > 0, fb->ops->now_us());
    if (action == WIFI_RETRY_ATTEMPT) {
        fb->ops->sta_connect();
    }
    return action;
}

bool wifi_fallback_ap_active(const wifi_fallback_t *fb)
{
    return fb->ap_active;
}

bool wifi_fallback_ap_only(const wifi_fallback_t *fb, bool sta_connected)
{
    return fb->ap_active && !sta_connected;
}

const char *wifi_fallback_reported_ip(const wifi_fallback_t *fb, bool sta_connected, const char *sta_ip)
{
    return wifi_fallback_ap_only(fb, sta_connected) ? WIFI_FALLBACK_AP_IP : sta_ip;
}
