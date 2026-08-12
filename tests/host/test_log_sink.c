/**
 * log_sink — the device log's ring buffer (#189).
 *
 * The parts worth pinning are the ones a firmware reader can't see going wrong:
 * eviction of the oldest line when the ring fills, ANSI/CR stripping (the ESP
 * console colours every line), assembly of a line delivered in several vprintf
 * chunks, and a snapshot that keeps the *newest* lines when the destination is
 * short — a truncated diagnostics bundle is useless if it holds the boot banner
 * and not the fault.
 */
#include "unity.h"
#include "log_sink.h"
#include <string.h>

void setUp(void) {}
void tearDown(void) {}

static log_sink_t s_sink;
static char s_storage[256];

static void reset(size_t capacity)
{
    memset(s_storage, 0, sizeof(s_storage));
    log_sink_init(&s_sink, s_storage, capacity);
}

static void write_str(const char *s)
{
    log_sink_write(&s_sink, s, strlen(s));
}

/** Snapshot into `dst` and return the line at index `idx`, or NULL. */
static const char *nth_line(char *dst, size_t dst_cap, size_t idx, size_t *out_lines)
{
    size_t lines = 0;
    size_t bytes = log_sink_snapshot(&s_sink, dst, dst_cap, &lines);
    if (out_lines) {
        *out_lines = lines;
    }
    size_t off = 0;
    for (size_t i = 0; i < lines && off < bytes; i++) {
        if (i == idx) {
            return dst + off;
        }
        off += strlen(dst + off) + 1;
    }
    return NULL;
}

static void test_lines_are_committed_on_newline(void)
{
    reset(sizeof(s_storage));
    write_str("I (12) main: hello\n");

    char out[256];
    size_t lines = 0;
    const char *first = nth_line(out, sizeof(out), 0, &lines);
    TEST_ASSERT_EQUAL_UINT(1, lines);
    TEST_ASSERT_EQUAL_STRING("I (12) main: hello", first);
    TEST_ASSERT_EQUAL_UINT32(1, s_sink.total);
    TEST_ASSERT_EQUAL_UINT32(0, s_sink.dropped);
}

/* Nothing is visible until the newline arrives: a half-written line in a
   snapshot would be indistinguishable from a truncated one. */
static void test_partial_line_is_not_visible_until_complete(void)
{
    reset(sizeof(s_storage));
    write_str("W (30) safety: over");

    char out[256];
    size_t lines = 99;
    TEST_ASSERT_EQUAL_UINT(0, log_sink_snapshot(&s_sink, out, sizeof(out), &lines));
    TEST_ASSERT_EQUAL_UINT(0, lines);

    write_str("temp\n");
    TEST_ASSERT_EQUAL_STRING("W (30) safety: overtemp", nth_line(out, sizeof(out), 0, &lines));
    TEST_ASSERT_EQUAL_UINT(1, lines);
}

/* The ESP console wraps every line in colour codes when CONFIG_LOG_COLORS is
   on. They are control bytes in a JSON string, so they never reach the ring. */
static void test_ansi_escapes_and_cr_are_stripped(void)
{
    reset(sizeof(s_storage));
    write_str("\033[0;32mI (44) main: ready\033[0m\r\n");

    char out[256];
    TEST_ASSERT_EQUAL_STRING("I (44) main: ready", nth_line(out, sizeof(out), 0, NULL));
}

static void test_blank_lines_are_not_retained(void)
{
    reset(sizeof(s_storage));
    write_str("\n\n\n");
    TEST_ASSERT_EQUAL_UINT(0, s_sink.lines);
    TEST_ASSERT_EQUAL_UINT32(0, s_sink.total);
}

/* The oldest line goes when the ring is full, and `dropped` says so — that
   counter is the only thing telling a bundle's reader the log is a window. */
static void test_oldest_lines_are_evicted_when_full(void)
{
    reset(32);
    write_str("aaaaaaaaaa\n"); /* 11 bytes stored */
    write_str("bbbbbbbbbb\n");
    write_str("cccccccccc\n"); /* 33 > 32: evicts "aaaaaaaaaa" */

    char out[64];
    size_t lines = 0;
    TEST_ASSERT_EQUAL_STRING("bbbbbbbbbb", nth_line(out, sizeof(out), 0, &lines));
    TEST_ASSERT_EQUAL_STRING("cccccccccc", nth_line(out, sizeof(out), 1, NULL));
    TEST_ASSERT_EQUAL_UINT(2, lines);
    TEST_ASSERT_EQUAL_UINT32(1, s_sink.dropped);
    TEST_ASSERT_EQUAL_UINT32(3, s_sink.total);
}

/* A runaway printf must cost one line, not the buffer: the head is kept (level,
   timestamp and tag live there) and the tail is discarded up to the newline. */
static void test_overlong_line_is_truncated_not_dropped(void)
{
    reset(sizeof(s_storage));
    char big[LOG_SINK_LINE_MAX * 3];
    memset(big, 'x', sizeof(big) - 1);
    big[sizeof(big) - 1] = '\0';
    write_str(big);
    write_str("\nnext\n");

    char out[sizeof(s_storage)];
    size_t lines = 0;
    const char *first = nth_line(out, sizeof(out), 0, &lines);
    TEST_ASSERT_EQUAL_UINT(2, lines);
    TEST_ASSERT_EQUAL_UINT(LOG_SINK_LINE_MAX - 1, strlen(first));
    TEST_ASSERT_EQUAL_STRING("next", nth_line(out, sizeof(out), 1, NULL));
}

/* A short destination keeps the tail of the log, not the head. */
static void test_snapshot_keeps_the_newest_lines_when_short(void)
{
    reset(sizeof(s_storage));
    write_str("one\n");
    write_str("two\n");
    write_str("three\n");

    char out[12]; /* room for "two\0three\0" but not "one\0" as well */
    size_t lines = 0;
    size_t bytes = log_sink_snapshot(&s_sink, out, sizeof(out), &lines);
    TEST_ASSERT_EQUAL_UINT(2, lines);
    TEST_ASSERT_EQUAL_UINT(10, bytes);
    TEST_ASSERT_EQUAL_STRING("two", out);
    TEST_ASSERT_EQUAL_STRING("three", out + 4);
}

/* An undersized destination that cannot hold even the newest line reports
   nothing rather than a partial line. */
static void test_snapshot_reports_nothing_when_no_line_fits(void)
{
    reset(sizeof(s_storage));
    write_str("a long enough line\n");

    char out[4];
    size_t lines = 99;
    TEST_ASSERT_EQUAL_UINT(0, log_sink_snapshot(&s_sink, out, sizeof(out), &lines));
    TEST_ASSERT_EQUAL_UINT(0, lines);
}

/* Every entry point takes NULLs without faulting: the ESP glue calls these
   before init when the boot-time allocation failed. */
static void test_null_safety(void)
{
    log_sink_init(NULL, NULL, 0);
    log_sink_write(NULL, "x", 1);

    log_sink_t sink;
    log_sink_init(&sink, NULL, 128);
    log_sink_write(&sink, "hello\n", 6);
    TEST_ASSERT_EQUAL_UINT(0, sink.lines);

    char out[8];
    TEST_ASSERT_EQUAL_UINT(0, log_sink_snapshot(&sink, out, sizeof(out), NULL));
    TEST_ASSERT_EQUAL_UINT(0, log_sink_snapshot(NULL, out, sizeof(out), NULL));
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_lines_are_committed_on_newline);
    RUN_TEST(test_partial_line_is_not_visible_until_complete);
    RUN_TEST(test_ansi_escapes_and_cr_are_stripped);
    RUN_TEST(test_blank_lines_are_not_retained);
    RUN_TEST(test_oldest_lines_are_evicted_when_full);
    RUN_TEST(test_overlong_line_is_truncated_not_dropped);
    RUN_TEST(test_snapshot_keeps_the_newest_lines_when_short);
    RUN_TEST(test_snapshot_reports_nothing_when_no_line_fits);
    RUN_TEST(test_null_safety);
    return UNITY_END();
}
