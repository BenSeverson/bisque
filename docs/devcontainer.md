# Local development in a VS Code dev container

The `.devcontainer/` config gives you a reproducible, full firmware + web
toolchain locally — no hand-installing ESP-IDF, Node, or the static-analysis
tools. It pins the **exact image CI uses** (`espressif/idf:v6.0.2`, target
`esp32s3`) so a local build matches the PR check, and bundles the Claude Code
CLI so Claude runs inside the same environment.

> Developing without a laptop instead? See [cloud-dev.md](cloud-dev.md) for the
> Claude Code on the web setup.

## Open it

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and
   the VS Code **Dev Containers** extension (`ms-vscode-remote.remote-containers`).
2. Open the repo in VS Code and run **Dev Containers: Reopen in Container**.

The first build pulls the Espressif image and installs `esp-clang` (~2–4 GB, a
few minutes). Subsequent opens are cached and fast. On create, `npm ci` installs
the `web_ui` deps and a readiness banner prints the tool versions.

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

## What doesn't — flashing

`idf.py flash monitor` needs the physical ESP32-S3 on a bench and USB
passthrough, which Docker Desktop does not provide on macOS (and is awkward on
Windows). Flash and run on-hardware tests from the **host**, not the container —
the same boundary documented in [cloud-dev.md](cloud-dev.md). On a Linux host
you can pass a serial device through by adding a `runArgs` entry to
`.devcontainer/devcontainer.json`, e.g. `"runArgs": ["--device=/dev/ttyACM0"]`.

## Claude Code auth

`.devcontainer/devcontainer.json` bind-mounts your host `~/.claude` into the
container so your existing login and global config carry over, and the repo's
committed `.claude/settings.json`, hooks, and skills apply as usual. If your
host has no `~/.claude`, remove that `mounts` entry and run `claude` once inside
the container to log in.

## Note on the `.vscode/` settings

The repo's `.vscode/` files are gitignored and host-specific — they hold
absolute ESP-IDF paths (`/Users/.../.espressif/...`) and a host serial port.
Because VS Code **workspace settings override** the dev container's settings,
the ESP-IDF extension may surface those stale host paths inside the container.

The robust in-container workflow is the **integrated terminal** (`idf.py` /
`make`) plus C/C++ IntelliSense, which reads `build/compile_commands.json`
(regenerated in-container with correct paths). If you use the ESP-IDF
extension's UI in the container, point it at the container toolchain by setting
`idf.espIdfPath` to `/opt/esp/idf` and `idf.toolsPath` to `/opt/esp` in your
local `.vscode/settings.json`.
