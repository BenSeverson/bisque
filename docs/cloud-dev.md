# Developing Bisque without a laptop (Claude Code on the web)

Bisque can be developed entirely from a browser or the Claude mobile/desktop
app using **Claude Code on the web**. Each session runs in an isolated,
ephemeral cloud container: the repo is cloned fresh on start and the container
is reclaimed after inactivity, so **anything worth keeping must be committed and
pushed**. See the [Claude Code on the web docs][docs].

> Developing locally instead? The VS Code dev container gives you the same
> toolchain on your own machine — see [devcontainer.md](devcontainer.md).

## What the SessionStart hook sets up

`.claude/hooks/session-start.sh` runs automatically at the start of every web
session (registered in `.claude/settings.json`). It:

1. Installs the `web_ui` toolchain (`npm install`) so the dashboard build, its
   Vitest suite, and the typecheck/lint/format checks work immediately.
2. Reports the `clang-format` version (it ships in the base image, so the C
   formatting checks in `make lint` already work).
3. Calls `install-esp-idf.sh` to set up the firmware toolchain **if** the
   network policy allows it (see below).

## What works in the cloud container

| Task | Command | Works in cloud? |
|---|---|---|
| Web UI build / dev | `make web`, `npm run dev` | ✅ |
| Web UI tests | `make test-web` | ✅ |
| Web typecheck / lint / format | `make lint-web` | ✅ |
| C formatting check | `make lint-c` | ✅ (clang-format in base image) |
| Host C unit tests | `make test-host` | ✅ (cmake + gcc + ctest present) |
| Docs & SVG diagrams | edit directly | ✅ |
| **Firmware build** | `idf.py build` | ⚠️ needs ESP-IDF + network policy (below) |
| clang-tidy / cppcheck | `make clang-tidy` / `make cppcheck` | ⚠️ needs ESP-IDF toolchain |
| **Firmware flash / monitor** | `idf.py flash monitor` | ❌ needs physical ESP32-S3 hardware |

Flashing and on-hardware testing are the only things that genuinely require a
bench. Building firmware is just cross-compilation and works in the cloud once
the toolchain is installed.

## Enabling firmware builds in the cloud

`idf.py build` needs the ESP-IDF v6.0.2 toolchain (the version CI pins — see
`.github/workflows/build.yml`). Installing it pulls from Espressif hosts that
are **blocked under the default network policy**:

- `dl.espressif.com` / `*.espressif.com` — compiler & tool downloads
- `api.components.espressif.com` — the component registry the build resolves
  `idf_component.yml` deps from into `managed_components/`

### Step 1 — allow the Espressif hosts in the network policy

The network policy is chosen per environment in the Claude Code web/desktop app
environment settings (it can't be changed from inside a session). Pick a policy
that permits outbound access to:

```
github.com, codeload.github.com   (already reachable)
dl.espressif.com
*.espressif.com
api.components.espressif.com
```

### Step 2 — restart the session

On the next session start, `install-esp-idf.sh` detects that the registry is
reachable and installs the toolchain (~2 GB, a few minutes on first run). It:

- installs OS prerequisites via apt (tolerant of blocked third-party PPAs),
- shallow-clones `esp-idf` at `v6.0.2` and runs `install.sh esp32s3`,
- appends `. ~/esp-idf/export.sh` to `$CLAUDE_ENV_FILE` so `idf.py` is on PATH
  for the session.

The container caches state after the hook, so subsequent sessions are a fast
no-op. Until the policy is enabled, the script detects the block and exits in a
few seconds without slowing session startup — firmware build stays CI-only.

### Step 3 — build

```bash
idf.py set-target esp32s3
idf.py build
```

[docs]: https://code.claude.com/docs/en/claude-code-on-the-web

## KiCad (custom PCB pipeline)

The `hardware/kicad/` generator (`kicad_build.py`, `check_netlist.py`,
`render-3d.sh`) needs KiCad 9/10 — newer than the base image provides. The
KiCad PPA is **blocked under the default network policy**:

- `ppa.launchpadcontent.net` — the KiCad 10 package repository
- `keyserver.ubuntu.com` / `api.launchpad.net` — PPA signing key (optional;
  the installer falls back to a trusted-repo entry inside the sandbox)

Allow those hosts in the environment's network policy and restart the
session; `install-kicad.sh` then adds `ppa:kicad/kicad-10.0-releases` and
installs `kicad`, `kicad-symbols` and `kicad-footprints` (~1.5 GB, cached
across sessions). Set `KICAD_3D=1` to also pull `kicad-packages3d` (~6 GB)
if you want component models in `kicad-cli pcb render` output.

Until the policy is enabled the script detects the block and exits in a few
seconds; the PCB generator requires KiCad 10, so the pipeline stays
unavailable in cloud sessions until then.
