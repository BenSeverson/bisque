# Vendored 3D models

STEP bodies for the six footprints on this board whose models KiCad 10 does
not ship, or does not ship reproducibly. `kicad_build.py`'s `MODEL_FIXUP`
points those footprints here via `${KIPRJMOD}/3dmodels/<stem>.step`, so
`make pcb-render` works on a clean clone with nothing installed by hand.

| File | Used by | Source |
|---|---|---|
| `ESP32-S3-WROOM-1U.step` | U1 | [espressif/kicad-libraries](https://github.com/espressif/kicad-libraries) `3dmodels/espressif.3dshapes/ESP32-S3-WROOM-1U.STEP` |
| `SW_Push_1P1T_XKB_TS-1187A.step` | SW1, SW2 | EasyEDA/LCSC **C318884** |
| `USB_C_Receptacle_HRO_TYPE-C-31-M-12.step` | J1 | EasyEDA/LCSC **C165948** |
| `QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm.step` | U7 | EasyEDA/LCSC **C515890** |
| `Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm.step` | Y1 | EasyEDA/LCSC **C2838127** (`c_rotation 0,0,0`; the STEP's internal filename names the package, `OSC-SMD_4P-L3.2-W2.5-…`, because EasyEDA shares one body across the 3225 4-pad family) |

8.8 MB of that is U1; the whole directory is ~15.9 MB on disk and ~2.8 MB of
git objects, since STEP is text and compresses about 6:1.

## Why vendored rather than fetched

Because the failure mode is silence. `kicad-cli pcb render` exits 0, prints
"Loading 3D models…", and omits any part whose model it cannot find. Nothing
warns you, and the render still looks like a render — a missing body reads as
a footprint with no part fitted, which is a thing that also happens on purpose
(DNP). Both ways of not vendoring leave that trap armed:

- The system path (`${KICAD10_3DMODEL_DIR}`) is not reproducible. A fresh
  clone never had a hand-installed file, and a KiCad upgrade wipes one out of
  an app bundle.
- A fetch script re-arms it every time it is skipped, and it will be skipped,
  because the renders are already a manual step.

The committed images in `3d/` are the reference for "does this board look
right", so reproducing them has to be the default rather than a setup chore.

## Refreshing an LCSC model

The four LCSC models come from the same EasyEDA component API that
`generator/lcsc_pads.py` already uses for CPL land patterns. A part's
`packageDetail` carries an `SVGNODE` shape whose `attrs` hold the 3D model's
uuid, and the STEP is served from `modules.easyeda.com`:

```bash
curl -sS "https://easyeda.com/api/products/C318884/components?version=6.4.19.5" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)["result"]
pkg=d.get("packageDetail") or d
for s in pkg["dataStr"]["shape"]:
    if s.startswith("SVGNODE"):
        a=json.loads(s.split("~",1)[1])["attrs"]
        print(a["uuid"], a.get("c_rotation"), a.get("title"))'
```

```bash
curl -sSL -o SW_Push_1P1T_XKB_TS-1187A.step \
  "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/<uuid>"
```

**Read `c_rotation` when you do.** EasyEDA stores a per-model display rotation
beside the geometry and authors the STEP in the *unrotated* frame, so a part
with a non-zero `c_rotation` lands wrong with no offset that can fix it. J1 is
the case here: unrotated its shell sits ~8.9 mm north of its own pads, which
looks like a translation error and is not one. `MODEL_FIXUP` carries the 180°
as `rotate`. C515890's `c_rotation` is `0,0,90` and is deliberately not
applied — a square QFN is invariant under it, so honouring it would be an
untestable claim in the table.

After any change here, re-render and look:

```bash
make pcb-render
```
