# Devcontainer KiCad 10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bake KiCad 10 into the local `.devcontainer/` image so the `hardware/kicad/generator/` pipeline (pcbnew Python API + kicad-cli) works out of the box inside the container, matching what already works for cloud Claude Code sessions.

**Architecture:** Add one `RUN` layer to `.devcontainer/Dockerfile` that installs KiCad 10 from `ppa:kicad/kicad-10.0-releases` (mirroring the install logic already proven in `.claude/hooks/install-kicad.sh`), pass an opt-in `KICAD_3D` build arg through `devcontainer.json`, surface the installed version in the `postCreate.sh` readiness banner, and document the new capability in `docs/devcontainer.md` and `hardware/kicad/README.md`.

**Tech Stack:** Docker (`espressif/idf:v6.0.2` base image, Ubuntu), apt/PPA, bash, VS Code Dev Containers (JSONC).

## Global Constraints

- KiCad 10+ only — the generator no longer supports KiCad 7 (`c5801e6`). Install from `ppa:kicad/kicad-10.0-releases`, packages `kicad kicad-symbols kicad-footprints` — the exact PPA and package list `.claude/hooks/install-kicad.sh` already uses successfully for cloud sessions.
- `KICAD_3D` build arg, default `0`. Only pulls `kicad-packages3d` (~6 GB) when explicitly set to `1`.
- Local-only change. Do not touch `.claude/hooks/install-kicad.sh` or `.claude/hooks/session-start.sh` — those remain the correct, separately-gated mechanism for cloud sandboxes.
- Out of scope, do not add: GUI KiCad in the container (X11/noVNC), a KiCad MCP server, a `make pcb` Makefile target.
- No Docker daemon is available to the plan's implementer in this working environment. Every task's verification step is either a check that genuinely doesn't need Docker (bash syntax check, careful diff re-read) or is explicitly marked **[requires user's Docker Desktop]** for the human to run after the PR is up.

---

## File Structure

| File | Change |
|---|---|
| `.devcontainer/Dockerfile` | New `ARG KICAD_3D=0` + `RUN` layer installing KiCad 10; update the top comment block |
| `.devcontainer/devcontainer.json` | `build.args` example (commented, opt-in) for `KICAD_3D`; update top comment |
| `.devcontainer/postCreate.sh` | Add `kicad-cli version` line to the readiness banner |
| `docs/devcontainer.md` | New "What works" table row + short paragraph on KiCad 10 |
| `hardware/kicad/README.md` | One-sentence addition pointing at the devcontainer as an alternative to a native KiCad install |

No new files. No tests directory — this repo has no Dockerfile test harness, and none is being introduced (see Global Constraints).

---

### Task 1: Dockerfile — install KiCad 10

**Files:**
- Modify: `.devcontainer/Dockerfile`

**Interfaces:**
- Produces: a `KICAD_3D` build arg (default `0`) that later tasks (devcontainer.json) reference by name.

- [ ] **Step 1: Update the file header comment**

In `.devcontainer/Dockerfile`, the current header reads:

```dockerfile
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
```

Replace the second comment paragraph so it also describes the new layer:

```dockerfile
# Bisque dev container — full firmware + web toolchain.
#
# Base on the exact image CI uses (.github/workflows/build.yml) so a local
# container build matches the PR check. ESP-IDF v6.0.2 (target esp32s3) is
# pre-installed at $IDF_PATH (/opt/esp/idf); tools live under /opt/esp.
#
# Layered here (durable, image-cached): the two extra tools CI installs at
# runtime — cppcheck and esp-clang — KiCad 10 for the hardware/kicad
# generator pipeline, plus shell init so idf.py is always on PATH. Node 24
# and the Claude Code CLI are added via devcontainer features (see
# devcontainer.json). Web deps install in postCreate.sh.
FROM espressif/idf:v6.0.2
```

- [ ] **Step 2: Add the KiCad install layer**

Insert this new block after the existing esp-clang `RUN` block and before the final `# Make idf.py + the tool paths...` block, so the full file reads:

```dockerfile
# Bisque dev container — full firmware + web toolchain.
#
# Base on the exact image CI uses (.github/workflows/build.yml) so a local
# container build matches the PR check. ESP-IDF v6.0.2 (target esp32s3) is
# pre-installed at $IDF_PATH (/opt/esp/idf); tools live under /opt/esp.
#
# Layered here (durable, image-cached): the two extra tools CI installs at
# runtime — cppcheck and esp-clang — KiCad 10 for the hardware/kicad
# generator pipeline, plus shell init so idf.py is always on PATH. Node 24
# and the Claude Code CLI are added via devcontainer features (see
# devcontainer.json). Web deps install in postCreate.sh.
FROM espressif/idf:v6.0.2

# cppcheck for `make cppcheck` (CI installs it via apt at runtime).
RUN apt-get update \
 && apt-get install -y --no-install-recommends cppcheck \
 && rm -rf /var/lib/apt/lists/*

# esp-clang so `make clang-tidy` works in-container (CI runs
# `idf_tools.py install esp-clang` on demand).
RUN . "$IDF_PATH/export.sh" \
 && python "$IDF_PATH/tools/idf_tools.py" install esp-clang

# KiCad 10 for the hardware/kicad generator pipeline (pcbnew Python API +
# kicad-cli). Ubuntu's own repo only ships KiCad 7, which the generator no
# longer supports (see hardware/kicad/README.md) — pull from the official
# PPA instead. Mirrors .claude/hooks/install-kicad.sh's install logic (kept
# in sync manually: same PPA, same package list); unlike that script, this
# layer does not preflight/skip on a blocked network, since a local Docker
# build isn't sandboxed the way a cloud session is — a failure here should
# fail the image build, not silently degrade.
ARG KICAD_3D=0
RUN . /etc/os-release \
 && PPA="kicad/kicad-10.0-releases" \
 && apt-get update -qq \
 && (apt-get install -y -qq software-properties-common \
     && add-apt-repository -y "ppa:${PPA}") \
    || echo "deb [trusted=yes] https://ppa.launchpadcontent.net/${PPA}/ubuntu ${UBUNTU_CODENAME} main" \
       > /etc/apt/sources.list.d/kicad.list \
 && apt-get update -qq \
 && PKGS="kicad kicad-symbols kicad-footprints" \
 && if [ "$KICAD_3D" = "1" ]; then PKGS="$PKGS kicad-packages3d"; fi \
 && apt-get install -y --no-install-recommends $PKGS \
 && rm -rf /var/lib/apt/lists/* \
 && kicad-cli version

# Make idf.py + the tool paths available in every interactive shell.
RUN echo '. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true' >> /root/.bashrc
```

- [ ] **Step 3: Syntax-check the embedded shell**

The multi-line `RUN` command is plain POSIX shell glued with `\` line
continuations — extract it and run it through `bash -n` (parse-only, no
execution) to catch quoting/escaping mistakes without needing Docker:

```bash
cat > /tmp/kicad-run-check.sh <<'EOF'
. /etc/os-release \
 && PPA="kicad/kicad-10.0-releases" \
 && apt-get update -qq \
 && (apt-get install -y -qq software-properties-common \
     && add-apt-repository -y "ppa:${PPA}") \
    || echo "deb [trusted=yes] https://ppa.launchpadcontent.net/${PPA}/ubuntu ${UBUNTU_CODENAME} main" \
       > /etc/apt/sources.list.d/kicad.list \
 && apt-get update -qq \
 && PKGS="kicad kicad-symbols kicad-footprints" \
 && if [ "$KICAD_3D" = "1" ]; then PKGS="$PKGS kicad-packages3d"; fi \
 && apt-get install -y --no-install-recommends $PKGS \
 && rm -rf /var/lib/apt/lists/* \
 && kicad-cli version
EOF
bash -n /tmp/kicad-run-check.sh && echo SYNTAX_OK
```

Run: the command above.
Expected: `SYNTAX_OK` printed, no `bash: ... syntax error` output.

- [ ] **Step 4: Commit**

```bash
git add .devcontainer/Dockerfile
git commit -m "devcontainer: install KiCad 10 for the hardware/kicad pipeline"
```

---

### Task 2: devcontainer.json — pass through KICAD_3D

**Files:**
- Modify: `.devcontainer/devcontainer.json`

**Interfaces:**
- Consumes: the `KICAD_3D` build arg name from Task 1.

- [ ] **Step 1: Update the top comment**

Current:

```jsonc
{
  // Local VS Code dev container for Bisque. See docs/devcontainer.md.
  // Mirrors the CI toolchain (ESP-IDF v6.0.2 + Node 24) and adds the Claude
  // Code CLI so the full firmware + web workflow works out of the box.
  "name": "Bisque (ESP-IDF v6.0.2 + web)",
  "build": { "dockerfile": "Dockerfile" },
```

Replace with:

```jsonc
{
  // Local VS Code dev container for Bisque. See docs/devcontainer.md.
  // Mirrors the CI toolchain (ESP-IDF v6.0.2 + Node 24), adds the Claude
  // Code CLI, and bakes in KiCad 10 for the hardware/kicad generator
  // pipeline — so the full firmware + web + PCB workflow works out of
  // the box.
  "name": "Bisque (ESP-IDF v6.0.2 + web)",
  "build": {
    "dockerfile": "Dockerfile"
    // Uncomment to also install kicad-packages3d (~6 GB) for
    // `kicad-cli pcb render`:
    // , "args": { "KICAD_3D": "1" }
  },
```

- [ ] **Step 2: Confirm the rest of the file is untouched**

Read the file back and confirm every line from `"features"` onward
(`features`, `remoteUser`, `remoteEnv`, `mounts`, `postCreateCommand`,
`customizations`) is byte-for-byte identical to before this task — this
task only touches the top comment and the `build` block.

- [ ] **Step 3: Sanity-check the JSONC is well-formed**

VS Code's dev container parser tolerates `//` comments (this file already
uses them), so `python3 -m json.tool` will reject it — don't use that.
Instead strip `//`-prefixed comment lines and confirm what's left parses:

```bash
python3 -c "
import json, re
with open('.devcontainer/devcontainer.json') as f:
    text = f.read()
stripped = re.sub(r'^\s*//.*$', '', text, flags=re.MULTILINE)
json.loads(stripped)
print('JSONC_OK')
"
```

Run: the command above.
Expected: `JSONC_OK` printed, no `json.decoder.JSONDecodeError`.

- [ ] **Step 4: Commit**

```bash
git add .devcontainer/devcontainer.json
git commit -m "devcontainer: document KICAD_3D build arg opt-in"
```

---

### Task 3: postCreate.sh — readiness banner

**Files:**
- Modify: `.devcontainer/postCreate.sh`

**Interfaces:**
- Consumes: `kicad-cli` on `PATH`, installed by Task 1's Dockerfile layer.

- [ ] **Step 1: Add the banner line**

Current tail of the file:

```bash
# Readiness banner.
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true
echo "Bisque devcontainer ready:"
echo "  idf.py : $(idf.py --version 2>/dev/null || echo 'n/a')"
echo "  node   : $(node -v 2>/dev/null)  npm $(npm -v 2>/dev/null)"
echo "  claude : $(claude --version 2>/dev/null || echo 'CLI installed')"
echo "Build: idf.py set-target esp32s3 && idf.py build  |  Full check: make ci"
```

Replace with:

```bash
# Readiness banner.
. "$IDF_PATH/export.sh" >/dev/null 2>&1 || true
echo "Bisque devcontainer ready:"
echo "  idf.py : $(idf.py --version 2>/dev/null || echo 'n/a')"
echo "  node   : $(node -v 2>/dev/null)  npm $(npm -v 2>/dev/null)"
echo "  claude : $(claude --version 2>/dev/null || echo 'CLI installed')"
echo "  kicad  : $(kicad-cli version 2>/dev/null || echo 'n/a')"
echo "Build: idf.py set-target esp32s3 && idf.py build  |  Full check: make ci"
```

(Column alignment: each label is padded to 7 characters before the colon —
`idf.py ` (6+1), `node   ` (4+3), `claude ` (6+1), `kicad  ` (5+2) — so
keep exactly two spaces between `kicad` and the colon.)

- [ ] **Step 2: Syntax-check the script**

```bash
bash -n .devcontainer/postCreate.sh && echo SYNTAX_OK
```

Run: the command above.
Expected: `SYNTAX_OK`, no syntax errors.

- [ ] **Step 3: Commit**

```bash
git add .devcontainer/postCreate.sh
git commit -m "devcontainer: show kicad-cli version in the readiness banner"
```

---

### Task 4: docs/devcontainer.md — document the new capability

**Files:**
- Modify: `docs/devcontainer.md`

- [ ] **Step 1: Add a table row**

Current "What works" table:

```markdown
## What works

Everything the PR check runs, from the container terminal:

| Task | Command |
|---|---|
| Firmware build | `idf.py set-target esp32s3 && idf.py build` |
| Web UI build / dev / test | `make web` · `npm run dev` · `make test-web` |
| Host C unit tests | `make test-host` |
| Lint + format | `make lint` |
| clang-tidy / cppcheck | `make clang-tidy` · `make cppcheck` |
| **The whole PR gate** | `make ci` |
| Claude Code | `claude` |
```

Replace with (new row inserted after clang-tidy/cppcheck, and a paragraph
added below the table):

```markdown
## What works

Everything the PR check runs, from the container terminal:

| Task | Command |
|---|---|
| Firmware build | `idf.py set-target esp32s3 && idf.py build` |
| Web UI build / dev / test | `make web` · `npm run dev` · `make test-web` |
| Host C unit tests | `make test-host` |
| Lint + format | `make lint` |
| clang-tidy / cppcheck | `make clang-tidy` · `make cppcheck` |
| **The whole PR gate** | `make ci` |
| Claude Code | `claude` |
| PCB/schematic regen + validation | see `hardware/kicad/README.md` (`generator/gen_sch.py`, `check_netlist.py`, `kicad_build.py`, `check_pcb.py`) |

KiCad 10 (`kicad-cli` + the `pcbnew` Python API) is baked into the image,
so the `hardware/kicad/generator/` pipeline works immediately — no
macOS-style bundled-Python (`KPY`) workaround needed, since apt-installed
KiCad on Linux binds directly to the container's system `python3`. Set the
`KICAD_3D` build arg to pull the ~6 GB 3D model pack if you need
`kicad-cli pcb render` output; see the comment in `devcontainer.json`.
```

- [ ] **Step 2: Re-read the file and confirm no other section changed**

Read `docs/devcontainer.md` back and confirm the "What doesn't — flashing",
"Claude Code auth", and "Note on the `.vscode/` settings" sections are
byte-for-byte unchanged.

- [ ] **Step 3: Commit**

```bash
git add docs/devcontainer.md
git commit -m "docs: document the devcontainer's KiCad 10 pipeline support"
```

---

### Task 5: hardware/kicad/README.md — point at the devcontainer

**Files:**
- Modify: `hardware/kicad/README.md`

- [ ] **Step 1: Add one sentence to "Regenerating the files"**

Current opening of that section:

```markdown
## Regenerating the files

Everything derives from `generator/design.py` — a single table of
components, pin→net connectivity and placements — so schematic and board
can never disagree. Requires **KiCad 10+** (pcbnew Python module +
kicad-cli + standard libraries). On macOS run the board build with
KiCad's bundled Python:
```

Replace with:

```markdown
## Regenerating the files

Everything derives from `generator/design.py` — a single table of
components, pin→net connectivity and placements — so schematic and board
can never disagree. Requires **KiCad 10+** (pcbnew Python module +
kicad-cli + standard libraries) — the project's `.devcontainer/` (see
`docs/devcontainer.md`) bakes this in, as an alternative to installing
KiCad natively. On macOS run the board build with KiCad's bundled Python:
```

- [ ] **Step 2: Re-read the file and confirm nothing else changed**

Read `hardware/kicad/README.md` back and confirm every other section
(Opening it, What's on the board, GPIO map, Bill of materials, Fabrication
& assembly, Safety) is byte-for-byte unchanged.

- [ ] **Step 3: Commit**

```bash
git add hardware/kicad/README.md
git commit -m "docs: point the KiCad README at the devcontainer's KiCad 10 install"
```

---

### Task 6: End-to-end verification **[requires user's Docker Desktop]**

This task has no automated steps — it cannot run in an environment without
a Docker daemon. It's here so the plan's execution isn't considered done
until someone with Docker Desktop has actually confirmed the image builds
and the pipeline works.

- [ ] **Step 1: Rebuild the container**

In VS Code, with the repo open: **Dev Containers: Rebuild Container**
(not just reopen — this forces the new Dockerfile layer to build rather
than reuse a stale cached image).

Expected: build succeeds; the `kicad-cli version` line at the end of
Task 1's `RUN` block prints a `10.x.x` version during the build log (this
is what makes the layer fail loudly if the install silently produced a
broken `kicad-cli`).

- [ ] **Step 2: Confirm the toolchain from the container terminal**

```bash
kicad-cli version
python3 -c "import pcbnew; print(pcbnew.Version())"
```

Expected: both print a `10.x` version; no `ImportError` from the second
command.

- [ ] **Step 3: Confirm the readiness banner**

Reopen a new terminal in the container (or re-run
`bash .devcontainer/postCreate.sh`) and confirm the `kicad :` line shows
the same `10.x` version.

- [ ] **Step 4: Run the real generator pipeline**

```bash
cd hardware/kicad
python3 generator/gen_sch.py bisque-controller.kicad_sch
python3 generator/check_netlist.py bisque-controller.kicad_sch
python3 generator/kicad_build.py bisque-controller.kicad_pcb
python3 generator/check_pcb.py bisque-controller.kicad_pcb
```

Expected: `check_netlist.py` reports a passing round-trip (0 mismatches);
`check_pcb.py` reports all checks passing (0 errors, 0 unconnected) — same
bar the `hardware/kicad/README.md` "Built and validated" section
describes. If `kicad_build.py` can't find footprint libraries, it exits
with `KiCad footprint libraries not found - set KICAD_FOOTPRINT_DIR`; this
shouldn't happen since apt installs them at
`/usr/share/kicad/footprints`, which `_find_fp_base()` already searches —
if it does happen, that's a real bug in this plan's Dockerfile layer, not
something to route around with an env var.

- [ ] **Step 5: Discard the regenerated output**

The commands in Step 4 rewrite `bisque-controller.kicad_sch` /
`.kicad_pcb` in place. This was only a pipeline smoke test, not an
intentional board change, so discard it:

```bash
git status hardware/kicad/    # confirm only the two regenerated files changed
git checkout -- hardware/kicad/bisque-controller.kicad_sch hardware/kicad/bisque-controller.kicad_pcb
```

- [ ] **Step 6: Report back**

No commit from this task (nothing should be checked in beyond what Tasks
1–5 already committed). If any expected output above didn't match, that's
a bug to fix in Task 1's Dockerfile layer — go back, adjust, re-run this
task from Step 1.

---

## Self-Review Notes

- **Spec coverage:** Dockerfile install (Task 1) ✓, `KICAD_3D` build arg
  passthrough (Task 2) ✓, postCreate banner (Task 3) ✓,
  `docs/devcontainer.md` (Task 4) ✓, `hardware/kicad/README.md` (Task 5) ✓,
  end-to-end testing plan from the spec (Task 6) ✓. No GUI/MCP/`make pcb`
  work included, per the spec's explicit exclusions.
- **Placeholder scan:** no TBD/TODO; every step shows the literal
  before/after file content or an exact runnable command.
- **Type consistency:** N/A (shell/config, not typed code) — the one
  cross-task interface, the `KICAD_3D` arg name, is spelled identically in
  Task 1's Dockerfile and Task 2's devcontainer.json comment.
