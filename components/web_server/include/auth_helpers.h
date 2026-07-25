#pragma once

/**
 * Pure helpers for API bearer-token authentication, split out so they can be
 * exercised on the host without bringing up esp_http_server.
 */

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Compare a supplied token against the configured one in constant time.
 *
 * `strcmp` returns as soon as two bytes differ, so how long a rejection takes
 * depends on how many leading bytes were right — enough, in principle, to
 * recover a token a byte at a time. The practical risk on a LAN is low (#81),
 * but a fixed-time compare costs nothing here.
 *
 * `max_len` is the size of the buffer holding the configured token
 * (`sizeof(kiln_settings_t::api_token)`); both sides are read only within it.
 *
 * Returns true when the tokens are equal. A NULL argument is never equal.
 */
bool auth_token_equal(const char *provided, const char *expected, size_t max_len);

/**
 * Extract the token from an `Authorization: Bearer <token>` header value.
 *
 * On success sets `*out_token` to point into `header` past the prefix and
 * returns true; returns false (leaving `*out_token` untouched) if the header
 * does not carry the Bearer scheme.
 */
bool auth_bearer_token(const char *header, const char **out_token);

#ifdef __cplusplus
}
#endif
