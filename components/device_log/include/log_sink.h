#pragma once

/**
 * Line-oriented log ring buffer — the pure half of the device log (#189).
 *
 * Nothing in here touches ESP-IDF, FreeRTOS or malloc: the caller supplies the
 * storage and does its own locking, which is what makes the whole thing
 * testable from tests/host/test_log_sink.c. device_log.c is the thin ESP glue
 * that owns the storage, the mutex and the esp_log_set_vprintf() hook.
 *
 * Storage layout is a packed sequence of NUL-terminated lines, oldest first.
 * That costs an occasional memmove when the oldest line is evicted, and buys a
 * snapshot that is a plain byte copy plus a walk over terminators — no
 * wraparound handling in the reader, and no partial line ever visible.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Longest single line retained. Anything longer is truncated, not dropped. */
#define LOG_SINK_LINE_MAX 200

typedef struct {
    char *storage;    /* caller-owned, `capacity` bytes */
    size_t capacity;  /* bytes of `storage` */
    size_t used;      /* bytes in use, terminators included */
    size_t lines;     /* complete lines currently retained */
    uint32_t dropped; /* lines evicted to make room since init */
    uint32_t total;   /* lines appended since init */

    /* Assembly area for the current line. The vprintf hook is handed whatever
       chunk the caller printed — usually one whole line, but not by contract —
       so bytes are accumulated here and only committed on a newline. */
    char pending[LOG_SINK_LINE_MAX];
    size_t pending_len;
    uint8_t esc_state; /* ANSI escape parser: 0 none, 1 saw ESC, 2 in CSI */
    bool truncating;   /* current line overflowed; drop until the newline */
} log_sink_t;

/** Bind `sink` to `capacity` bytes of caller-owned storage and reset it. */
void log_sink_init(log_sink_t *sink, char *storage, size_t capacity);

/**
 * Feed raw log output in. Splits on '\n', drops '\r' and ANSI colour escapes,
 * and commits each completed line to the ring, evicting the oldest lines when
 * there is not enough room.
 *
 * A line longer than LOG_SINK_LINE_MAX-1 is committed truncated and the rest of
 * it discarded, so one runaway printf can't eat the whole buffer.
 */
void log_sink_write(log_sink_t *sink, const char *data, size_t len);

/**
 * Feed one already-formatted log record.
 *
 * `complete` is false when the formatter truncated the record — which takes the
 * record's own trailing newline with it. Without that flag the sink is left
 * mid-line and still in its drop-the-tail state, so it swallows the whole of
 * the *next* record and uses that record's newline to commit this one: one
 * oversized message costs two log lines, and the second loss is invisible.
 */
void log_sink_write_record(log_sink_t *sink, const char *data, size_t len, bool complete);

/**
 * Copy the retained lines into `dst` as a packed NUL-separated block, oldest
 * first, and return the number of bytes written.
 *
 * When `dst` is too small the *oldest* lines are dropped rather than the
 * newest: a truncated diagnostic bundle should hold whatever happened just
 * before the operator hit the button. `*out_lines` (optional) receives the
 * number of lines actually copied.
 */
size_t log_sink_snapshot(const log_sink_t *sink, char *dst, size_t dst_capacity, size_t *out_lines);

#ifdef __cplusplus
}
#endif
