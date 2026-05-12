#include "esp_timer.h"

static int64_t s_now_us = 0;

int64_t esp_timer_get_time(void)
{
    return s_now_us;
}

void host_clock_set(int64_t now_us)
{
    s_now_us = now_us;
}

void host_clock_advance(int64_t delta_us)
{
    s_now_us += delta_us;
}
