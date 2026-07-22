# Devcontainer KiCad 10 Design

## Context

The local `.devcontainer/` (Docker Desktop + VS Code Dev Containers) gives a
reproducible firmware + web toolchain, but installs no KiCad at all. The
`hardware/kicad/generator/` pipeline — the single source of truth for the
PCB (`design.py` → `kicad_build.py`/`check_netlist.py`/`check_pcb.py` via
`pcbnew` Python + `kicad-cli`) — hard-requires **KiCad 10+** (KiCad 7
support was dropped in `c5801e6`). Anyone opening the devcontainer to have
Claude Code edit the board today has no working `kicad-cli`/`pcbnew`; a bare
`apt-get install kicad` on the container's Ubuntu base would only reach
KiCad 7 from Ubuntu universe, which the generator no longer supports.

Cloud Claude Code sessions already solve this via
`.claude/hooks/install-kicad.sh`, wired into `session-start.sh`: it adds
`ppa:kicad/kicad-10.0-releases` and installs `kicad kicad-symbols
kicad-footprints`, gated behind a preflight check for the cloud sandbox's
network policy (skips cleanly if `ppa.launchpadcontent.net` is blocked).
That script is cloud-specific — a local Docker build isn't network-policy
sandboxed, so the same install belongs baked into the devcontainer's
`Dockerfile` as a cached image layer, not re-run at every container start.

## Approach

Add a `RUN` layer to `.devcontainer/Dockerfile` that installs KiCad 10 from
the same PPA `install-kicad.sh` uses, following the same
add-apt-repository → trusted-repo fallback for resilience against a blocked
keyserver. Unlike the cloud script, this layer does **not** preflight-check
and silently skip — a local image build has normal internet access, so if
the PPA is unreachable the build should fail loudly like any other missing
dependency.

This only changes the **local** devcontainer. `install-kicad.sh` /
`session-start.sh` for cloud sessions are untouched — they remain the
correct mechanism for the network-policy-gated cloud sandbox.

## Dockerfile Changes

New `RUN` block after the existing esp-clang layer, before the shell-init
line:

```dockerfile
# KiCad 10 for the hardware/kicad generator pipeline (pcbnew Python API +
# kicad-cli). Ubuntu's own repo only ships KiCad 7, which the generator no
# longer supports (see hardware/kicad/README.md) — pull from the official
# PPA instead. Mirrors .claude/hooks/install-kicad.sh's install logic
# (kept in sync manually: same PPA, same package list); unlike that script,
# this layer does not preflight/skip on a blocked network, since a local
# Docker build isn't sandboxed the way a cloud session is — a failure here
# should fail the image build, not silently degrade.
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
```

`kicad-cli version` at the end fails the build immediately if the install
didn't actually work, rather than surfacing a confusing failure later at
`kicad_build.py` runtime.

## devcontainer.json Changes

Pass the new build arg through so 3D models are a one-line opt-in without
touching the Dockerfile:

```jsonc
"build": {
  "dockerfile": "Dockerfile"
  // Uncomment to also pull kicad-packages3d (~6 GB) for kicad-cli pcb render:
  // , "args": { "KICAD_3D": "1" }
},
```

Default stays `KICAD_3D=0` (no `args` key) — matches `install-kicad.sh`'s
default, keeps the base image build fast, and most editing sessions
(`design.py` changes → `check_netlist.py`/`check_pcb.py`) never touch
rendering.

## postCreate.sh Changes

Add a line to the existing readiness banner, alongside idf.py/node/claude:

```bash
echo "  kicad  : $(kicad-cli version 2>/dev/null || echo 'n/a')"
```

## Documentation Changes

**docs/devcontainer.md** — add a row to the "What works" table:

| Task | Command |
|---|---|
| PCB/schematic regen + validation | see `hardware/kicad/README.md` (`generator/gen_sch.py`, `check_netlist.py`, `kicad_build.py`, `check_pcb.py`) |

Plus a short paragraph noting KiCad 10 (`kicad-cli` + `pcbnew` Python) is
baked into the image, so the generator pipeline works out of the box —
no macOS-style `KPY` bundled-Python path needed, since apt-installed KiCad
on Linux binds directly to the container's system `python3`.

**hardware/kicad/README.md** — one-line addition to the "Regenerating the
files" section noting the devcontainer provides a ready KiCad 10 + pcbnew
environment as an alternative to installing KiCad natively.

## What's Explicitly Out of Scope

- **No GUI KiCad in the container.** The repo's workflow is entirely
  script-driven (`design.py` regeneration); nothing here needs a KiCad
  window, and X11/noVNC forwarding would add real complexity for no
  documented use case. A human wanting to visually inspect the board still
  opens `bisque-controller.kicad_pro` in native KiCad on the host, per the
  existing README instructions.
- **No KiCad MCP server.** LLM-driven editing means Claude Code editing
  `design.py` and running the generator scripts inside the container, the
  same workflow already documented in `hardware/kicad/README.md` — not a
  new tool-calling interface into KiCad internals.
- **No `make pcb` target.** Left as the documented command sequence in
  `hardware/kicad/README.md`; not part of this change.

## Testing Plan

Can't build/run Docker from this environment. After the Dockerfile change
lands, verify manually:

1. VS Code: **Dev Containers: Rebuild Container** (forces the new layer to
   build, not just reuse a cached image).
2. In the container terminal:
   ```bash
   kicad-cli version                    # expect 10.x
   python3 -c "import pcbnew; print(pcbnew.Version())"   # expect 10.x, no ImportError
   ```
3. Run the actual generator pipeline end-to-end against the real board
   files, from `hardware/kicad/`:
   ```bash
   python3 generator/gen_sch.py bisque-controller.kicad_sch
   python3 generator/check_netlist.py bisque-controller.kicad_sch   # must PASS
   python3 generator/kicad_build.py bisque-controller.kicad_pcb
   python3 generator/check_pcb.py bisque-controller.kicad_pcb       # ALL CHECKS PASS
   ```
   then `git diff` / `git checkout -- hardware/kicad/` to discard the
   regenerated output if it's only a smoke test.
4. Confirm the postCreate banner prints a `kicad` version line on container
   create.

If step 2 or 3 fails, the most likely cause is a footprint library path
mismatch — `kicad_build.py`'s `_find_fp_base()` already searches
`/usr/share/kicad/footprints` and `/usr/share/kicad*/footprints`, which is
where the apt package installs them, so this should resolve without needing
`KICAD_FOOTPRINT_DIR` set explicitly.
