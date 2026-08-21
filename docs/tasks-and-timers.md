# Tasks and Timers

Status: **reference** — the concurrency counterpart to
[`pin-assignments.md`](pin-assignments.md). That doc is the one place the whole
pin map is written down; this is the one place the whole task and timer map is.

It exists for the same reason: the schedule is spread across files that must
agree, and two of them have already drifted apart (see
[Discrepancies](#discrepancies)).

| File | Owns |
|---|---|
| `components/app_config/include/app_config.h` | `APP_TASK_*_PRIO` / `APP_TASK_*_STACK` for the control tasks |
| `main/main.c` | Creates the control tasks, the display task, and the housekeeping tasks; owns core assignment |
| Each component's `.c` | Creates its own worker (`wifi_manager`, `ota`, `ws_handler`, `notification_task`) with locally-defined priority and stack |
| `sdkconfig` | `CONFIG_ESP_TIMER_TASK_AFFINITY_*` — which core runs every `esp_timer` callback |

## Core allocation

The split is deliberate and load-bearing: **core 1 is the control domain, core 0
is UI and network.** Real-time supervision must not be scheduled behind a Wi-Fi
stack that can stall for tens of seconds (#250).

- **Core 1** — `safety`, `temp_read`, `firing`, created via `start_control_task()`
  ([`main.c:33`](../main/main.c#L33)), which hardcodes core 1.
- **Core 0** — `display`, `status_led`, `notify`, `ws_broadcast`, `wifi_worker`,
  **and the `esp_timer` task**.
- **Unpinned** (`tskNO_AFFINITY`, scheduler picks) — `httpd`, `ota_install`,
  `ota_confirm`.

Note that `display` is on core **0** despite being created alongside the control
tasks in boot order — it is UI, not control.

## FreeRTOS tasks

Priorities are FreeRTOS numbers: **higher preempts lower**, `configMAX_PRIORITIES`
is 25.

| Task | Prio | Core | Stack | Cadence | Created |
|---|---|---|---|---|---|
| `safety` | 6 | 1 | 4096 | 500 ms, `xTaskDelayUntil` | [`main.c:116`](../main/main.c#L116) |
| `httpd` | **5** | any | 12288 | event-driven | [`web_server.c:188`](../components/web_server/web_server.c#L188) |
| `temp_read` | 5 | 1 | 4096 | 250 ms, `xTaskDelayUntil` | [`main.c:117`](../main/main.c#L117) |
| `ota_install` | 5 | any | 8192 | transient — one per update, then exits | [`ota_manager.c:343`](../components/ota/ota_manager.c#L343) |
| `firing` | 4 | 1 | 8192 | 1000 ms, **interruptible** (see below) | [`main.c:118`](../main/main.c#L118) |
| `ota_confirm` | 3 | any | 4096 | transient — one healthy-uptime window after an OTA boot | [`ota_confirm.c:83`](../components/ota/ota_confirm.c#L83) |
| `display` | 2 | 0 | 16384 | ~30 ms LVGL loop | [`main.c:133`](../main/main.c#L133) |
| `ws_broadcast` | 2 | 0 | 4096 | blocks on `ulTaskNotifyTake(portMAX_DELAY)` | [`ws_handler.c:300`](../components/web_server/ws_handler.c#L300) |
| `status_led` | 1 | 0 | 2048 | 250 ms | [`main.c:221`](../main/main.c#L221) |
| `notify` | 1 | 0 | 6144 | blocks on `xQueueReceive(portMAX_DELAY)` | [`notification_task.c:46`](../components/web_server/notification_task.c#L46) |
| `wifi_worker` | 1 | 0 | 4096 | 1000 ms queue timeout | [`wifi_manager.c:359`](../components/wifi_manager/wifi_manager.c#L359) |

Three are conditional, and their absence is logged rather than fatal: `display`
(skipped if `display_init()` fails — the controller runs headless), `status_led`
(skipped if the LED did not initialize), and `ota_confirm` (only after an OTA
boot). `display` is the one exception to "non-fatal": if `xTaskCreatePinnedToCore`
itself fails for it, `main.c` calls `abort()`, because a 16 KiB stack allocation
failure otherwise produces a UI that silently never starts.

**`firing` is not a fixed 1 Hz sleeper.** `wait_until_next_tick()`
([`firing_engine.c:1677`](../components/firing_engine/firing_engine.c#L1677))
waits on the command queue with the *remaining* time as its timeout, so a queued
command wakes it early and the real call rate into `safety_set_ssr()` is ≥ 1 Hz.
That only ever helps the 3 s control-loop heartbeat in `safety_task`.

## esp_timer callbacks

Both run in the shared `esp_timer` task: **priority 22** (`ESP_TASK_TIMER_PRIO`
= `configMAX_PRIORITIES - 3`), **core 0** (`CONFIG_ESP_TIMER_TASK_AFFINITY_CPU0=y`),
3584-byte stack. Priority 22 is above every task in the table above, so a callback
that blocks or runs long delays everything else on core 0 — keep them short and
non-blocking.

| Timer | Period | Callback | Created |
|---|---|---|---|
| `ssr_window` | 100 ms | `ssr_timer_cb` → `ssr_window_apply()` (time-proportional SSR window) then `wdt_kick_step()` (toggles the watchdog kick, so a 5 Hz square wave) | [`safety.c:280`](../components/safety/safety.c#L280) |
| `ws_broadcast` | 1000 ms | `ws_broadcast_timer_cb` → notifies the `ws_broadcast` task | [`main.c:230`](../main/main.c#L230) |

## LVGL timer

| Timer | Period | Callback |
|---|---|---|
| `dashboard_tick_cb` | 500 ms | [`display_task.c:133`](../components/display/display_task.c#L133) |

This is **not** an `esp_timer`. LVGL timers run inside `lv_timer_handler()` on the
`display` task, so they inherit its priority (2) and core (0), and they hold the
LVGL lock. Adding work here cannot preempt control tasks.

## The supervision chain

Priority order is not arbitrary — it encodes who vouches for whom.

```
esp_timer (22, core 0)   ssr_window_apply() — drives the SSR pin from stored duty
        ^ reads
safety   (6,  core 1)    over-temp, TC fault, stale reading, control-loop heartbeat
        ^ supervises
firing   (4,  core 1)    PID → safety_set_ssr() every tick
```

- `safety` is the **highest-priority task pinned to core 1**, so nothing in the
  control domain can starve it. Only the `esp_timer` task (microseconds of work)
  and flash-cache stalls can delay it.
- If `firing` stops calling `safety_set_ssr()` for 3 s *while duty > 0*,
  `safety_task` forces the SSR pin low and latches an emergency stop
  ([`safety.c:546`](../components/safety/safety.c#L546)).
- `ssr_window_apply()` is the only writer of the SSR pin outside the emergency
  path. It re-checks the emergency latch, `s_supervised`, and the lid gate on
  every 100 ms tick, so those interlocks hold even if a task wedges.

**Flash operations stall both cores.** An SPI-flash erase or write disables the
instruction cache, so code executing from flash pauses on core 0 *and* core 1 —
including the `esp_timer` callbacks. `firing_engine.c` calls `nvs_commit()` on the
firing path. This is the one mechanism that can delay `safety` and the timers
together, and it is why anything with a hardware timeout budget must tolerate a
stall on the order of tens to hundreds of milliseconds.

## Discrepancies

**`APP_TASK_HTTPD_PRIO` (3) is dead and wrong.** It is defined in
[`app_config.h:75`](../components/app_config/include/app_config.h#L75) and
referenced nowhere. `web_server_start()` uses `HTTPD_DEFAULT_CONFIG()` and
overrides only `uri_match_fn`, `max_uri_handlers`, `stack_size`,
`lru_purge_enable` and `max_open_sockets` — never `task_priority` or `core_id`.
So the HTTP server actually runs at **priority 5** (`tskIDLE_PRIORITY + 5`),
unpinned, not priority 3.

That is one above `firing` (4), which means a heavy request — an OTA upload, a
large SPIFFS read — can preempt the control loop if the scheduler places it on
core 1. `safety` at 6 still outranks it, so supervision is unaffected. Either
delete the macro or pass it to `config.task_priority`; do not trust it as-is.

## When adding a task or timer

1. Control-domain work (anything that can energize or supervise the SSR) goes on
   **core 1** via `start_control_task()`, with its priority in `app_config.h`.
2. UI, network and telemetry go on **core 0**.
3. `esp_timer` callbacks run at priority 22 — do no blocking work, take no
   long-held locks, and remember they are on core 0.
4. Update this file, and check the priority against the supervision chain above:
   nothing that commands heat should outrank `safety`.
