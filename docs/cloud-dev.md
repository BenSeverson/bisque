# Developing Bisque without a laptop (Claude Code on the web)

Bisque can be developed entirely from a browser or the Claude mobile/desktop
app using **Claude Code on the web**. Each session runs in an isolated,
ephemeral cloud container: the repo is cloned fresh on start and the container
is reclaimed after inactivity, so **anything worth keeping must be committed and
pushed**. See the [Claude Code on the web docs][docs].

With the network policy configured as described below, a cloud session builds
**the same artifacts CI builds** — same ESP-IDF version, same pinned component
versions, same static analysis. Flashing and on-hardware testing are the only
things that genuinely need a bench.

> Developing locally instead? The VS Code dev container gives you the same
> toolchain on your own machine — see [devcontainer.md](devcontainer.md).

## Set the network policy first

This is the one piece of setup that cannot be done from inside a session, and
almost everything else depends on it.

The container reaches the network through a policy chosen **per environment**,
in the Claude Code web or desktop app's environment settings. The default policy
allows GitHub and the language registries (npm, PyPI) but blocks the Espressif
and Launchpad hosts, which is enough for the web UI and the host C tests but not
for firmware or the PCB pipeline.

Allow these hosts:

| Host | Needed for | Unlocks |
|---|---|---|
| `github.com` | ESP-IDF sources; most toolchain archives | firmware |
| `objects.githubusercontent.com` | GitHub release asset downloads | firmware |
| `dl.espressif.com` | Python dependency constraints; some tool archives | firmware |
| `components.espressif.com` | component registry — resolves `idf_component.yml` | firmware |
| `components-file.espressif.com` | component archive downloads | firmware |
| `ppa.launchpadcontent.net` | KiCad 10 packages | PCB pipeline |
| `api.launchpad.net` | PPA lookup by `add-apt-repository` (launchpadlib) | PCB pipeline |
| `keyserver.ubuntu.com` | PPA signing key (package verification) | PCB pipeline |

The first two are already reachable under the default policy; they are listed
because the install genuinely depends on them, and because a future policy
change that dropped them would break the build in a confusing way.

`api.components.espressif.com` is **not** required, despite the name. It exists
in `idf_component_tools` only as a constant used to normalise registry URLs; a
full firmware build, including fetching all six managed components, has been
verified to succeed with that host firewalled off. Allowing it does no harm, but
a policy without it is complete.

Then **start a new session** — a running session keeps the policy it started
with.

### Why the installers refuse to work around a block

Every one of those hosts has a tempting workaround: skip the Python constraints
(`IDF_PYTHON_CHECK_CONSTRAINTS=no`), pull the tools from a mirror, vendor the
managed components from their upstream GitHub repos, install PPA packages with
`[trusted=yes]`. Each one produces a container that builds *something*, and
reports success while doing it.

That is the failure mode worth avoiding. A toolchain that resolves its Python
dependencies differently from CI, or compiles against a hand-assembled set of
components rather than the registry-pinned ones, gives you a green build whose
green means nothing — the interesting bugs are exactly the ones that show up
when the versions differ. The installers therefore check reachability up front
and, when a host is blocked, print which one and what to do about it, rather
than degrading quietly.

## What the SessionStart hook does

`.claude/hooks/session-start.sh` runs automatically at the start of every web
session (registered in `.claude/settings.json`). It:

1. Installs the `web_ui` toolchain (`npm install`).
2. Reports the `clang-format` version (it ships in the base image).
3. Installs `cppcheck` from the Ubuntu archive — no special policy needed.
4. Runs `install-sim-deps.sh` — SDL2 plus LVGL pinned to the version in
   `dependencies.lock`, so `make sim` works. Also no policy change needed.
5. Runs `install-esp-idf.sh`, which preflights the Espressif hosts and then
   installs ESP-IDF v6.1 + the esp32s3 tools + esp-clang (for clang-tidy).
6. Runs `install-kicad.sh`, which preflights the Launchpad hosts and then
   installs KiCad 10 with `pcbnew`, the 3D model pack and Xvfb, and exports
   `KPY` for the session (see below).
7. Prints a summary of what this session can actually do.

Both installers are no-ops on a warm container (state is cached between
sessions) and exit within seconds when their hosts are blocked, so a restricted
session still starts fast.

The "can I use this?" checks in `.claude/hooks/lib/toolchain.sh` are functional,
not presence-based, and are shared by the installers and the summary so they
cannot disagree. That matters more than it sounds: `~/esp-idf/export.sh` exists
after a *failed* install, and the stock image already has a `kicad-cli` several
major versions too old for the board generator. Reporting either as available
sends you off to build with a toolchain that will fail or, worse, quietly
produce the wrong artifact.

## What works in the cloud container

| Task | Command | Default policy | Policy configured |
|---|---|---|---|
| Web UI build / dev | `make web`, `npm run dev` | ✅ | ✅ |
| Web UI tests | `make test-web` | ✅ | ✅ |
| Web typecheck / lint / format | `make lint-web` | ✅ | ✅ |
| C formatting check | `make lint-c` | ✅ | ✅ |
| Host C unit tests | `make test-host` | ✅ | ✅ |
| cppcheck | `make cppcheck` | ✅ | ✅ |
| **LCD simulator** | `make sim`, `make sim-verify` | ✅ | ✅ |
| Docs & SVG diagrams | edit directly | ✅ | ✅ |
| **Firmware build** | `idf.py build` | ❌ | ✅ |
| clang-tidy | `make clang-tidy` | ❌ | ✅ |
| **PCB regeneration + checks** | `make pcb-build`, `make pcb-cosmetic`, `make pcb-check` | ❌ | ✅ |
| PCB fab outputs + 3D renders | `make pcb-fab`, `make pcb-render` | ❌ | ✅ |
| **Firmware flash / monitor** | `idf.py flash monitor` | ❌ | ❌ (needs hardware) |

The PCB targets work only because `install-kicad.sh` exports **`KPY`** through
`$CLAUDE_ENV_FILE`, pointing it at `.claude/hooks/kicad-python`. The Makefile
already honours `KPY` (it is how macOS finds KiCad.app's bundled Python), so no
target changes, and nothing sets it on a laptop. It exists because the obvious
interpreters are all wrong here, in three different ways:

- `python3` on `PATH` is the ESP-IDF virtualenv once IDF is activated — no
  system site-packages, so no `pcbnew` at all.
- `/usr/bin/python3` is **3.11** (the image's alternative), while the PPA builds
  KiCad for noble's 3.12. It still *imports* `pcbnew`, because `_pcbnew.so` has
  no ABI tag and drags `libpython3.12` into the process, so the Makefile's own
  search picks it; most checkers then pass, and the first script that imports
  `wx` (ABI-tagged, 3.12 only) dies. `check_placement.py` is the one that shows
  it, with an `AttributeError` from a half-initialised `wx` package.
- `python3.12` is right, but the generator calls `wx.App(False)`, which GTK
  refuses without an X server: "Unable to access the X Display".

The wrapper picks the interpreter that can import **both** `pcbnew` and `wx`
(`toolchain_kicad_python` in `lib/toolchain.sh`) and runs it against one
long-lived Xvfb on `:87`, set for that process only — a session-wide `DISPLAY`
would change what SDL and anything else probing for a display does. It does
not use `xvfb-run`, which merges stderr into stdout. Run a generator script by
hand the same way: `$KPY hardware/kicad/generator/kicad_build.py
hardware/kicad/bisque-controller.kicad_pcb`.

`install-kicad.sh` also installs **`kicad-packages3d`** (424 MB download, 3.2 GB
on disk, ~40 s; `KICAD_3D=0` skips it). Without it `make pcb-render` still exits
0 but draws only the six models vendored in `hardware/kicad/3dmodels/` — every
passive, IC and terminal block renders as bare pads. `check_3dmodels.py` cannot
catch that either: when the stock model directory is absent it skips every
`${KICAD10_3DMODEL_DIR}` reference rather than failing them. The session summary
says which state you are in.

Measured on a 4-core container, all byte-identical to the committed board:
`pcb-check` ~20 s, `pcb-cosmetic` ~110 s, `pcb-build` ~13 min (the README's
figures are from an Apple Silicon Mac, roughly 2-2.5x faster), `pcb-render` ~45 s.

Nor is the explicit board path. `kicad_build.py` defaults its output to a bare
`bisque-controller.kicad_pcb` resolved against the current directory, so run
from the repo root without an argument it writes a new top-level board and DRC
report and leaves the tracked one alone — a regeneration that looks like it
worked and changed nothing. Name the output, or `cd hardware/kicad` first as
`hardware/kicad/README.md` does.

The simulator is the one to reach for when changing `components/display/`: it
renders every screen against real LVGL and diffs the result, so a UI regression
is caught without a bench. `install-sim-deps.sh` sets it up from the Ubuntu
archive and GitHub, both reachable by default, so it works even in a session
with no policy changes at all.

## Building firmware

Once the policy is set and the session has restarted:

```bash
idf.py set-target esp32s3
idf.py build
```

`idf.py` is on `PATH` already — the installer appends `export.sh` to
`$CLAUDE_ENV_FILE`, which every shell in the session sources.

The full local approximation of the PR check is `make ci`. Note the firmware
build bundles the gzipped web assets into the SPIFFS image, so `make web &&
make gzip` (or just `./build.sh`) must run first if you have not built the web
UI in this session.

## Troubleshooting

**"network policy blocks the hosts below"** — the policy is not set, or the
session predates the change. Set it as above and start a new session.

**"found an incomplete ESP-IDF … reinstalling"** — a previous install did not
finish. The installer repairs it automatically when the hosts are reachable.

**"ESP-IDF installed but does not activate cleanly"** — the install finished but
`export.sh` fails, usually a missing constraints file from a partially-allowed
policy. Confirm every Espressif host above is allowed, then re-run
`.claude/hooks/install-esp-idf.sh`.

**`make pcb-*` fails with "Unable to access the X Display", or
`check_placement.py` with `AttributeError: partially initialized module 'wx'`**
— `KPY` is not set in this shell, so the Makefile fell back to a bare
interpreter (see above). The session's env file sets it; a shell started some
other way can `export KPY="$PWD/.claude/hooks/kicad-python"` from the repo root.

**`make pcb-render` output shows bare pads where parts should be** — the 3D
model pack is missing. Re-run `.claude/hooks/install-kicad.sh` (without
`KICAD_3D=0`), and do not commit the render you have.

**`make sim` reports "lvgl.h: No such file or directory"** — the LVGL clone is
missing. Re-run `.claude/hooks/install-sim-deps.sh`; it re-clones the pinned
version into `managed_components/lvgl__lvgl`.

**A screenshot scene fails after a `components/display/` change** — if the
change was intentional, refresh the baselines with
`./simulator/build/bisque_sim --screenshot` and eyeball the result; the README
screenshots come from the same files. Run `make sim-verify` too: it asserts on
dashboard state rather than pixels, so it catches regressions the diff cannot
see (see the note in CLAUDE.md).

[docs]: https://code.claude.com/docs/en/claude-code-on-the-web
