#pragma once

#include "lvgl.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Builder callback for a modal frame. Invoked when the frame becomes the top
 * of the modal stack. `root` is the modal's full-screen container parented
 * to lv_layer_top(); the builder populates it with widgets. Any focusable
 * widgets created inside join the modal's input group automatically.
 *
 * @param root  The modal's root container.
 * @param ctx   Opaque user data passed through from dashboard_modal_open().
 *              The pointer must remain valid for the lifetime of the frame
 *              (i.e. until the frame is popped). Static / global storage works;
 *              stack-allocated data does not.
 */
typedef void (*modal_builder_fn)(lv_obj_t *root, void *ctx);

/**
 * Push a modal onto the stack. Tears down the previous top frame's widgets,
 * builds the new one, switches the encoder indev to the modal group.
 *
 * Must be called with LVGL locked via lv_lock().
 */
void dashboard_modal_open(modal_builder_fn builder, void *ctx);

/**
 * Pop the top frame. If a parent frame remains, it is rebuilt; otherwise the
 * encoder indev is restored to the dashboard's base group.
 *
 * Must be called with LVGL locked via lv_lock().
 */
void dashboard_modal_close(void);

/**
 * Pop every frame and return to the dashboard. Used when an action commits
 * (e.g. "Start" or "Stop") to dismiss the entire modal workflow.
 *
 * Must be called with LVGL locked via lv_lock().
 */
void dashboard_modal_close_all(void);

/**
 * @return true if any modal frame is currently on the stack.
 */
bool dashboard_modal_active(void);

/**
 * Move focus to the previous object in the modal group. Bound to LEFT (and UP)
 * physical presses while a modal is active.
 */
void dashboard_modal_nav_left(void);

/**
 * Move focus to the next object in the modal group. Bound to RIGHT (and DOWN)
 * physical presses while a modal is active.
 */
void dashboard_modal_nav_right(void);

#ifdef __cplusplus
}
#endif
