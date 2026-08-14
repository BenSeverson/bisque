#include "ota_manager.h"

#include "esp_log.h"
#include "esp_ota_ops.h"
#include "firing_engine.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "ota_confirm";

/* How long to keep trying for the OTA-busy flag before leaving the image
   unconfirmed. Five minutes of 5 s attempts outlasts a manifest install on a
   slow link; past that, whatever holds the flag is the more authoritative
   operation. */
#define CONFIRM_ACQUIRE_ATTEMPTS 60
#define CONFIRM_ACQUIRE_RETRY_MS 5000

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

    /* Take the OTA-busy flag, like every other writer of otadata (#177). This
       task and a client-driven rollback or install can otherwise reach that
       partition at the same moment — and the rollback case is not merely a
       torn write: marking this image valid is precisely the transition the
       user is trying to abandon.
       Retry rather than give up at the first conflict: an install holds the
       flag for the length of a download, and a window missed here leaves a
       healthy image unconfirmed, which reverts it on the next reboot. */
    bool claimed = false;
    for (int attempt = 0; attempt < CONFIRM_ACQUIRE_ATTEMPTS; attempt++) {
        if (ota_busy_acquire()) {
            claimed = true;
            break;
        }
        ESP_LOGI(TAG, "Confirm deferred: another OTA operation holds the flag");
        vTaskDelay(pdMS_TO_TICKS(CONFIRM_ACQUIRE_RETRY_MS));
    }

    if (!claimed) {
        /* Deliberately not forcing it. The image stays PENDING_VERIFY, so the
           bootloader reverts on the next restart — the conservative end of an
           OTA operation that has been running this long. */
        ESP_LOGW(TAG, "Gave up confirming: OTA busy throughout; image stays pending verify");
        vTaskDelete(NULL);
        return;
    }

    if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
        ESP_LOGI(TAG, "Firmware confirmed valid; rollback canceled");
    } else {
        ESP_LOGW(TAG, "Failed to mark app valid");
    }
    ota_busy_release();
    vTaskDelete(NULL);
}

void ota_confirm_task_start(void)
{
    xTaskCreate(confirm_task, "ota_confirm", 4096, NULL, 3, NULL);
}
