#!/usr/bin/env bash
# Print every firmware/simulator C source clang-format owns, one per line.
#
# Single source of truth for the format check's scope: `make lint-c` (which CI
# runs), scripts/lint.sh (the pre-push hook), and scripts/format.sh all read
# from here, so widening or narrowing coverage is a one-line change rather than
# three that can drift apart.
#
# Exclusions, all deliberate — these are files we do not author in this style:
#   */assets/*        generated lv_img_conv bitmap arrays
#   simulator/stb_*   vendored single-header libraries (nothings/stb)
#   simulator/lv_conf.h
#                     derived from LVGL's upstream template; its column-aligned
#                     defines are what make diffs against upstream readable, and
#                     reformatting would fight every LVGL upgrade
#   simulator/freertos/*, simulator/esp_err.h
#                     hand-written stand-ins that mirror the layout of the
#                     ESP-IDF/FreeRTOS headers they replace
#   */build/*         CMake's own generated probes (CMakeCCompilerId.c and
#                     friends) land here once the simulator has been built
#   simulator/.lvgl/* upstream LVGL itself. #248 moved the SessionStart hook's
#                     LVGL clone here from managed_components/, which put ~1030
#                     vendored sources inside this find's roots for the first
#                     time. Unpruned, `make lint-c` grows from 58 files to 1089
#                     and takes minutes, and `scripts/format.sh` would rewrite
#                     the whole of upstream LVGL. CI never sees it — the
#                     ui-screenshots job still clones to managed_components/,
#                     outside these roots — so this only bites local and cloud
#                     development, which is exactly who the fallback path
#                     exists for.
set -euo pipefail
cd "$(dirname "$0")/.."

find main components simulator \
    \( -path '*/assets/*' -o -path '*/build/*' -o -path 'simulator/freertos/*' \
       -o -path 'simulator/.lvgl/*' \) -prune -o \
    ! -name 'stb_image.h' \
    ! -name 'stb_image_write.h' \
    ! -name 'lv_conf.h' \
    ! -name 'esp_err.h' \
    \( -name '*.c' -o -name '*.h' \) -print
