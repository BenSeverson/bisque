#include "ota_manager.h"

#include "esp_log.h"
#include "esp_ota_ops.h"
#include "firing_engine.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "ota_confirm";

/*
 * Runs once after boot. If the running image is awaiting verification,
 * survives a healthy-uptime window and then cancels rollback. Reaching the
 * end of the delay is itself the health proof: a boot loop or panic would
 * reboot the device before the window elapses, leaving the image
 * unconfirmed so the bootloader reverts to the previous slot.
 */
static void confirm_task(void *arg)
{
    (void)arg;

    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (esp_ota_get_state_partition(running, &state) != ESP_OK || state != ESP_OTA_IMG_PENDING_VERIFY) {
        ESP_LOGI(TAG, "Running image already confirmed; nothing to do");
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "New image pending verify; observing health for %d s", CONFIG_OTA_CONFIRM_DELAY_SECONDS);
    vTaskDelay(pdMS_TO_TICKS((TickType_t)CONFIG_OTA_CONFIRM_DELAY_SECONDS * 1000));

    /* Exercise the firing engine; a wedged controller would not return here. */
    firing_progress_t prog;
    firing_engine_get_progress(&prog);

    if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
        ESP_LOGI(TAG, "Firmware confirmed valid; rollback canceled");
    } else {
        ESP_LOGW(TAG, "Failed to mark app valid");
    }
    vTaskDelete(NULL);
}

void ota_confirm_task_start(void)
{
    xTaskCreate(confirm_task, "ota_confirm", 4096, NULL, 3, NULL);
}
