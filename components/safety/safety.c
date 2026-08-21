#include "safety.h"
#include "safety_internal.h"
#include "wdt_kick.h"
#include "thermocouple.h"
#include "app_config.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include <math.h>

static const char *TAG = "safety";

/* Vent active below this temperature during firing */
#define VENT_MAX_TEMP_C 700.0f

/* Piezo buzzer tone driven via LEDC. The buzzer needs an AC waveform to
   produce sound; static GPIO levels won't work. 4 kHz matched the resonance
   peak of the buzzer used during bench testing — adjust if a different
   buzzer is fitted. */
#define ALARM_TONE_FREQ_HZ    4000
#define ALARM_TONE_DUTY_RES   LEDC_TIMER_10_BIT
#define ALARM_TONE_DUTY_50PCT (1U << (ALARM_TONE_DUTY_RES - 1))
#define ALARM_LEDC_TIMER      LEDC_TIMER_0
#define ALARM_LEDC_CHANNEL    LEDC_CHANNEL_0
#define ALARM_LEDC_MODE       LEDC_LOW_SPEED_MODE

static int s_ssr_pin = -1;
static int s_alarm_gpio = -1;
static int s_vent_gpio = -1;
/* Last level written to the vent pin. Read by the web/display tasks via
   safety_get_vent_state(); a plain bool written from one task and read from
   others, so volatile to keep the read out of a cached register. */
static volatile bool s_vent_active = false;
static int s_lid_gpio = -1;
/* Written by safety_task, read by the firing/web/display tasks via
   safety_get_lid_state(); volatile for the same reason s_vent_active is. */
static volatile lid_state_t s_lid_state = LID_STATE_NOT_FITTED;
static volatile bool s_lid_interlock_armed = false;
static lid_debounce_t s_lid_debounce = {.state = LID_STATE_OPEN, .close_samples = 0};
static float s_max_safe_temp = 1300.0f;
static float s_tc_offset_c = 0.0f;
static safety_trip_cause_t s_trip_cause = SAFETY_TRIP_NONE;
static EventGroupHandle_t s_event_group;
static portMUX_TYPE s_safety_mux = portMUX_INITIALIZER_UNLOCKED;

/* Time-proportional SSR state */
static float s_ssr_duty = 0.0f;
static int64_t s_ssr_window_start_us = 0;
#define SSR_WINDOW_US ((int64_t)APP_SSR_WINDOW_MS * 1000LL)

/* Re-evaluate the time-proportional window at 10 Hz so duty resolves to ~1% of
 * the window instead of the ~3 coarse levels a 1 Hz update produced. */
static esp_timer_handle_t s_ssr_timer = NULL;
#define SSR_APPLY_PERIOD_US (100LL * 1000LL)

static void ssr_timer_cb(void *arg);

/* Control-loop heartbeat: safety_set_ssr() is called every firing tick (1 Hz).
 * If it goes silent while the element is commanded on, the firing task has
 * wedged with the SSR latched — safety_task forces the output off (and trips an
 * emergency stop). 3 s ≈ three missed control ticks. */
static int64_t s_last_ssr_cmd_us = 0;
#define SSR_HEARTBEAT_TIMEOUT_US (3LL * 1000000)

/* Set once safety_task is running. Until then the SSR is hard-held off: an
 * element energized with no over-temp check, no stale-reading check and no
 * thermocouple-fault watchdog is unsupervised heat. Boot order alone used to be
 * the only thing preventing that (#250) — this makes it an invariant, so a
 * future relay self-test or resume-after-reboot path added early in app_main
 * fails safe instead of silently firing unwatched. */
static volatile bool s_supervised = false;

/* ── Hardware watchdog kick (RB-2, #307) ──────────────────────────────────
 * KILN_PIN_WDT_KICK retriggers a monostable whose output gates BOTH SSR opto
 * channels. It retriggers on EDGES, so a pin wedged at either level expires the
 * window exactly like a pin that stopped — which is the entire point.
 *
 * The kick is split across two places deliberately. safety_task stamps a
 * heartbeat at the END of each completed pass, and the existing 100 ms SSR timer
 * toggles the pin only while that stamp is fresh. Emitting the kick straight
 * from the timer would keep it toggling after safety_task died — the exact
 * failure the watchdog exists to catch — and stamping at the top of the loop
 * would mean "the loop was entered" rather than "the checks ran".
 *
 * Both cross-task variables are plain 32-bit volatiles rather than spinlocked
 * state: an aligned 32-bit load is a single instruction on the LX7 and cannot
 * tear, which is the same reasoning s_vent_active and s_lid_state already use.
 * That matters here because the alternative costs two critical sections per
 * kick — the mux plus xEventGroupGetBits() inside safety_is_emergency() — and
 * both disable interrupts. */
static int s_wdt_gpio = -1;
static bool s_wdt_level = false;
/* Milliseconds, wrapping every 49.7 days; wdt_kick_allowed() is unsigned so the
   wrap needs no special case. 0 means "no pass completed yet". */
static volatile uint32_t s_wdt_heartbeat_ms = 0;
/* Mirrors the emergency latch so the kick path never touches the event group.
   Written only by safety_emergency_stop_cause() and safety_clear_emergency(),
   the same two functions that own the bit itself. */
static volatile bool s_wdt_blocked = false;

static void alarm_tone_on(void)
{
    ledc_set_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL, ALARM_TONE_DUTY_50PCT);
    ledc_update_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL);
}

static void alarm_tone_off(void)
{
    ledc_set_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL, 0);
    ledc_update_duty(ALARM_LEDC_MODE, ALARM_LEDC_CHANNEL);
}

/* The only place the vent pin is written. Pin and cache move together here so
 * they cannot drift: safety_get_vent_state() is what the API and the LCD show,
 * and an emergency stop that drove the GPIO low directly left both reporting a
 * fan that had already been cut. No-op when no vent GPIO is configured. */
static void vent_write(bool on)
{
    if (s_vent_gpio < 0) {
        return;
    }
    gpio_set_level(s_vent_gpio, on ? 1 : 0);
    s_vent_active = on;
}

/* Polarity-corrected "is the lid open" reading, straight off the pin. The
   mapping itself lives in safety_helpers.c so the host tests can reach it. */
static bool lid_raw_open(void)
{
    return safety_lid_level_is_open(gpio_get_level(s_lid_gpio), APP_LID_SWITCH_OPEN_IS_LOW);
}

/* True when the interlock should be holding the element off right now. */
static bool lid_blocks_output(void)
{
    return s_lid_interlock_armed && s_lid_state == LID_STATE_OPEN;
}

lid_state_t safety_get_lid_state(void)
{
    return s_lid_state;
}

void safety_set_lid_interlock_armed(bool armed)
{
    s_lid_interlock_armed = armed;
}

void safety_init_io(int alarm_gpio, int vent_gpio, int lid_gpio)
{
    s_alarm_gpio = alarm_gpio;
    s_vent_gpio = vent_gpio;
    s_lid_gpio = lid_gpio;

    if (alarm_gpio >= 0) {
        const ledc_timer_config_t timer = {
            .speed_mode = ALARM_LEDC_MODE,
            .timer_num = ALARM_LEDC_TIMER,
            .duty_resolution = ALARM_TONE_DUTY_RES,
            .freq_hz = ALARM_TONE_FREQ_HZ,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        const ledc_channel_config_t channel = {
            .speed_mode = ALARM_LEDC_MODE,
            .channel = ALARM_LEDC_CHANNEL,
            .timer_sel = ALARM_LEDC_TIMER,
            .intr_type = LEDC_INTR_DISABLE,
            .gpio_num = alarm_gpio,
            .duty = 0,
            .hpoint = 0,
        };
        ESP_ERROR_CHECK(ledc_timer_config(&timer));
        ESP_ERROR_CHECK(ledc_channel_config(&channel));
        ESP_LOGI(TAG, "Alarm GPIO %d configured (LEDC %d Hz tone)", alarm_gpio, ALARM_TONE_FREQ_HZ);
    }

    if (vent_gpio >= 0) {
        gpio_config_t io = {
            .pin_bit_mask = (1ULL << vent_gpio),
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_ENABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&io);
        vent_write(false); /* s_vent_gpio is already set, above */
        ESP_LOGI(TAG, "Vent GPIO %d configured", vent_gpio);
    }

    if (lid_gpio >= 0) {
        gpio_config_t io = {
            .pin_bit_mask = (1ULL << lid_gpio),
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&io);
        /* Start from "open" and let safety_task debounce its way to the truth.
           Assuming closed here would allow one unsupervised SSR window against a
           lid that might be up. */
        s_lid_state = LID_STATE_OPEN;
        s_lid_debounce.state = LID_STATE_OPEN;
        s_lid_debounce.close_samples = 0;
        ESP_LOGI(TAG, "Lid switch GPIO %d configured (%s = open)", lid_gpio,
                 APP_LID_SWITCH_OPEN_IS_LOW ? "low" : "high");
    } else {
        s_lid_state = LID_STATE_NOT_FITTED;
    }
}

void safety_trigger_alarm(int pattern)
{
    if (s_alarm_gpio < 0) {
        return;
    }

    switch (pattern) {
    case 0: /* short beep */
        alarm_tone_on();
        vTaskDelay(pdMS_TO_TICKS(200));
        alarm_tone_off();
        break;
    case 1: /* long beep (completion) */
        for (int i = 0; i < 3; i++) {
            alarm_tone_on();
            vTaskDelay(pdMS_TO_TICKS(500));
            alarm_tone_off();
            vTaskDelay(pdMS_TO_TICKS(200));
        }
        break;
    case 2: /* error pattern */
        for (int i = 0; i < 5; i++) {
            alarm_tone_on();
            vTaskDelay(pdMS_TO_TICKS(100));
            alarm_tone_off();
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        break;
    default:
        alarm_tone_on();
        vTaskDelay(pdMS_TO_TICKS(300));
        alarm_tone_off();
        break;
    }
}

void safety_update_vent(bool is_firing, float current_temp_c)
{
    /* Before anything else, so a kiln with no vent relay — the default — never
       reaches into the event group below. safety_init() happens to run before
       safety_init_io() today, but nothing here needs to depend on that. */
    if (s_vent_gpio < 0) {
        return;
    }
    /* Respect a latched emergency stop, the same way safety_set_ssr() does.
       safety_emergency_stop_cause() cuts the vent, but firing_tick() drives the
       vent before it checks for the stop — so the tick that first observes an
       emergency still arrives here with is_firing == true and, below 700°C,
       switched the relay straight back on for a second. The policy that an
       emergency stop means the vent is off belongs here, next to the trip that
       states it, rather than in the caller's statement order. */
    if (safety_is_emergency()) {
        vent_write(false);
        return;
    }
    /* Vent relay on during firing at temperatures below 700°C */
    vent_write(is_firing && current_temp_c < VENT_MAX_TEMP_C);
}

vent_state_t safety_get_vent_state(void)
{
    if (s_vent_gpio < 0) {
        return VENT_STATE_NOT_FITTED;
    }
    return s_vent_active ? VENT_STATE_ON : VENT_STATE_OFF;
}

esp_err_t safety_init(int ssr_pin, float max_safe_temp)
{
    s_ssr_pin = ssr_pin;
    s_max_safe_temp = (max_safe_temp < APP_HARDWARE_MAX_TEMP_C) ? max_safe_temp : APP_HARDWARE_MAX_TEMP_C;

    /* Configure SSR GPIO as output, start LOW (off) */
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << ssr_pin),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t ret = gpio_config(&io_conf);
    if (ret != ESP_OK) {
        return ret;
    }

    gpio_set_level(ssr_pin, 0);

    s_event_group = xEventGroupCreate();
    if (!s_event_group) {
        return ESP_ERR_NO_MEM;
    }

    /* Periodic timer that re-applies the time-proportional SSR window. */
    const esp_timer_create_args_t ssr_timer_args = {
        .callback = ssr_timer_cb,
        .name = "ssr_window",
    };
    esp_err_t terr = esp_timer_create(&ssr_timer_args, &s_ssr_timer);
    if (terr != ESP_OK) {
        vEventGroupDelete(s_event_group);
        s_event_group = NULL;
        return terr;
    }
    terr = esp_timer_start_periodic(s_ssr_timer, SSR_APPLY_PERIOD_US);
    if (terr != ESP_OK) {
        esp_timer_delete(s_ssr_timer);
        s_ssr_timer = NULL;
        vEventGroupDelete(s_event_group);
        s_event_group = NULL;
        return terr;
    }

    ESP_LOGI(TAG, "Safety initialized: SSR pin=%d, max_safe_temp=%.0f°C", ssr_pin, s_max_safe_temp);
    return ESP_OK;
}

EventGroupHandle_t safety_get_event_group(void)
{
    return s_event_group;
}

void safety_emergency_stop_cause(safety_trip_cause_t cause)
{
    if (s_ssr_pin >= 0) {
        gpio_set_level(s_ssr_pin, 0);
    }
    /* Turn off vent on emergency stop */
    vent_write(false);
    portENTER_CRITICAL(&s_safety_mux);
    s_ssr_duty = 0.0f;
    /* Latch the first cause — safety_task re-trips every 500 ms while a fault
       persists, and the engine reads the cause on the first emergency tick. */
    if (s_trip_cause == SAFETY_TRIP_NONE) {
        s_trip_cause = cause;
    }
    portEXIT_CRITICAL(&s_safety_mux);

    s_wdt_blocked = true;
    xEventGroupSetBits(s_event_group, SAFETY_BIT_EMERGENCY_STOP);
    ESP_LOGE(TAG, "EMERGENCY STOP activated (cause=%d)", (int)cause);
}

void safety_emergency_stop(void)
{
    safety_emergency_stop_cause(SAFETY_TRIP_OTHER);
}

safety_trip_cause_t safety_get_trip_cause(void)
{
    safety_trip_cause_t cause;
    portENTER_CRITICAL(&s_safety_mux);
    cause = s_trip_cause;
    portEXIT_CRITICAL(&s_safety_mux);
    return cause;
}

void safety_clear_emergency(void)
{
    portENTER_CRITICAL(&s_safety_mux);
    s_trip_cause = SAFETY_TRIP_NONE;
    portEXIT_CRITICAL(&s_safety_mux);
    s_wdt_blocked = false;
    xEventGroupClearBits(s_event_group, SAFETY_BIT_EMERGENCY_STOP);
    ESP_LOGI(TAG, "Emergency stop cleared");
}

bool safety_is_emergency(void)
{
    EventBits_t bits = xEventGroupGetBits(s_event_group);
    return (bits & SAFETY_BIT_EMERGENCY_STOP) != 0;
}

void safety_set_max_temp(float max_safe_temp)
{
    portENTER_CRITICAL(&s_safety_mux);
    s_max_safe_temp = (max_safe_temp < APP_HARDWARE_MAX_TEMP_C) ? max_safe_temp : APP_HARDWARE_MAX_TEMP_C;
    portEXIT_CRITICAL(&s_safety_mux);
}

float safety_get_max_temp(void)
{
    float val;
    portENTER_CRITICAL(&s_safety_mux);
    val = s_max_safe_temp;
    portEXIT_CRITICAL(&s_safety_mux);
    return val;
}

void safety_set_tc_offset(float offset_c)
{
    portENTER_CRITICAL(&s_safety_mux);
    s_tc_offset_c = offset_c;
    portEXIT_CRITICAL(&s_safety_mux);
}

void safety_init_wdt(int wdt_gpio)
{
    s_wdt_gpio = wdt_gpio;
    if (wdt_gpio < 0) {
        ESP_LOGW(TAG, "No WDT kick pin configured; the board needs the SJ2 "
                      "WDT DEFEAT jumper fitted or it will not heat");
        return;
    }
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << wdt_gpio),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&io));
    s_wdt_level = false;
    gpio_set_level(wdt_gpio, 0);
    ESP_LOGI(TAG, "WDT kick on GPIO %d (%u ms period)", wdt_gpio, (unsigned)WDT_KICK_PERIOD_MS);
}

/* One kick tick, called from the 100 ms SSR timer. Toggling on every call makes
 * a 5 Hz square wave, so the monostable sees a rising edge every 200 ms. */
static void wdt_kick_step(void)
{
    if (s_wdt_gpio < 0) {
        return;
    }
    uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);
    if (!wdt_kick_allowed(now_ms, s_wdt_heartbeat_ms, s_wdt_blocked)) {
        /* Stop toggling and leave the level where it is. Do NOT drive it to a
           defined level "for safety" — the monostable retriggers on edges, so a
           held level is already indistinguishable from a stopped one, and
           pretending otherwise invites someone to add a gpio_set_level here. */
        return;
    }
    s_wdt_level = !s_wdt_level;
    gpio_set_level(s_wdt_gpio, s_wdt_level ? 1 : 0);
}

/* Drive the SSR GPIO from the stored duty using the time-proportional window.
 * Called both from safety_set_ssr() (for immediate response when the control
 * loop updates the duty) and from a periodic timer at SSR_APPLY_PERIOD_US so
 * the on/off edge lands at the right point within the window instead of only at
 * the 1 Hz control cadence — that 1 Hz sampling collapsed the output to a few
 * coarse duty levels. */
static void ssr_window_apply(void)
{
    if (s_ssr_pin < 0) {
        return;
    }
    if (safety_is_emergency() || !s_supervised || lid_blocks_output()) {
        gpio_set_level(s_ssr_pin, 0);
        return;
    }

    int64_t now = esp_timer_get_time();
    float duty;
    portENTER_CRITICAL(&s_safety_mux);
    duty = s_ssr_duty;
    int64_t elapsed = now - s_ssr_window_start_us;
    if (elapsed >= SSR_WINDOW_US) {
        s_ssr_window_start_us = now;
        elapsed = 0;
    }
    portEXIT_CRITICAL(&s_safety_mux);

    int64_t on_time = (int64_t)(duty * SSR_WINDOW_US);
    gpio_set_level(s_ssr_pin, (elapsed < on_time) ? 1 : 0);
}

static void ssr_timer_cb(void *arg)
{
    (void)arg;
    ssr_window_apply();
    wdt_kick_step();
}

void safety_set_ssr(float duty)
{
    if (safety_is_emergency()) {
        gpio_set_level(s_ssr_pin, 0);
        return;
    }

    /* Discard the command outright, don't just decline to apply it.
       ssr_window_apply() refuses to drive the pin high while unsupervised, but
       s_supervised latches true for good — so a nonzero duty left in s_ssr_duty
       would be replayed by the periodic window timer the moment safety_task
       arms, energizing the element with no fresh command behind it. (The
       emergency-stop path above can leave a stale duty safely because
       ssr_window_apply() re-checks that flag every tick and it can clear.) */
    if (!s_supervised && duty > 0.0f) {
        ESP_LOGE(TAG, "SSR commanded to %.2f before safety_task started — discarded", duty);
        duty = 0.0f;
    }

    if (duty < 0.0f) {
        duty = 0.0f;
    }
    if (duty > 1.0f) {
        duty = 1.0f;
    }

    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&s_safety_mux);
    s_ssr_duty = duty;
    s_last_ssr_cmd_us = now; /* feed the control-loop heartbeat */
    portEXIT_CRITICAL(&s_safety_mux);

    /* Apply immediately for low latency; the periodic timer keeps the window
       edge accurate between control updates. */
    ssr_window_apply();
}

float safety_get_ssr_duty(void)
{
    /* Emergency stop zeroes s_ssr_duty as it trips (safety_emergency_stop), and
       safety_set_ssr() discards a nonzero duty while unsupervised, so the stored
       value already accounts for both — no second check needed here. */
    portENTER_CRITICAL(&s_safety_mux);
    float duty = s_ssr_duty;
    portEXIT_CRITICAL(&s_safety_mux);
    return duty;
}

void safety_task(void *param)
{
    (void)param;
    TickType_t last_wake = xTaskGetTickCount();
    /* Seed the fault-debounce origin at task start: this task outranks
       temp_read_task, so the first few ticks see no reading at all and a fault
       present at boot must still get the full grace period. */
    int64_t last_valid_reading_us = esp_timer_get_time();

    /* Release the SSR interlock: from here on the element has a watchdog. */
    s_supervised = true;

    ESP_LOGI(TAG, "safety_task started");

    for (;;) {
        thermocouple_reading_t reading;
        thermocouple_get_latest(&reading);

        int64_t now = esp_timer_get_time();

        /* Lid switch. Sampled before the thermocouple work so an open lid cuts
           heat on this tick rather than the next one; ssr_window_apply() is what
           actually holds the pin low, within one 100 ms window. */
        if (s_lid_gpio >= 0) {
            lid_state_t lid = safety_lid_debounce_step(&s_lid_debounce, lid_raw_open());
            if (lid != s_lid_state) {
                ESP_LOGI(TAG, "Lid %s", lid == LID_STATE_OPEN ? "opened" : "closed");
            }
            s_lid_state = lid;
        }

        safety_tc_state_t tc_state = safety_tc_watchdog_step(&reading, now, &last_valid_reading_us);

        if (tc_state == SAFETY_TC_FAULT_TRIP) {
            ESP_LOGE(TAG, "Thermocouple fault persisted >5s, emergency stop");
            xEventGroupSetBits(s_event_group, SAFETY_BIT_TEMP_FAULT);
            safety_emergency_stop_cause(SAFETY_TRIP_TC_FAULT);
        } else if (tc_state == SAFETY_TC_OK) {
            xEventGroupClearBits(s_event_group, SAFETY_BIT_TEMP_FAULT);

            /* Over-temperature check. Compare the calibration-corrected
             * temperature against the user limit — the control loop acts on the
             * corrected value, so safety must too or a nonzero offset lets the
             * kiln run hotter than max_safe_temp before tripping. The absolute
             * hardware ceiling stays on the raw reading as a backstop. */
            float max_temp, offset;
            portENTER_CRITICAL(&s_safety_mux);
            max_temp = s_max_safe_temp;
            offset = s_tc_offset_c;
            portEXIT_CRITICAL(&s_safety_mux);

            float corrected = reading.temperature_c + offset;
            if (corrected > max_temp || reading.temperature_c > APP_HARDWARE_MAX_TEMP_C) {
                ESP_LOGE(TAG, "Over-temp: %.1f°C (corrected %.1f°C) exceeds limit %.1f°C", reading.temperature_c,
                         corrected, max_temp);
                safety_emergency_stop_cause(SAFETY_TRIP_OVER_TEMP);
            }
        }

        /* Check for stale reading (no new data for >5 seconds). Skipped when the
         * watchdog already tripped on a persistent fault this tick — a reading
         * that is both faulted and stale would otherwise trip TC_FAULT twice.
         * Harmless (the cause latches first-wins) but redundant (#217). */
        if (tc_state != SAFETY_TC_FAULT_TRIP && reading.timestamp_us > 0 &&
            (now - reading.timestamp_us) > TEMP_FAULT_TIMEOUT_US) {
            ESP_LOGE(TAG, "No thermocouple data for >5s, emergency stop");
            xEventGroupSetBits(s_event_group, SAFETY_BIT_TEMP_FAULT);
            safety_emergency_stop_cause(SAFETY_TRIP_TC_FAULT);
        }

        /* Control-loop heartbeat. safety_set_ssr() runs every firing tick; if it
         * stops while the element is commanded on, the firing task has wedged
         * with the SSR latched. Force the output off and escalate. A stale
         * heartbeat with the last duty at 0 (idle/paused) is harmless, so only
         * trip the emergency stop when heat was actually being commanded. */
        float last_duty;
        int64_t last_cmd_us;
        portENTER_CRITICAL(&s_safety_mux);
        last_duty = s_ssr_duty;
        last_cmd_us = s_last_ssr_cmd_us;
        portEXIT_CRITICAL(&s_safety_mux);
        if (last_cmd_us != 0 && (now - last_cmd_us) > SSR_HEARTBEAT_TIMEOUT_US) {
            if (s_ssr_pin >= 0) {
                gpio_set_level(s_ssr_pin, 0);
            }
            if (last_duty > 0.0f && !safety_is_emergency()) {
                ESP_LOGE(TAG, "Control loop stalled (%lldms since last SSR command, duty=%.2f), emergency stop",
                         (long long)((now - last_cmd_us) / 1000), last_duty);
                safety_emergency_stop();
            }
        }

        /* Every check above has run, so this pass is complete — stamp the
           heartbeat that lets the SSR timer keep kicking the hardware watchdog.
           Deliberately the last statement in the loop body: at the top it would
           mean "the loop was entered", which is not the same claim. */
        s_wdt_heartbeat_ms = (uint32_t)(esp_timer_get_time() / 1000);

        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(500));
    }
}
