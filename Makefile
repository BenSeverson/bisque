# Bisque developer dispatcher.
#
# `idf.py` still owns the firmware build under the hood; this Makefile is
# a thin top-level entry point so `make help` lists every common task in
# one place and CI/local can run the same recipes. New targets should be
# additive — don't reimplement what idf.py / npm / cmake already do, just
# call them.

.DEFAULT_GOAL := help

WEB_DIR     := web_ui
IOS_DIR     := ios/Bisque
SPIFFS_DIR  := spiffs_data/www

# Resolve cmake/ctest to absolute paths via the shell rather than letting make
# search PATH itself. Sourcing ESP-IDF's export.sh puts $IDF_PATH/tools on PATH,
# and that directory contains a *subdirectory* named `cmake`; make's own PATH
# lookup does not skip directories, so it tries to exec it and dies with
# "cmake: Permission denied". The shell skips it correctly, so one `command -v`
# up front makes every target below work in an IDF-activated shell — which is
# every shell in a cloud session and in the dev container.
CMAKE       := $(shell command -v cmake 2>/dev/null || echo cmake)
CTEST       := $(shell command -v ctest 2>/dev/null || echo ctest)

# Recipe prefix for anything that shells out to the ESP-IDF toolchain. Each
# recipe line runs in its own fresh shell, which has never sourced export.sh,
# so every idf.py/idf_tools.py call must activate first. No-op once active.
IDF         := . ./scripts/idf-env.sh &&

.PHONY: help build web gzip firmware sim sim-verify \
        test test-host test-web test-ios fixtures \
        lint lint-c lint-web format \
        clang-tidy cppcheck \
        size size-firmware size-spiffs \
        ci ci-firmware clean

help:  ## List available targets
	@awk 'BEGIN{FS=":.*## "} /^[a-z][a-zA-Z0-9_-]*:.*## / {printf "  \033[1m%-15s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

## ──────────────────────────────────────────────────────────────────────
## Build
## ──────────────────────────────────────────────────────────────────────

build:  ## Full pipeline: web UI + gzip + firmware (== ./build.sh)
	./build.sh

web:  ## Build the web UI bundle into $(SPIFFS_DIR) (does NOT gzip)
	cd $(WEB_DIR) && npm ci && npm run build

# Keep this file list in sync with the same find in build.sh.
# PNGs are left alone — already deflate-compressed, so gzip only adds a header.
gzip:  ## Compress $(SPIFFS_DIR)/* in place; partition only fits gzipped
	cd $(SPIFFS_DIR) && find . -type f \
	    \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.svg" \
	       -o -name "*.webmanifest" \) \
	    -exec gzip -9 -f {} \;

web-icons:  ## Re-rasterize web_ui/public PWA icons from web_ui/icons/*.svg
	./scripts/gen-web-icons.sh

firmware:  ## Firmware only — assumes $(SPIFFS_DIR) is already populated
	$(IDF) idf.py build

sim:  ## Build and run the LVGL/SDL2 simulator with --diff against baselines
	$(CMAKE) -S simulator -B simulator/build
	$(CMAKE) --build simulator/build
	./simulator/build/bisque_sim --diff

sim-verify:  ## Assert dashboard state (chart history, peak temp) — no pixel diffing
	$(CMAKE) -S simulator -B simulator/build
	$(CMAKE) --build simulator/build
	./simulator/build/bisque_sim --verify

## ──────────────────────────────────────────────────────────────────────
## Tests
## ──────────────────────────────────────────────────────────────────────

test-host:  ## Host C unit tests (Unity, runs via ctest)
	$(CMAKE) -S tests/host -B tests/host/build
	$(CMAKE) --build tests/host/build
	$(CTEST) --test-dir tests/host/build --output-on-failure

fixtures:  ## Generate JSON API fixtures for the web contract tests
	$(CMAKE) -S tests/host -B tests/host/build
	$(CMAKE) --build tests/host/build --target api_fixtures

test-web: fixtures  ## Web UI tests (Vitest); depends on fixtures target
	cd $(WEB_DIR) && npm run test:run

# Deliberately not part of `test`: it needs a Mac with Xcode and an iOS
# simulator, while `test` runs in the Linux container CI uses for everything
# else. Same policy as the build-ios CI job, which is kept out of `build.needs:`
# because iOS regressions do not block firmware merges.
#
# xcodegen runs with the version variables *unset* so the committed pbxproj
# keeps its ${BISQUE_*} placeholders; xcodebuild then expands them from its own
# environment. Exporting them around xcodegen instead would bake concrete
# versions into a tracked file and dirty the tree on every test run.
#
# The values themselves are not decoration: unset, CFBundleVersion ends up empty
# and the simulator refuses to install the app extension with "bundleVersion
# must be set in placeholder attributes" — a failure that says nothing about the
# tests.
test-ios:  ## iOS unit tests (XCTest on a simulator; needs macOS + Xcode)
	@device=$$(./scripts/pick-simulator.sh) && \
	  echo "Testing on $$device" && \
	  cd $(IOS_DIR) && \
	  env -u BISQUE_MARKETING_VERSION -u BISQUE_BUILD_NUMBER xcodegen generate && \
	  BISQUE_MARKETING_VERSION=$${BISQUE_MARKETING_VERSION:-1.0.0} \
	  BISQUE_BUILD_NUMBER=$${BISQUE_BUILD_NUMBER:-1} \
	  xcodebuild test -scheme Bisque \
	    -destination "platform=iOS Simulator,name=$$device" \
	    CODE_SIGNING_ALLOWED=NO -quiet

test: test-host test-web  ## Run every test suite (host + web; see test-ios)

## ──────────────────────────────────────────────────────────────────────
## Lint & format
## ──────────────────────────────────────────────────────────────────────

# The file list is built, checked and only then handed to clang-format, rather
# than piped straight in. `producer | xargs clang-format` reports the exit
# status of xargs alone, and both ways that pipeline can fail are silent:
# a producer that dies leaves xargs with empty input, and xargs given empty
# input still runs clang-format once, which reads its empty stdin and exits 0.
# Either way the job passes having checked nothing. Make's recipes run under
# /bin/sh, so `set -o pipefail` is not available to catch the first case.
#
# Not hypothetical, and doubly relevant now that the producer is a script
# rather than an inline find: this target once referenced ./scripts/c-sources.sh
# on a branch where the file did not exist, and CI's lint-c reported success
# over zero files for two commits.
lint-c:  ## clang-format dry-run over main/, components/ and simulator/
	@set -e; \
	files=$$(./scripts/c-sources.sh); \
	test -n "$$files" || { \
	    echo 'lint-c: no C sources found — the file list is broken, not clean' >&2; \
	    exit 1; \
	}; \
	echo "$$files" | xargs clang-format --dry-run --Werror

lint-web:  ## Web UI typecheck + lint + format check
	cd $(WEB_DIR) && npm run typecheck && npm run lint && npm run format:check

lint: lint-c lint-web  ## All linters

format:  ## Auto-format C and web sources
	./scripts/format.sh

## ──────────────────────────────────────────────────────────────────────
## Static analysis (developer-on-demand; not part of `make ci`)
## ──────────────────────────────────────────────────────────────────────

clang-tidy:  ## Run clang-tidy with -warnings-as-errors=* (needs firmware build)
	$(IDF) idf_tools.py install esp-clang
	@bash -c '. ./scripts/idf-env.sh && eval "$$(idf_tools.py export)" && idf.py clang-check --run-clang-tidy-options="-warnings-as-errors=*" --exclude-paths managed_components'

cppcheck:  ## Run cppcheck across main/ and components/
	cppcheck --enable=warning,style,performance --error-exitcode=1 \
	    --suppress=missingIncludeSystem --suppress=unusedFunction \
	    main/ components/

## ──────────────────────────────────────────────────────────────────────
## Size checks
## ──────────────────────────────────────────────────────────────────────

size-firmware:  ## Check firmware binary fits in the OTA partition
	./scripts/check-firmware-size.sh build/bisque.bin

size-spiffs:  ## Check $(SPIFFS_DIR) fits in the SPIFFS partition
	./scripts/check-spiffs-size.sh $(SPIFFS_DIR)

size: size-firmware size-spiffs  ## Both partition size checks

## ──────────────────────────────────────────────────────────────────────
## Aggregates
## ──────────────────────────────────────────────────────────────────────

ci-firmware:  ## Replicate CI's `build` job locally (no clang-tidy/cppcheck)
	$(MAKE) web
	$(MAKE) gzip
	$(MAKE) size-spiffs
	$(MAKE) firmware
	$(MAKE) size-firmware

ci: lint test ci-firmware  ## Closest local approximation of full CI

clean:  ## Remove build artifacts (firmware, host tests, simulator, SPIFFS)
	-$(IDF) idf.py fullclean
	rm -rf build cmake-build-debug tests/host/build simulator/build $(SPIFFS_DIR)
