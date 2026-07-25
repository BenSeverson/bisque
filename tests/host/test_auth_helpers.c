#include "auth_helpers.h"
#include "unity.h"

#include <string.h>

/* Matches sizeof(kiln_settings_t::api_token). */
#define TOKEN_BUF 64

void setUp(void)
{
}
void tearDown(void)
{
}

/* ── auth_token_equal ───────────────────────────────────────────────────── */

static void test_matching_tokens_compare_equal(void)
{
    TEST_ASSERT_TRUE(auth_token_equal("s3cret", "s3cret", TOKEN_BUF));
    TEST_ASSERT_TRUE(auth_token_equal("", "", TOKEN_BUF));
}

static void test_differing_tokens_compare_unequal(void)
{
    TEST_ASSERT_FALSE(auth_token_equal("s3cret", "s3crer", TOKEN_BUF));
    /* Differing in the very first byte and in the very last must both fail —
       the whole point of the fixed-time loop is that neither short-circuits. */
    TEST_ASSERT_FALSE(auth_token_equal("Xs3cret", "s3cret", TOKEN_BUF));
    TEST_ASSERT_FALSE(auth_token_equal("s3cretX", "s3cret", TOKEN_BUF));
}

/* A prefix must never authenticate. Folding the length difference into the
   accumulator is what makes this work: out-of-range bytes read as 0 on both
   sides, so without it "abc" would match "abc\0\0…". */
static void test_a_prefix_does_not_authenticate(void)
{
    TEST_ASSERT_FALSE(auth_token_equal("s3c", "s3cret", TOKEN_BUF));
    TEST_ASSERT_FALSE(auth_token_equal("s3cret", "s3c", TOKEN_BUF));
    TEST_ASSERT_FALSE(auth_token_equal("", "s3cret", TOKEN_BUF));
    TEST_ASSERT_FALSE(auth_token_equal("s3cret", "", TOKEN_BUF));
}

static void test_null_arguments_never_authenticate(void)
{
    TEST_ASSERT_FALSE(auth_token_equal(NULL, "s3cret", TOKEN_BUF));
    TEST_ASSERT_FALSE(auth_token_equal("s3cret", NULL, TOKEN_BUF));
    TEST_ASSERT_FALSE(auth_token_equal(NULL, NULL, TOKEN_BUF));
    TEST_ASSERT_FALSE(auth_token_equal("s3cret", "s3cret", 0));
}

/* Only the first max_len bytes are ever read, so an unterminated buffer cannot
   run off the end. */
static void test_comparison_is_bounded_by_max_len(void)
{
    char a[8];
    char b[8];
    memset(a, 'x', sizeof(a));
    memset(b, 'x', sizeof(b));
    TEST_ASSERT_TRUE(auth_token_equal(a, b, sizeof(a)));

    b[7] = 'y';
    TEST_ASSERT_FALSE(auth_token_equal(a, b, sizeof(b)));
    /* Restricting the window to the identical prefix makes them equal again. */
    TEST_ASSERT_TRUE(auth_token_equal(a, b, 7));
}

static void test_full_length_token_compares(void)
{
    char a[TOKEN_BUF];
    char b[TOKEN_BUF];
    memset(a, 'k', TOKEN_BUF - 1);
    a[TOKEN_BUF - 1] = '\0';
    memcpy(b, a, TOKEN_BUF);
    TEST_ASSERT_TRUE(auth_token_equal(a, b, TOKEN_BUF));

    b[TOKEN_BUF - 2] = 'j';
    TEST_ASSERT_FALSE(auth_token_equal(a, b, TOKEN_BUF));
}

/* ── auth_bearer_token ──────────────────────────────────────────────────── */

static void test_bearer_prefix_is_stripped(void)
{
    const char *tok = NULL;
    TEST_ASSERT_TRUE(auth_bearer_token("Bearer s3cret", &tok));
    TEST_ASSERT_EQUAL_STRING("s3cret", tok);
}

static void test_bearer_accepts_an_empty_token(void)
{
    /* Parsing succeeds; auth_token_equal is what rejects it against a
       configured token. */
    const char *tok = NULL;
    TEST_ASSERT_TRUE(auth_bearer_token("Bearer ", &tok));
    TEST_ASSERT_EQUAL_STRING("", tok);
    TEST_ASSERT_FALSE(auth_token_equal(tok, "s3cret", TOKEN_BUF));
}

static void test_non_bearer_schemes_are_rejected(void)
{
    const char *tok = NULL;
    TEST_ASSERT_FALSE(auth_bearer_token("Basic s3cret", &tok));
    TEST_ASSERT_FALSE(auth_bearer_token("bearer s3cret", &tok)); /* scheme is case-sensitive here */
    TEST_ASSERT_FALSE(auth_bearer_token("Bearer", &tok));        /* no separating space */
    TEST_ASSERT_FALSE(auth_bearer_token("", &tok));
    TEST_ASSERT_NULL(tok); /* untouched on failure */
}

static void test_bearer_null_arguments(void)
{
    const char *tok = NULL;
    TEST_ASSERT_FALSE(auth_bearer_token(NULL, &tok));
    TEST_ASSERT_FALSE(auth_bearer_token("Bearer s3cret", NULL));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_matching_tokens_compare_equal);
    RUN_TEST(test_differing_tokens_compare_unequal);
    RUN_TEST(test_a_prefix_does_not_authenticate);
    RUN_TEST(test_null_arguments_never_authenticate);
    RUN_TEST(test_comparison_is_bounded_by_max_len);
    RUN_TEST(test_full_length_token_compares);
    RUN_TEST(test_bearer_prefix_is_stripped);
    RUN_TEST(test_bearer_accepts_an_empty_token);
    RUN_TEST(test_non_bearer_schemes_are_rejected);
    RUN_TEST(test_bearer_null_arguments);
    return UNITY_END();
}
