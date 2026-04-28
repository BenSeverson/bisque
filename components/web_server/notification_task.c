#include "web_server.h"
#include "firing_engine.h"
#include "safety.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

static const char *TAG = "notify";

static void notification_task(void *arg)
{
    (void)arg;
    QueueHandle_t q = firing_engine_get_event_queue();
    if (!q) {
        ESP_LOGE(TAG, "no event queue, exiting");
        vTaskDelete(NULL);
        return;
    }

    for (;;) {
        firing_event_t evt;
        if (xQueueReceive(q, &evt, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        switch (evt.kind) {
        case FIRING_EVENT_COMPLETE:
            ESP_LOGI(TAG, "firing complete: profile=%s peak=%.1fC dur=%us", evt.profile_id, evt.peak_temp,
                     (unsigned)evt.duration_s);
            safety_trigger_alarm(1);
            send_webhook_event("complete", evt.profile_id, evt.peak_temp, evt.duration_s);
            break;
        case FIRING_EVENT_ERROR:
            ESP_LOGW(TAG, "firing error: profile=%s peak=%.1fC dur=%us", evt.profile_id, evt.peak_temp,
                     (unsigned)evt.duration_s);
            safety_trigger_alarm(2);
            send_webhook_event("error", evt.profile_id, evt.peak_temp, evt.duration_s);
            break;
        }
    }
}

esp_err_t notification_task_start(void)
{
    BaseType_t ok = xTaskCreatePinnedToCore(notification_task, "notify", 6144, NULL, 1, NULL, 0);
    return (ok == pdPASS) ? ESP_OK : ESP_ERR_NO_MEM;
}
