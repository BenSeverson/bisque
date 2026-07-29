#include "auth_helpers.h"

#include <string.h>

bool auth_token_equal(const char *provided, const char *expected, size_t max_len)
{
    if (!provided || !expected || max_len == 0) {
        return false;
    }

    size_t plen = strnlen(provided, max_len);
    size_t elen = strnlen(expected, max_len);

    /* Accumulate every difference instead of returning at the first one, and
     * walk the full buffer rather than the shorter string, so neither the
     * position of the first mismatch nor the length of the supplied token is
     * observable in how long this takes. Out-of-range bytes read as 0 on both
     * sides, which is why the length difference has to be folded in separately —
     * without it, "abc" and "abc\0\0" would compare equal. */
    unsigned char diff = (unsigned char)(plen ^ elen);
    for (size_t i = 0; i < max_len; i++) {
        unsigned char pc = (i < plen) ? (unsigned char)provided[i] : 0u;
        unsigned char ec = (i < elen) ? (unsigned char)expected[i] : 0u;
        diff |= (unsigned char)(pc ^ ec);
    }
    return diff == 0;
}

bool auth_bearer_token(const char *header, const char **out_token)
{
    if (!header || !out_token) {
        return false;
    }
    static const char PREFIX[] = "Bearer ";
    const size_t prefix_len = sizeof(PREFIX) - 1;
    if (strncmp(header, PREFIX, prefix_len) != 0) {
        return false;
    }
    *out_token = header + prefix_len;
    return true;
}
