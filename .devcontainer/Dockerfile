# Bisque dev container — full firmware + web toolchain.
#
# Base on the exact image CI uses (.github/workflows/build.yml) so a local
# container build matches the PR check. ESP-IDF v6.0.2 (target esp32s3) is
# pre-installed at $IDF_PATH (/opt/esp/idf); tools live under /opt/esp.
#
# Layered here (durable, image-cached): the two extra tools CI installs at
# runtime — cppcheck and esp-clang — plus shell init so idf.py is always on
# PATH. Node 24 and the Claude Code CLI are added via devcontainer features
# (see devcontainer.json). Web deps install in postCreate.sh.
FROM espressif/idf:v6.0.2

# cppcheck for `make cppcheck` (CI installs it via apt at runtime).
RUN apt-get update \
 && apt-get install -y --no-install-recommends cppcheck \
 && rm -rf /var/lib/apt/lists/*

# esp-clang so `make clang-tidy` works in-container (CI runs
# `idf_tools.py install esp-clang` on demand).
RUN . "$IDF_PATH/export.sh" \
 && python "$IDF_PATH/tools/idf_tools.py" install esp-clang

# Make idf.py + the tool paths available in every interactive shell.
RUN echo '. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true' >> /root/.bashrc
