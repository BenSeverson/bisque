#include "modal.h"
#include "ui_common.h"
#include "esp_log.h"

extern lv_indev_t *g_indev_encoder;
extern lv_group_t *g_input_group;
extern lv_group_t *g_modal_group;

static const char *TAG = "modal";

#define MODAL_STACK_MAX 4

typedef struct {
    modal_builder_fn builder;
    void *ctx;
} modal_frame_t;

static modal_frame_t s_stack[MODAL_STACK_MAX];
static int s_stack_depth = 0;
static lv_obj_t *s_root = NULL;

static void teardown_root(void)
{
    if (s_root) {
        lv_obj_delete(s_root);
        s_root = NULL;
        lv_group_remove_all_objs(g_modal_group);
    }
}

static void build_frame(const modal_frame_t *frame)
{
    s_root = lv_obj_create(lv_layer_top());
    lv_obj_set_size(s_root, UI_LCD_W, UI_LCD_H);
    lv_obj_set_pos(s_root, 0, 0);
    lv_obj_set_style_bg_color(s_root, UI_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(s_root, LV_OPA_90, 0);
    lv_obj_set_style_border_width(s_root, 0, 0);
    lv_obj_set_style_radius(s_root, 0, 0);
    lv_obj_set_style_pad_all(s_root, 0, 0);
    lv_obj_clear_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    /* New widgets default to the modal group so the builder doesn't have to
     * call lv_group_add_obj manually. */
    lv_group_set_default(g_modal_group);
    if (frame->builder) {
        frame->builder(s_root, frame->ctx);
    }
    lv_group_set_default(g_input_group);

    lv_indev_set_group(g_indev_encoder, g_modal_group);
}

void dashboard_modal_open(modal_builder_fn builder, void *ctx)
{
    if (s_stack_depth >= MODAL_STACK_MAX) {
        ESP_LOGE(TAG, "modal stack full (%d frames); refusing open", s_stack_depth);
        return;
    }

    teardown_root();
    s_stack[s_stack_depth++] = (modal_frame_t){.builder = builder, .ctx = ctx};
    build_frame(&s_stack[s_stack_depth - 1]);
}

void dashboard_modal_close(void)
{
    if (s_stack_depth == 0) {
        return;
    }
    s_stack_depth--;
    teardown_root();

    if (s_stack_depth > 0) {
        build_frame(&s_stack[s_stack_depth - 1]);
    } else {
        lv_indev_set_group(g_indev_encoder, g_input_group);
    }
}

void dashboard_modal_close_all(void)
{
    s_stack_depth = 0;
    teardown_root();
    lv_indev_set_group(g_indev_encoder, g_input_group);
}

bool dashboard_modal_active(void)
{
    return s_stack_depth > 0;
}
