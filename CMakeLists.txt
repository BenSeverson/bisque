cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

project(bisque)

spiffs_create_partition_image(storage spiffs_data/www FLASH_IN_PROJECT)
