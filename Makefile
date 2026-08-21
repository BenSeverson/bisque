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

.PHONY: help build web web-demo gzip firmware sim sim-verify \
        test test-host test-web test-ios fixtures \
        lint lint-c lint-web format \
        clang-tidy cppcheck \
        size size-firmware size-spiffs \
        ci ci-firmware clean \
        pcb pcb-build pcb-cosmetic pcb-cosmetic-verify pcb-fab pcb-render \
        pcb-check pcb-check-portable datasheets-manifest

help:  ## List available targets
	@awk 'BEGIN{FS=":.*## "} /^[a-z][a-zA-Z0-9_-]*:.*## / {printf "  \033[1m%-20s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

## ──────────────────────────────────────────────────────────────────────
## Build
## ──────────────────────────────────────────────────────────────────────

build:  ## Full pipeline: web UI + gzip + firmware (== ./build.sh)
	./build.sh

web:  ## Build the web UI bundle into $(SPIFFS_DIR) (does NOT gzip)
	cd $(WEB_DIR) && npm ci && npm run build

# The demo is the only build that exercises the __DEMO__-gated dynamic import
# of mock-server/, so nothing else catches a break in it. pages.yml deploys it
# on push to main, i.e. after a bad merge has already landed — CI's lint-web
# job runs this so the breakage is caught on the PR instead.
web-demo:  ## Build the static GitHub Pages demo into $(WEB_DIR)/dist
	cd $(WEB_DIR) && npm run build:demo

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

# BISQUE_SKIP_CONTRACTS=1 is the opt-out for a machine that cannot run the C
# build, so it has to drop the `fixtures` prerequisite as well as reach the test
# runner: a prerequisite runs whatever the recipe would have gone on to do, and
# generating fixtures *is* the C build the flag exists to avoid. Setting it and
# still watching cmake start is the whole complaint.
#
# Both spellings are honoured because both are documented: the plain one is what
# a developer types, and the TEST_RUNNER_-prefixed one is the only form that
# survives into a process on the simulator (xcodebuild forwards that prefix and
# nothing else — unprefixed, the variable stops at xcodebuild and the suite runs
# anyway).
SKIP_CONTRACTS := $(or $(BISQUE_SKIP_CONTRACTS),$(TEST_RUNNER_BISQUE_SKIP_CONTRACTS))

ifeq ($(SKIP_CONTRACTS),1)
CONTRACT_FIXTURES :=
else
CONTRACT_FIXTURES := fixtures
endif

test-web: $(CONTRACT_FIXTURES)  ## Web UI tests (Vitest); depends on fixtures target
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
#
# Depends on `fixtures` for the same reason `test-web` does: BisqueTests includes
# a firmware contract suite that decodes the generated JSON with the app's models
# (#154), and reads it straight off disk via #filePath rather than as a bundled
# resource — tests/host/build/ does not exist when xcodegen runs, so it cannot be
# declared as one. Missing or stale fixtures fail rather than skip; see
# SKIP_CONTRACTS above for the opt-out, which this target has to translate into
# xcodebuild's TEST_RUNNER_ prefix to get it as far as the simulator.
test-ios: $(CONTRACT_FIXTURES)  ## iOS unit tests (XCTest on a simulator; needs macOS + Xcode)
	@udid=$$(./scripts/pick-simulator.sh) && \
	  cd $(IOS_DIR) && \
	  env -u BISQUE_MARKETING_VERSION -u BISQUE_BUILD_NUMBER xcodegen generate && \
	  BISQUE_MARKETING_VERSION=$${BISQUE_MARKETING_VERSION:-1.0.0} \
	  BISQUE_BUILD_NUMBER=$${BISQUE_BUILD_NUMBER:-1} \
	  TEST_RUNNER_BISQUE_SKIP_CONTRACTS=$(SKIP_CONTRACTS) \
	  xcodebuild test -scheme Bisque \
	    -destination "platform=iOS Simulator,id=$$udid" \
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
## PCB (hardware/kicad) — see hardware/kicad/README.md for the full regen
## order and why it matters (zone fill must be current before gerbers
## export, or a stale pour gets baked into gerbers/).
## ──────────────────────────────────────────────────────────────────────

KICAD_DIR := hardware/kicad

# KiCad's Python — the one that can `import pcbnew`. Resolved inside the
# recipe, not baked in at parse time, because the answer differs per host:
# the Linux devcontainer (docs/devcontainer.md) has pcbnew on the *system*
# python3, macOS has it only inside the KiCad.app bundle. Hardcoding the
# bundle path made `make pcb` / `make pcb-check` fail in the container even
# though pcbnew was installed and importable. `KPY=... make pcb` still wins.
KPY_CANDIDATES = python3 \
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /usr/bin/python3 /usr/local/bin/python3
define find_kpy
KPY="$${KPY:-$$(for p in $(KPY_CANDIDATES); do \
	  "$$p" -c 'import pcbnew' >/dev/null 2>&1 && { echo "$$p"; break; }; \
	done)}"; \
if [ -z "$$KPY" ]; then \
	echo "error: no Python with 'import pcbnew' found. Install KiCad 10+, or" >&2; \
	echo "       run in the devcontainer (docs/devcontainer.md), or set KPY=..." >&2; \
	echo "       tried: $(KPY_CANDIDATES)" >&2; \
	exit 1; \
fi
endef

# The gerber layer set JLCPCB needs. In1.Cu/In2.Cu are NOT optional: this is
# a 4-layer board and a package without them fabricates as 2-layer, with
# every ground and power connection missing.
GERBER_LAYERS := F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts

# The seven checkers that read the board and schematic as text with nothing
# but the standard library. Split out so CI can run them on a bare ubuntu
# runner: installing KiCad 10 from the PPA (see .devcontainer/Dockerfile)
# costs minutes and ~1 GB, which is not worth paying to learn that a pin
# default drifted.
#
# check_pinmap is the reason this target exists. `design.py` and
# `main/Kconfig.projbuild` must agree on every GPIO and have drifted apart
# before; until this ran in CI, the only thing standing between a drift and
# `main` was someone remembering to type `make pcb-check`.
#
# ADDING A CHECKER HERE: a script "needs KiCad" in THREE independent ways,
# and this list was wrong twice because each fix only considered the one
# that had just failed:
#   1. `import pcbnew`          - via_in_pad, silk, placement
#   2. a `kicad-cli` subprocess - netlist (exports the netlist to diff it)
#   3. KiCad's footprint libs   - jlc_placement (fits LCSC's land pattern
#                                 onto the real .kicad_mod; see
#                                 find_footprint_dir())
# Every dev machine satisfies all three, so a green local run proves
# nothing about this list. Check all three, and let CI be the arbiter.
pcb-check-portable:  ## PCB checkers that need no KiCad install (the CI subset)
	@cd $(KICAD_DIR) && python3 generator/check_pinmap.py \
	  && python3 generator/check_sch_bounds.py bisque-controller.kicad_sch \
	  && python3 generator/check_sch_layout.py bisque-controller.kicad_sch \
	  && python3 generator/check_mpn.py bisque-controller.kicad_sch \
	  && python3 generator/check_pcb.py bisque-controller.kicad_pcb \
	  && python3 generator/check_drill_clearance.py bisque-controller.kicad_pcb \
	  && python3 generator/check_canonical.py bisque-controller.kicad_pcb \
	  && python3 generator/gen_gerber_zip.py --check

# The remaining five need a KiCad install, for the three reasons above. Run
# the portable set first — same twelve checks as before the split, and a
# cheap failure beats an expensive one.
pcb-check: pcb-check-portable  ## Run every PCB checker (no KiCad rebuild)
	@$(find_kpy); \
	cd $(KICAD_DIR) && python3 generator/check_netlist.py bisque-controller.kicad_sch \
	  && python3 generator/check_jlc_placement.py \
	  && "$$KPY" generator/check_via_in_pad.py bisque-controller.kicad_pcb \
	  && "$$KPY" generator/check_silk.py bisque-controller.kicad_pcb \
	  && "$$KPY" generator/check_placement.py \
	  && python3 generator/gen_datasheet_manifest.py --check

# The datasheet cache is gitignored, so this is a local housekeeping tool
# rather than a CI gate — see the header of gen_datasheet_manifest.py.
datasheets-manifest:  ## Re-index hardware/kicad/datasheets/ into its manifest.json
	@cd $(KICAD_DIR) && python3 generator/gen_datasheet_manifest.py

# pcb-check runs BEFORE pcb-render on purpose: the raytrace is the most
# expensive step here and the least informative one to look at if a checker
# has already said the board is wrong. Fail first, then spend the minutes.
pcb: pcb-build pcb-fab  ## Regenerate schematic + board + fab outputs + 3D renders
	$(MAKE) pcb-check
	$(MAKE) pcb-render

pcb-build:  ## Regenerate schematic + board only (no fab outputs)
	@$(find_kpy); \
	cd $(KICAD_DIR) && python3 generator/gen_sch.py bisque-controller.kicad_sch \
	  && "$$KPY" generator/kicad_build.py bisque-controller.kicad_pcb \
	  && "$$KPY" generator/check_via_in_pad.py bisque-controller.kicad_pcb

# The fast path. Routing 93 nets across 141 parts is ~144 s of pcb-build's
# ~158 s, and silkscreen placement, 3D-model offsets, the title block and
# reference-designator text metrics cannot move copper at all — so those
# re-derive off the existing routing in ~8 s. Byte-identical to pcb-build
# by construction and by test (pcb-cosmetic-verify); kicad_build.py refuses
# --no-route outright if design.py's parts, placement or nets have drifted
# from the board on disk. ANYTHING touching placement, connectivity, net
# classes or router parameters needs `make pcb-build`.
pcb-cosmetic:  ## Re-derive silk/3D models/title block only, reusing the existing routing (fast)
	@$(find_kpy); \
	cd $(KICAD_DIR) && python3 generator/gen_sch.py bisque-controller.kicad_sch \
	  && "$$KPY" generator/kicad_build.py --no-route bisque-controller.kicad_pcb \
	  && "$$KPY" generator/check_via_in_pad.py bisque-controller.kicad_pcb

# Costs a full rebuild, so it is deliberately not in pcb-check. Run it when
# kicad_build.py, silk.py or design.py's placement machinery changes.
pcb-cosmetic-verify:  ## Prove --no-route is byte-identical to a full rebuild (slow)
	@$(find_kpy); \
	cd $(KICAD_DIR) && "$$KPY" generator/check_fast_path.py \
	  bisque-controller.kicad_pcb

# Everything a fab order reads. Runs AFTER pcb-build: kicad_build.py ends
# with a `kicad-cli pcb drc --refill-zones` pass, and exporting before that
# bakes a stale pour into gerbers/. Stale gerbers are deleted rather than
# overwritten so a layer that stops being exported cannot linger in the zip.
# gen_gerber_zip.py runs after both exports and before gen_jlc.py, so
# jlcpcb/ ends up holding the complete upload: gerbers.zip + BOM + CPL.
# The 3D raytrace is not here — no fab output reads a model — but `make pcb`
# still runs it as its own step; see pcb-render.
pcb-fab:  ## Regenerate gerbers, drill, gerbers.zip, BOM/CPL and the PDFs
	cd $(KICAD_DIR) \
	  && rm -f gerbers/*.gbr gerbers/*.drl gerbers/*.gbrjob \
	  && kicad-cli pcb export gerbers -o gerbers/ --layers "$(GERBER_LAYERS)" \
	       bisque-controller.kicad_pcb \
	  && kicad-cli pcb export drill -o gerbers/ --format excellon \
	       --excellon-units mm --excellon-zeros-format decimal --generate-map \
	       --map-format gerberx2 --gerber-precision 5 bisque-controller.kicad_pcb \
	  && python3 generator/gen_gerber_zip.py \
	  && python3 generator/gen_jlc.py jlcpcb \
	  && kicad-cli sch export pdf -o pdf/bisque-controller-schematic.pdf \
	       bisque-controller.kicad_sch \
	  && kicad-cli pcb export pdf --mode-multipage --include-border-title \
	       -l "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Silkscreen,B.Silkscreen" \
	       --common-layers "Edge.Cuts" \
	       -o pdf/bisque-controller-board.pdf bisque-controller.kicad_pcb

# Nothing in a fab order reads a 3D model, so this used to be a hand-run
# target outside `make pcb`. That made 3d/ the one derived artifact that
# could silently go stale against the board, and stale is worse here than
# slow: these renders are how placement and silk get eyeballed without a
# board in hand, so a reader cannot tell a fixed layout from an old picture
# of a broken one. It is now the last step of `make pcb`.
#
# It stays a separate target, and a content-addressed one, because the
# raytracer is not reproducible — see the stamp comment in render-3d.sh.
# An unchanged board therefore costs ~0.2 s here, not 13 s and a 900 KB
# binary diff. FORCE=1 re-renders regardless.
pcb-render:  ## Re-raytrace hardware/kicad/3d/ (skipped when nothing affects a pixel; FORCE=1 overrides)
	cd $(KICAD_DIR) && ./generator/render-3d.sh $(if $(FORCE),--force,)

## ──────────────────────────────────────────────────────────────────────
## Aggregates
## ──────────────────────────────────────────────────────────────────────

ci-firmware:  ## Replicate CI's `build` job locally (no clang-tidy/cppcheck)
	$(MAKE) web
	$(MAKE) gzip
	$(MAKE) size-spiffs
	$(MAKE) firmware
	$(MAKE) size-firmware

ci: lint web-demo test ci-firmware  ## Closest local approximation of full CI

clean:  ## Remove build artifacts (firmware, host tests, simulator, SPIFFS)
	-$(IDF) idf.py fullclean
	rm -rf build cmake-build-debug tests/host/build simulator/build $(SPIFFS_DIR)
