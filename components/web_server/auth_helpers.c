#include "auth_helpers.h"

#include <string.h>

bool auth_token_equal(const char *provided, const char *expected, size_t max_len)
{
    if (!provided || !expected || max_len == 0) {
        return false;
    }

    /* The configured token's length is measured by scanning the whole buffer
     * rather than with strnlen(). strnlen() stops at the terminator, so it
     * takes time proportional to the secret's length — handing anyone who can
     * time rejections one of the two things this compare exists to hide. The
     * caller guarantees max_len bytes of `expected` are readable, so scanning
     * past the terminator is in-bounds; `live` clears at the first NUL and
     * never sets again, without a branch. */
    size_t elen = 0;
    unsigned char live = 1u;
    for (size_t i = 0; i < max_len; i++) {
        live &= (unsigned char)(expected[i] != '\0');
        elen += live;
    }

    /* `provided` is the caller's own input, not a secret, so measuring it
     * normally leaks nothing — and unlike `expected` it carries no guarantee
     * of readable bytes past its terminator. */
    size_t plen = strnlen(provided, max_len);

    /* Accumulate every difference instead of returning at the first one, and
     * walk the full buffer rather than the shorter string, so the position of
     * the first mismatch is not observable in how long this takes.
     *
     * Out-of-range bytes read as 0 on both sides, which is why the length
     * difference has to be folded in separately — without it, "abc" and
     * "abc\0\0" would compare equal.
     *
     * The masks replace `(i < len) ? byte : 0`. That ternary branches on a
     * secret-derived value for `expected`; a mask of all-ones or all-zeros
     * computes the same thing with no branch to observe. `provided` is indexed
     * at min(i, plen) so the read stays inside the string — its terminator is
     * the furthest byte touched. */
    unsigned char diff = (unsigned char)(plen ^ elen);
    for (size_t i = 0; i < max_len; i++) {
        unsigned char pmask = (unsigned char)(0u - (unsigned char)(i < plen));
        unsigned char emask = (unsigned char)(0u - (unsigned char)(i < elen));
        unsigned char pc = (unsigned char)provided[i < plen ? i : plen] & pmask;
        unsigned char ec = (unsigned char)expected[i] & emask;
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
