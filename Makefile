# Bisque developer dispatcher.
#
# `idf.py` still owns the firmware build under the hood; this Makefile is
# a thin top-level entry point so `make help` lists every common task in
# one place and CI/local can run the same recipes. New targets should be
# additive — don't reimplement what idf.py / npm / cmake already do, just
# call them.

.DEFAULT_GOAL := help

WEB_DIR     := web_ui
SPIFFS_DIR  := spiffs_data/www

.PHONY: help build web gzip firmware sim \
        test test-host test-web fixtures \
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

gzip:  ## Compress $(SPIFFS_DIR)/* in place; partition only fits gzipped
	cd $(SPIFFS_DIR) && find . -type f \
	    \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.svg" \) \
	    -exec gzip -9 -f {} \;

firmware:  ## Firmware only — assumes $(SPIFFS_DIR) is already populated
	idf.py build

sim:  ## Build and run the LVGL/SDL2 simulator with --diff against baselines
	cmake -S simulator -B simulator/build
	cmake --build simulator/build
	./simulator/build/bisque_sim --diff

## ──────────────────────────────────────────────────────────────────────
## Tests
## ──────────────────────────────────────────────────────────────────────

test-host:  ## Host C unit tests (Unity, runs via ctest)
	cmake -S tests/host -B tests/host/build
	cmake --build tests/host/build
	ctest --test-dir tests/host/build --output-on-failure

fixtures:  ## Generate JSON API fixtures for the web contract tests
	cmake -S tests/host -B tests/host/build
	cmake --build tests/host/build --target api_fixtures

test-web: fixtures  ## Web UI tests (Vitest); depends on fixtures target
	cd $(WEB_DIR) && npm run test:run

test: test-host test-web  ## Run every test suite

## ──────────────────────────────────────────────────────────────────────
## Lint & format
## ──────────────────────────────────────────────────────────────────────

lint-c:  ## clang-format dry-run over main/ and components/
	find main components \( -path '*/assets/*' -prune \) -o \
	    \( -name '*.c' -o -name '*.h' \) -print | \
	    xargs clang-format --dry-run --Werror

lint-web:  ## Web UI typecheck + lint + format check
	cd $(WEB_DIR) && npm run typecheck && npm run lint && npm run format:check

lint: lint-c lint-web  ## All linters

format:  ## Auto-format C and web sources
	./scripts/format.sh

## ──────────────────────────────────────────────────────────────────────
## Static analysis (developer-on-demand; not part of `make ci`)
## ──────────────────────────────────────────────────────────────────────

clang-tidy:  ## Run clang-tidy with -warnings-as-errors=* (needs firmware build)
	idf_tools.py install esp-clang
	@bash -c 'eval "$$(idf_tools.py export)" && idf.py clang-check --run-clang-tidy-options="-warnings-as-errors=*" --exclude-paths managed_components'

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
	-idf.py fullclean
	rm -rf build cmake-build-debug tests/host/build simulator/build $(SPIFFS_DIR)
