#include "log_sink.h"
#include <string.h>

void log_sink_init(log_sink_t *sink, char *storage, size_t capacity)
{
    if (!sink) {
        return;
    }
    memset(sink, 0, sizeof(*sink));
    sink->storage = storage;
    sink->capacity = storage ? capacity : 0;
}

/** Drop the oldest retained line. Returns false when there is nothing left. */
static bool evict_oldest(log_sink_t *sink)
{
    if (sink->lines == 0) {
        return false;
    }
    size_t n = strlen(sink->storage) + 1;
    if (n > sink->used) {
        n = sink->used;
    }
    memmove(sink->storage, sink->storage + n, sink->used - n);
    sink->used -= n;
    sink->lines--;
    sink->dropped++;
    return true;
}

/** Commit `pending` as a line, making room for it first. */
static void commit_pending(log_sink_t *sink)
{
    size_t len = sink->pending_len;
    sink->pending_len = 0;
    sink->truncating = false;

    if (len == 0 || sink->capacity == 0) {
        /* A blank line carries nothing a reader can use, and the ESP log emits
           one on every early-boot banner. */
        return;
    }
    if (len + 1 > sink->capacity) {
        len = sink->capacity - 1;
    }
    while (sink->used + len + 1 > sink->capacity) {
        if (!evict_oldest(sink)) {
            break;
        }
    }
    if (sink->used + len + 1 > sink->capacity) {
        return; /* unreachable while capacity >= len + 1, but never overrun */
    }

    memcpy(sink->storage + sink->used, sink->pending, len);
    sink->storage[sink->used + len] = '\0';
    sink->used += len + 1;
    sink->lines++;
    sink->total++;
}

void log_sink_write(log_sink_t *sink, const char *data, size_t len)
{
    if (!sink || !data) {
        return;
    }
    for (size_t i = 0; i < len; i++) {
        char c = data[i];

        /* ANSI colour runs: "ESC [ params final", where final is any byte in
           '@'..'~'. Stripped rather than escaped — the log is JSON now, and a
           control byte in it is noise for every consumer.

           The '[' is itself inside that final-byte range, so the intro has to
           be consumed as its own state; treating it as a terminator ends the
           escape immediately and leaks "0;32m" into the line. */
        if (sink->esc_state == 1) {
            sink->esc_state = (c == '[') ? 2 : 0; /* anything else is a 2-byte escape */
            continue;
        }
        if (sink->esc_state == 2) {
            /* A newline inside an escape means the sequence was cut short —
               end it here rather than swallowing the rest of the log. */
            if (c == '\n') {
                sink->esc_state = 0;
            } else {
                if (c >= '@' && c <= '~') {
                    sink->esc_state = 0;
                }
                continue;
            }
        }
        if (c == '\033') {
            sink->esc_state = 1;
            continue;
        }

        if (c == '\n') {
            commit_pending(sink);
            continue;
        }
        if (c == '\r' || c == '\0') {
            continue;
        }
        if (sink->truncating) {
            continue;
        }
        if (sink->pending_len + 1 >= sizeof(sink->pending)) {
            /* Keep the head of the line — the level, timestamp and tag are the
               part worth having — and discard the tail up to the newline. */
            sink->truncating = true;
            continue;
        }
        sink->pending[sink->pending_len++] = c;
    }
}

void log_sink_write_record(log_sink_t *sink, const char *data, size_t len, bool complete)
{
    log_sink_write(sink, data, len);
    if (sink && !complete) {
        /* Terminate the record the formatter cut short. Feeding the newline it
           lost commits what survived and clears `truncating`, so the next
           record starts a line of its own instead of being eaten as this
           one's tail. */
        log_sink_write(sink, "\n", 1);
    }
}

size_t log_sink_snapshot(const log_sink_t *sink, char *dst, size_t dst_capacity, size_t *out_lines)
{
    if (out_lines) {
        *out_lines = 0;
    }
    if (!sink || !dst || dst_capacity == 0 || sink->used == 0) {
        return 0;
    }

    /* Start at the oldest line that still fits, so a small destination keeps
       the newest lines rather than the oldest. */
    size_t start = 0;
    while (sink->used - start > dst_capacity) {
        size_t n = strlen(sink->storage + start) + 1;
        start += n;
        if (start >= sink->used) {
            return 0;
        }
    }

    size_t bytes = sink->used - start;
    memcpy(dst, sink->storage + start, bytes);

    if (out_lines) {
        size_t count = 0;
        for (size_t i = 0; i < bytes; i++) {
            if (dst[i] == '\0') {
                count++;
            }
        }
        *out_lines = count;
    }
    return bytes;
}
