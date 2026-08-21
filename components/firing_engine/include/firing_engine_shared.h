#pragma once

/**
 * Firing-engine declarations that are public API *and* reachable from the host
 * test harness.
 *
 * Two headers need these three functions and neither can be the sole home:
 * `firing_engine.h` is the public API the web server consumes, but it pulls in
 * FreeRTOS and esp_err; `firing_engine_internal.h` is deliberately dep-free so
 * tests/host/ can link the pure decision logic without that. Declaring them in
 * both is what clang-tidy's readability-redundant-declaration flags, and what
 * CLAUDE.md forbids — "Declare each function in exactly one header."
 *
 * So they live here, in the intersection: nothing beyond firing_types.h and the
 * C standard library, and included by both. Anything added here must keep that
 * property, or the internal header stops being dep-free.
 */

#include "firing_types.h"
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Find the first segment whose ramp-rate sign is inconsistent with the
 * direction from its starting temperature to its target — the config in which
 * the engine labels a segment COOLING while actually driving full-power
 * heating (or vice versa), disabling the heating watchdogs.
 *
 * Segment 0 starts from `start_temp`; each later segment starts from the
 * previous segment's target. A move of more than RAMP_SIGN_EPS_C toward a
 * higher temperature requires a positive ramp; toward a lower temperature, a
 * negative ramp. Near-equal targets (|delta| <= eps) impose no direction.
 *
 * Pass a non-finite `start_temp` (e.g. NAN) to skip segment 0's own direction
 * check — used at profile-save time, when the kiln temperature the profile
 * will eventually fire from is unknown; the inter-segment checks still apply.
 *
 * Returns the offending segment index, or -1 if every segment is consistent
 * (also -1 for a NULL/empty profile). Pure: no globals, no I/O.
 *
 * Defined in firing_helpers.c.
 */
int firing_first_bad_ramp_sign(const firing_profile_t *profile, float start_temp);

/**
 * True while a relay diagnostic pulse is holding the SSR on. This is a
 * distinct busy state from a firing: `firing_engine_get_progress()` reports
 * is_active == false during a relay test, so callers that must not run
 * concurrently with it (firing start, autotune start, OTA, reboot) have to
 * consult this in addition to is_active.
 */
bool firing_engine_relay_test_active(void);

/**
 * Arm a relay diagnostic pulse for `duration_s` seconds (clamped to
 * [1, RELAY_TEST_MAX_S internally]). Returns true if armed, false if the kiln
 * is busy (firing, armed delayed start, autotune, or a test already running).
 *
 * Synchronous and atomic: the caller gets a definitive answer with no queue
 * latency, so an HTTP handler can return a real 200/409 instead of a fire-and-
 * forget {ok:true}. Does not check OTA — callers that need that gate it
 * separately. The firing tick drives the SSR for the armed pulse.
 */
bool firing_engine_relay_test_arm(uint32_t duration_s);

#ifdef __cplusplus
}
#endif
