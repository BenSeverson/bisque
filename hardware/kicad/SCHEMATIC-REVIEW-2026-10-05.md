# Schematic and PCB review — 2026-10-05

**Updated component findings:** see
[the PCB review](PCB-REVIEW-2026-10-05.md) for the newly added exact
part sheets, Samsung bias curves, and recommended fixes. It identifies substantial C41/C42
capacitance loss, further watchdog/ESR/flyback qualification gaps, and a
USB rail-clamp mismatch; the original findings below remain applicable.

Reviewed the Rev B.2 design at commit `3a63e46`, including the generated
schematic, exported netlist, routed board, fabrication outputs, assembly
tables, relevant firmware, installation instructions, and component datasheets.
This is a review of the committed design; no circuit, layout, or firmware was
changed. The source for future changes is `generator/design.py` and the related
generators, rather than manual edits to the generated KiCad files.

## Assessment

The routing and fabrication package are consistent and pass the geometry checks
performed here. There are electrical issues that those checks cannot detect.
I would resolve the input protection coordination and the claimed current range
before a production release, and explicitly specify the exposed-pad assembly
process before placing an assembly order. A small prototype run on a clean,
current-limited supply can still be useful for the remaining measurements, with
the restrictions below recorded in its build instructions.

Two findings contradict assumptions in the current generator comments:

- The SMAJ30A's **48.4 V clamp** is above the downstream buck/diode ratings.
  The claim that an absolute maximum applies only to DC is incorrect.
- Channel A's new IAN filter does **not** balance the CT signal while R33
  still references the negative end to ground. Its nominal input-pin range
  remains approximately **69 A rms**, rather than the advertised 139 A.

The independent heater cutoff is an installation requirement, and must be
settled before commissioning heat. The PCB watchdog does not cover every
external wiring fault or a failed load-side SSR.

Priority definitions: **P1** requires resolution before deployment/production;
**P2** requires a design decision, operating restriction, or first-article
measurement; **P3** is a documentation or robustness improvement. Confidence
and conditions are stated separately from priority. No bench performance was
measured in this review.

## Findings

### 1. P1 — Input TVS, buck, catch diode, and fuse are not coordinated

**Confirmed rating mismatch; exposure depends on the applied fault/surge.**
References: `generator/design.py:278–297`, `:559–613`; F1, D8, Q8, U11, D7.

D8 is R+O SMAJ30A, LCSC C19077547. Its 30 V rating is its reverse
stand-off voltage. The selected manufacturer's table gives breakdown of
33.3–36.8 V at 1 mA and a clamp of **48.4 V at 8.3 A**. U11 XL1509 has
a **40 V operating input maximum and 45 V absolute maximum**. D7 SS34 is
a **40 V** rectifier. Q8 passes a positive overvoltage; D11 protects Q8's
gate rather than limiting the supply. Thus the rated TVS pulse can exceed
both downstream ratings. The actual board voltage also depends on source
impedance and wiring inductance; survival has not been established.
[Selected R+O datasheet](https://datasheet.lcsc.com/datasheet/pdf/55ccf1c46f874447a5c4c88bdfecf89c.pdf?productCode=C19077547),
[XL1509 datasheet, Rev 1.2, page 4](https://www.xlsemi.com/datasheet/XL1509-CN.pdf).

The comment at line 287 dismisses the mismatch because it is a surge. An
absolute maximum is not a blanket permission to exceed the rating during a
transient. Any allowed transient excursion needs a specific manufacturer
rating or qualification. TVS breakdown at its test current also does not
define a fixed 33–37 V clamp under an arbitrary sustained fault.
[TI protection design guidance, section 2.1](https://www.ti.com/lit/an/slva930/slva930.pdf).

The PPTC argument needs revision too. F1 holds 0.75 A and trips at 1.5 A
at 25°C; a current-limited overvoltage can heavily dissipate D8 while remaining
below F1's hold current. For example, 0.5 A at roughly 35 V is about 17.5 W
in the TVS and does not guarantee fuse operation. The statement that a 33 V
PPTC makes the input safe to approximately 67 V assumes the downstream node
remains at the TVS breakdown voltage throughout the fault. That assumption
does not hold after a TVS failure or collapse of the protected rail.
[Jinrui family ratings, page 3](https://datasheet.lcsc.com/datasheet/pdf/bf3f0b74de54755047f1f9ac46a3e07e.pdf?productCode=C369172).

**Action:** define the maximum normal input, source impedance, sustained
misconnection cases, and required surge waveform. Coordinate the clamp with
U11, D7, input capacitors, SSR inputs, and F1 over temperature. Options include
a lower clamp with an appropriate maximum-normal-voltage restriction,
higher-rated downstream parts, or an overvoltage disconnect. A lower TVS must
also tolerate the documented 26.4 V PSU setting. Validate fault energy and
clearing time; selecting another nominal TVS voltage alone is insufficient.

> **Status 2026-10-27:** coordinated, by defining the envelope and raising
> the two parts that had no margin, not by changing the TVS. The HDR-15-24
> trims to **29 V** (its sheet: 21.6–29 V), so a lower TVS is ruled out —
> an SMAJ28A stands off 28 V. Under the envelope (in-enclosure supply,
> ≤ 1 A limit, wiring stays in the box) the SMAJ30A's own table bounds the
> rail at 36.8 V + 1.4 Ω × I: ≤ 38.1 V at the HDR-15-24's 0.91 A limit,
> ≤ 40 V up to F1's 2.3 A, 45 V (U11 abs max) only at 5.8 A, 48.4 V only
> on the 10/1000 µs pulse. D7 SS34 → **SS36** (60 V, C7420367) and D9/D10
> B5819W → **1N4007W** (1 kV, C3018540), both in the same lands. Q8 is
> not stressed in a forward fault (body diode conducts, D11 clamps the
> gate). The sustained current-limited case ends with D8 failing short at
> ≤ 38 V, which is the intended outcome. Written out at F1, D7 and D9 in
> `DESIGN-NOTES.md`. Still named as open: the external SSR input at 29 V /
> 38 V (installation check A4) and a field-surge rating or 60 V buck (rev C).

### 2. P2 — Channel A still exceeds its pin range above approximately 69 A

**Confirmed by netlist and linear AC analysis; clipping not bench-observed.**
References: `generator/design.py:2025–2076`; R31–R33, R59, C31, C40, U7.

The exported schematic connects R33 = 1 kΩ from CTA_N to ground. R59/C40
now take CTA_N to IAN, but there is no symmetric DC ground reference on
CTA_P. At 50/60 Hz the 33 nF capacitors have much higher impedance than R33,
so nearly the entire burden signal remains on IAP. The ADE7953 specifies
**±250 mV maximum per channel A input pin at gain 1**; ±500 mV differential
requires the appropriate common-mode distribution.
[ADE7953, page 19, Table 6 footnote](https://www.analog.com/media/en/technical-documentation/data-sheets/ADE7953.pdf).

For an ideal floating 2000:1 CT, 5.1 Ω burden, the two 1 kΩ/33 nF filters,
and the datasheet's 50 MΩ input resistances, the calculated values are:

| Primary current | Frequency | IAP peak | IAN peak | Differential peak |
|---|---|---|---|---|
| 100 A rms | 50 Hz | 360.49 mV | 3.74 mV | 360.60 mV |
| 100 A rms | 60 Hz | 360.44 mV | 4.48 mV | 360.59 mV |

IAP reaches 250 mV at approximately **69.35 A rms**. These are nominal
calculations, not a guaranteed calibrated operating limit; burden, CT, and
component tolerances need margin. A 25–40 A kiln circuit is below this nominal
pin limit, but the current 100 A/139 A description is not supported for A.
The earlier review's A10 resolution is therefore incomplete.

**Action:** either implement a genuinely balanced burden/reference network
(for example, equal burden halves with their midpoint grounded and symmetric
filters), lower channel A's burden for the required range, or explicitly
restrict and document its range. A roughly 2.55 Ω burden would halve the
present pin amplitudes without requiring a balanced signal, but changes
calibration and must be sourced and verified. Check gain settings and both
channels with a known current; do not repair clipping with a software scale
factor.

> **Status 2026-10-26:** balanced reference implemented. R65 (1 k, CTA_P to GND) mirrors R33, so the floating secondary sits at ±V/2 on IAP/IAN and the ±250 mV pin limit is reached at the same 139 A nominal as channel B. Burden unchanged; the calibration constant is unchanged. Bench check with a known current is still on the first-article list.

### 3. P1 — A grounded SSR return bypasses the watchdog; cutoff documentation conflicts

**Confirmed architecture limitation, already noted in the September review.**
References: `generator/design.py:1145–1413`,
`jlcpcb/README.md:126–145`, `../enclosure/README.md:36` and `:81`.

J4/J9 pin 1 is always-live VIN_P. Q5/Q6 switch each return, and Q7 opens
their shared return when the watchdog expires. If an OUT wire shorts to the
grounded metal enclosure, current bypasses both switches: that SSR's control
input stays energized even with the MCU and watchdog off. A load-side SSR
failed short is another fault the PCB cannot interrupt.

The assembly README correctly calls for an independent contactor/cutout,
while the enclosure BOM calls the contactor merely "strongly recommended"
and includes a "≤25 A per zone, no contactor" configuration.

**Action:** make the independently operated, load-rated cutoff a requirement
for the heater installation, with its own temperature sensing/manual-reset
policy and E-stop wiring as appropriate. Remove the conflicting installation
option. If this PCB is expected to contain a return-to-ground fault by itself,
the power interruption architecture needs a redesign, such as appropriately
protected high-side interruption. More firmware checks cannot open a
ground-short bypass path.

> **Status 2026-10-28, rev B.4:** redesigned rather than documented around.
> Both channels now switch the **+** side with 60 V P-channel LP2309LT1Gs
> (Q5/Q6, source on `SSR_24V`, drain on the terminal's pin 1) and the
> terminals' pin 2 is board GND, so a `−` lead that finds ground is the
> wiring diagram rather than a bypass. The watchdog's cutoff is a third
> LP2309LT1G (Q9) in series between `VIN_P` and `SSR_24V`, driven through
> Q7/R71/D12/R22, which restores the board-level turn-off B.1 had for a
> failed-short channel. A `+` lead on the chassis is a short the supply's
> current limit or F1 ends with the SSR off. The B.2 objection (no fee-free
> 60 V P-FET) died with the Economic tier on 2026-10-27. Derivation in
> `DESIGN-NOTES.md` (SSR block); the contactor remains required for a
> load-side SSR failed short, which no board can interrupt.

### 4. P2 — Watchdog timeout is an estimate, not the claimed guaranteed worst case

**Confirmed gap in the stated timing justification; functional topology is sound.**
References: `generator/design.py:1463–1476`, `:1514–1534`;
`components/safety/wdt_kick.h`, `components/safety/safety.c:418`.

U10 is correctly wired as a rising-edge retriggerable one-shot. However,
the **1.65–2.71 s worst-case** claim takes TI's timing bounds at a
10 kΩ/0.1 µF test point and extrapolates them to **100 kΩ/22 µF**. The
datasheet does not give those same guaranteed bounds at this combination.
The 15% capacitor bias/temperature allowance also needs evidence for the
actual purchased MLCC, including aging. This does not establish that the
watchdog fails; it means the quoted deadline is not yet guaranteed.
[SN74LVC1G123, sections 5.8–5.9 and typical timing curves](https://www.ti.com/lit/ds/symlink/sn74lvc1g123.pdf).

**Action:** characterize loss-of-edge timing over rail voltage, temperature,
and component variation, including a kick held high and a kick held low.
Use a watchdog/timer with a specified accuracy if a hard deadline is required.
Measure total fault latency too: if only the safety task hangs while its timer
continues, the 900 ms heartbeat allowance can precede the final one-shot
interval. Test MCU reset, missing 3.3 V, OTA/flash operations, emergency stop,
and boot with SJ2 open.

### 5. P2 — Seventeen open thermal vias overlap paste apertures

**Confirmed on the current PCB; previously reported by JLCDFM.**
References: `generator/gen_pcb.py:283–287`,
`generator/check_via_in_pad.py:51–96`, current F.Paste/drill exports.

Independent pad/via hit-testing gives **U7: 4, U1: 9, U2: 4** thermal
vias, all with 0.3 mm drills and centers inside a paste aperture. Tenting
does not make these epoxy-filled/capped vias. They can wick solder from
U7's hidden ground pad, the ESP32 module ground pad, and U2's thermal tab.
The via-in-pad checker deliberately exempts these EP grids, so its PASS
does not close this assembly risk.

**Action before assembly order:** specify a suitable filled/capped via-in-pad
process with the assembler, or change via/paste geometry to a qualified
process. JLC offers epoxy-filled/capped vias on four-layer boards as an extra
process. If accepting the existing geometry for prototypes, explicitly arrange
inspection of hidden joints and verify U7 ground continuity and U2 thermal
performance; do not infer joint quality from DRC.
[JLC via covering process descriptions](https://jlcpcb.com/help/article/pcb-via-covering).

### 6. P2 — External input protection has narrower coverage than its names suggest

**Confirmed connectivity; damaging fault outcomes depend on the source.**
References: `generator/design.py:1742–1812`, `:2100–2119`; D5, D6, J11, J12.

J11 is suitable for **dry contacts to GND**, not powered 24 V field sensors.
D5's steering paths reach the 3.3 V rail on the connector side of the series
resistors. A sustained 24 V miswire can inject into the entire 3.3 V rail;
the 1 kΩ resistors at the GPIOs do not limit that upstream injection. Specify
the interface clearly on wiring instructions and use an appropriate input
stage if powered industrial sensors are in scope.

D6 on J12 similarly steers positive CT-terminal excursions toward 3.3 V.
That does not by itself ensure U7's **+2 V analog-input absolute maximum**
is respected during a sustained overrange or wrong sensor connection. The
RC filters help fast pulses but do not attenuate DC at these high-impedance
inputs. This is an unqualified protection path, not evidence of damage during
normal CT operation.
[ADE7953, page 8 absolute maximum table](https://www.analog.com/media/en/technical-documentation/data-sheets/ADE7953.pdf).

**Action:** define allowed sensor types and fault voltages, and qualify the
clamp/filter network against the AFE limits and acceptable leakage/accuracy.
Lock the CT ratio, current-output versus voltage-output type, polarity, and
insulation rating. For a current-output CT, specify how an open secondary is
prevented or limited when the PCB connector is disconnected; the board burden
cannot protect a CT once its wires are removed.

### 7. P2 — Aux outputs are outside the hardware watchdog and need a load specification

**Confirmed architectural limitation; importance depends on auxiliary function.**
References: `generator/design.py:1580–1628`; U6, J10, SJ1.

ULN2003 inputs are pulled low at reset, but an otherwise hung MCU can leave
an AUX GPIO high indefinitely. Q7 and the one-shot do not interrupt AUX_VP
or the ULN return. If an auxiliary is assigned a safety-related gas valve,
there is no independent deenergization path in this circuit. Define each
auxiliary's required fault state; a cooling fan or purge function can have
different requirements from a fuel valve.

The "500 mA per channel" description is also not a guaranteed useful load
at 3.3 V drive. TI specifies increasing input voltage with collector current,
including 2.7 V for 250 mA and 3.0 V for 300 mA at its stated conditions.
Check ESP32 minimum output voltage, ULN saturation voltage, simultaneous
channel power, and actual coil pull-in current. The selected ULN2003ADR has
a 70°C maximum rated operating ambient, which matters near a kiln.
[ULN2003A datasheet](https://www.ti.com/lit/ds/symlink/uln2003a.pdf).

**Action:** publish a validated per-channel and total load budget over the
intended temperature range. Use logic-compatible MOSFET drivers or another
specified driver if higher currents are needed. With an external coil supply,
its negative must connect to board GND and COM must connect to the coil's
positive supply. J10 does not provide a separate GND terminal, so document
the return connection explicitly.

### 8. P2 — Power, USB current, and thermal budgets require first-article evidence

**Unverified margins; no normal-operation failure established.**
References: `generator/design.py:363–424`, `:559–669`, `:688–785`;
U11, U12, U2, C38, C41–C48.

- U2 dissipates approximately `(5 − 3.3) × I3V3`: **0.85 W at 0.5 A**
  and **1.36 W at 0.8 A**. Its thermal vias are useful, but allowable current
  depends on the populated board and enclosure temperature. Measure sustained
  Wi-Fi traffic and peripheral loading, rather than treating the 1 A part
  rating as a system current rating. U2 must be the specified **LV** variant.
  [TLV1117LV datasheet](https://www.ti.com/lit/ds/symlink/tlv1117lv.pdf).
- U12 has buck priority and reverse blocking, which addresses the previous
  backfeed problem. Switching at nominal 4 V can still dip +5V into LDO
  dropout under heavy loading. The generator's 90 mV dropout calculation
  uses a typical value at 200 mA. Scope +5V/+3V3 during removal and restoration
  of J2 with USB connected, across slow ramps and load extremes.
  [TPS2116 datasheet](https://www.ti.com/lit/ds/symlink/tps2116.pdf).
- Separate 5.1 kΩ CC resistors are correct, but no source-current detection
  is implemented. USB powers the MCU, display/backlight, and potentially
  5 V auxiliaries. Establish the USB-only budget, including startup and
  pre-enumeration behavior. If it exceeds default USB current, detect the
  advertised CC current and limit consumption appropriately, or restrict
  the USB-powered configuration. [Espressif USB-C hardware guidance](https://docs.espressif.com/projects/esp-iot-solution/en/latest/usb/usb_overview/usb_typec_hardware_guide.html).
- F1's 750 mA hold figure is at 25°C. Derate it for enclosure temperature
  and include the buck input, both SSR inputs, inrush, and any loads routed
  through that fuse. The documented 0.63 A PSU also needs a separate budget
  including externally connected relay coils.
- C46 is a useful provision, but the comments' assumed ESR range and the
  parallel ceramic network do not constitute a loop-stability measurement.
  Measure buck startup, no/light/full-load ripple, ringing after load steps,
  and hot-plug overshoot. Check the actual MLCC effective capacitance and
  inductor saturation/temperature rise at peak load.

### 9. P2 — Thermocouple compatibility and cold-junction accuracy need explicit acceptance tests

**Known compatibility constraint; placement-related accuracy remains unmeasured.**
References: U3/U5, J3/J8, `generator/design.py:1058` and `:1127`.

BIAS is connected to the raw negative leg and the two input filters follow
the intended MAX31856 arrangement. This is not a supported grounded-probe
front-end: connecting a junction to an earthed kiln shell can pull it outside
the required common-mode range. The existing requirement for **ungrounded
thermocouples** must carry through procurement and installation, including
verification of sheath-to-junction insulation.
[Analog Devices grounded-thermocouple guidance](https://ez.analog.com/data_converters/a/documents/c/max31856-faq/DO12495/is-it-possible-to-use-maxim-s-thermocouple-to-digital-converter-with-grounded-thermocouple).

The MAX31856s measure their own local temperature for cold-junction
compensation; the screw terminals are spatially separated from them. Test
terminal-to-IC temperature gradients with Wi-Fi active, buck/aux loads on,
enclosure heating, and realistic airflow. Use suitable thermocouple/extension
wire to the terminals and verify polarity. Test open/shorted probes and
maximum common-mode noise in the final wiring arrangement before trusting
high-temperature accuracy.

### 10. P2 — Several provisioned hardware features are not functional in current firmware

**Confirmed by firmware initialization and available drivers.**
References: `main/main.c:124–146`, `components/thermocouple/thermocouple.c`,
`docs/application-roadmap-and-pcb-provisions.md`.

TC1 and SSR1 are the active control path. Firmware explicitly parks SSR2
low and TC2/touch chip selects high. There is no implemented ADE7953 current
measurement driver, second-zone control, or touch driver in the reviewed
application. The additional flow/spare inputs and auxiliary channels also
need their process policies and drivers before they deliver the advertised
future functions. Existing parking of unused SPI selects is correct and avoids
the earlier bus-contention problem.

**Action:** define a manufacturing/acceptance firmware that exercises every
fitted interface, even if the shipping application initially supports one
zone. Do not claim two-zone operation or current-based failed-SSR detection
from hardware presence alone. With J13 DNP there is no measured voltage
channel, so true power/energy needs an additional appropriately isolated,
scaled voltage-sensing system. J13 must not receive mains directly.

### 11. P2 — A failed channel MOSFET can overstress the other channel's gate

**Confirmed fault topology, already present in prior review; not a normal-use fault.**
References: Q5/Q6/Q7, R7/R20/R22, `generator/design.py:1309–1413`.

If Q5 fails drain-to-source short and Q7 turns off, SSR_RTN can rise toward
VIN_P through the external SSR input and indicator path. R22 = 100 kΩ
only weakly references it to ground. The healthy Q6 gate remains near ground
through R20, so its VGS can approach **−24 V** on a part rated **±20 V**.
This can propagate one channel failure into the other and weakens the claimed
independence of the two interruptions.

**Action:** include this state in the fault model and redesign the gate
reference/protection if single-fault containment is required. A simple
gate-source zener alone is not an assured fix: with the existing gate-to-GND
resistor it creates another return path from SSR_RTN to GND, potentially
allowing SSR input current around Q7. Check every proposed clamp path
against the actual SSR's turn-on current. Retain the independent load cutoff.

> **Status 2026-10-28, rev B.4:** closed by the item-3 redesign. The
> channel switches are P-channel with gates referenced to their common
> source rail `SSR_24V` through R7/R20, and the watchdog opens that rail
> (Q9) rather than a shared return, so a failed-short Q5 with the window
> expired leaves nothing to pull the healthy channel's gate anywhere:
> `V_SG` = 0 whatever `SSR_24V` floats to. `SSR_RTN` and R22's old role
> no longer exist. Each gate also carries an 8.2 V gate-source zener
> (D13/D14), which here is the drive clamp, not a fault patch.

### 12. P3 — Connector EMC, RGB logic margin, and design metadata need tightening

References: J5–J7/J14, LED1/D3/R3, `generator/design.py:1696–1729`.

- J6's panel-button signals and the I2C/header connections lack the dedicated
  protection/filtering of J11. Assess ESD and conducted/radiated interference
  with the actual looms. Add low-leakage ESD devices, series impedance, or
  filtering where testing or the intended environment requires it. Header
  peripheral shorts can collapse the primary 3.3 V rail. Specify 3.3 V logic
  and hot-plug restrictions.
- The 40 MHz display SPI bus has multiple device stubs and a cable. The 33 Ω
  display resistors are useful, but measure edges and reliable TC reads while
  the display is busy. Reduce clock rate or adjust termination/layout if
  ringing or contention appears. Passing a netlist check proves connectivity,
  not signal integrity.
- The RGB LED uses a diode drop to accommodate 3.3 V data. The cached legacy
  WS2812B sheet specifies VIH = 0.7 × VDD; that relationship does not guarantee
  margin against the ESP32's minimum VOH, especially at low LED current where
  D3 drops less voltage. The ordered part is WS2812B-B/T, C2761795, and its
  exact applicable revision was not verified here; newer variants differ.
  Lock the actual manufacturer's revision and check its pinout, reset time,
  supply range, and input threshold. An appropriate 5 V AHCT buffer is a
  robust alternative if the selected LED's limits do not close.
- D8 uses the bidirectional `Device:D_TVS` symbol while the assembly part
  is unidirectional. U2's stock TLV1117 symbol links to the non-LV sheet,
  and the schematic's MPN property holds a distributor C-number. These do
  not show a current assembly error, but make substitutions/reviews easier
  to get wrong. Use accurate symbols, datasheet links, and separate supplier
  and manufacturer identities where available.

## Checks completed and limitations

| Check | Result |
|---|---|
| Native KiCad 10.0.6 copper DRC, all severities/all track errors | 0 violations, 0 unconnected items |
| Native KiCad DRC with schematic parity, outside the macOS sandbox | Completed; 0 copper violations, 0 unconnected items, 513 parity issues |
| Full unmodified `make pcb-check`, outside the macOS sandbox | Pass |
| Schematic netlist versus generator table | 108 nets, 0 mismatches |
| GPIO defaults versus hardware | 29 assignments agree |
| Schematic bounds/layout | Pass; no detected symbol/text/wire collisions |
| Schematic UUID round trip and source identity | Pass; 1955 UUIDs retained, 160 sourced refs match |
| Custom copper and drill checks | Pass; 598 drill apertures, minimum measured web 0.300 mm |
| USB pair check | Pass; no vias, 2.52 mm J1-to-U1 skew; not an eye/impedance measurement |
| Assembly pattern fit | Pass; 147 placements, 46 distinct sourced land patterns fitted |
| Fast placement check | 182 footprints checked, 0 problems |
| KiCad-backed placement check | 0 overlaps, 0 outside board |
| Silkscreen check | 0 over-pad, off-board, overlap, or under-part findings |
| Non-exempt via-in-pad check | Pass; independent radius-based pad audit also found 0 overlaps outside the intentional EP grids |
| Fresh Gerber/drill/job export versus committed files | All match after removing creation timestamps |
| Fresh BOM/CPL/hand-solder/Mouser tables | Byte-for-byte match with committed package |
| Gerber ZIP versus exported files | Match |
| Assembly inventory | 147 SMT placements on 49 BOM lines; 13 hand-fitted parts |

Initial sandboxed runs failed in macOS display initialization. A follow-up
run of the full, unmodified `make pcb-check` outside the Codex sandbox returned
exit status 0; the earlier workaround that omitted wx is no longer needed.
A separate via-overlap audit used the explicit F.Cu via diameter and also
found no non-exempt overlaps.

The `--schematic-parity` crash was reproduced inside the sandbox (exit 133,
Swift "Array index out of range"). The macOS crash stack runs through
`BOARD_COMMIT::Push`, `wxGetMousePosition`, and `wxFromNSPoint`, ending in an
empty NSArray lookup. KiCad creates DRC markers and pushes their commit;
this reaches GUI tool notifications even in its CLI. The wxWidgets
[screen lookup](https://raw.githubusercontent.com/wxWidgets/wxWidgets/v3.2.8/src/osx/cocoa/nonownedwnd.mm)
checks for a nil screen array but indexes element 0 without checking for an
empty array. The stack and successful rerun outside the sandbox identify a
macOS display-access/tooling failure, rather than malformed board data.

The identical native parity command outside the sandbox completed with
**0 copper violations, 0 unconnected items, and 513 parity issues**:

- 199 footprint/symbol mismatches: 178 bare versus library-qualified
  footprint names and 21 exclusion-from-BOM attribute mismatches.
- 182 footprint/symbol field mismatches, including 160 missing MPN fields.
- 132 net-name conflicts: 103 local-label path-prefix differences (`NAME`
  versus `/NAME`) and 29 no-connect net naming differences.

These are native parity findings that need generator metadata/name cleanup
or explicit justification. Completing the command is not a clean parity
result. The repository's separate 108-net connectivity comparison passes,
but does not cover all of these native parity checks. Run the macOS command
from a normal logged-in Terminal session, or permit that specific Codex
command outside the sandbox, to avoid the verified crash trigger.

Native schematic ERC produced **4 errors and 230 warnings**:

- U11 VIN and U12 VIN1: power-input pins not driven by a power-output pin.
- U3/U5 SDO: two output-type symbol pins on the intended shared SPI MISO net.
- U12 VOUT and #FLG02: two power-output symbol pins connected together.
- Warnings: 173 library-symbol mismatches, 55 off-grid endpoints, and
  2 same-local/global-label cases.

The four errors appear to be ERC modeling issues, rather than evidence of a
physical short: passive input paths need appropriate power declarations;
MAX31856 SDO is tri-state when deselected; and the redundant output PWR_FLAG
can be removed. Resolve or narrowly document the actual exceptions so ERC
becomes useful for subsequent changes. Do not broadly suppress output/output
or power errors. Library mismatches must be understood before refreshing
symbols, especially symbols intentionally adapted by the generator.

Datasheets were read for the major ICs and switching/protection parts. The
repository manifest checker found only 13 of its 26 declared cached sheets.
Part stock, supplier substitutions, exact LED revision, actual stack-up
acceptance, assembler process capability, and regulatory compliance were not
fully qualified. No hardware was available for this review, so thermal,
analog accuracy, EMC, timing, and signal-integrity performance remain unmeasured.

## Before an order and first-article acceptance

### Before sending the fabrication/assembly order

1. Resolve findings 1 and 2 for the intended electrical ratings, or record
   prototype-only restrictions: clean limited 24 V supply and channel A range
   below its verified input limit with margin.
2. Choose and document filled/capped vias or a qualified alternative for the
   17 EP vias; specify stencil/paste and inspection with the assembler.
3. Confirm four-layer 1.6 mm construction and the actual manufacturer's
   stack-up. The board uses In1 for GND and In2 for 3.3 V; do not let a job-file
   default replace the order-form stack-up confirmation. Confirm the USB
   impedance requirement with that stack-up if controlled impedance is ordered.
4. Review pin 1/polarity in the supplier placement preview for U1, U2, U7,
   U10–U12, J1, optocouplers, LEDs, and C46. Fit checks pass, but a supplier
   substitution requires a fresh fit. Confirm drilled slots and finish against
   the selected fab's process, plus assembly rails/fiducial visibility.
5. Preserve intentional DNPs: J13, test features, and both solder jumpers.
   **SJ2 open** preserves the watchdog. **SJ1 open** is mandatory with an
   external 24 V auxiliary supply. Bridging SJ1 then backfeeds 24 V into +5V.
6. Lock the thermocouple/CT/display/coil/SSR interface specifications and
   recheck actual stock and substitutions. Budget the hand fitting of BZ1,
   J2–J12, and LED1; LED1 has no line in the Mouser order file.
7. Set an enclosure ambient-temperature target and an initial test plan.
   Check component temperature grades, electrolytic life, antenna/pigtail
   requirements, cable clearance, mounting-hole bonding, and market-specific
   EMC/safety/RF requirements before a production release.

### On the first assembled boards

Start with dummy loads and no heater connected. Record the board serial,
component substitutions, supply settings, firmware revision, and measured
values; use `docs/bench-smoke-test.md` as the starting procedure.

| Area | Required evidence |
|---|---|
| Assembly | AOI and suitable hidden-joint inspection; polarity, solder bridges, EP ground continuity, open SJ1/SJ2, DNP J13 |
| Power | Current-limited startup; rail DC/ripple/overshoot; load steps; USB-only and J2-only; both power transition directions; no host/buck backfeed |
| Thermal | Closed-enclosure soak with Wi-Fi traffic, full backlight, SSR inputs, and intended aux loads; U2/U11/L1/D7/F1 temperatures and rail margin |
| SSR/watchdog | Boot/reset/flash/OTA off state; held-high/held-low/missing kick; MCU and safety-task stalls separately; 3.3 V loss; hot leakage and measured turnoff latency |
| Installation cutoff | Independent mechanical/temperature cutoff and contactor operation; verified ability to remove heater power despite a control-output bypass or failed SSR |
| Thermocouples | Ungrounded probe compatibility, CJC gradients, known temperature/reference comparison, open/short faults, noise with switching loads |
| Current sensing | Clock/reset/I2C operation, required ADE initialization, both channel calibrations, overrange/input voltages, CT polarity, open-secondary procedure |
| Digital interfaces | USB in both orientations/cable types; display plus TC traffic; every aux/input/header exercised by acceptance firmware |
| Wiring/EMC | Correct external coil return and COM; dry-contact input behavior including broken wire; ESD/EFT/surge testing to the defined interface envelope |

Do not run destructive input-fault tests until the protection limits and
fixture have been designed. Inspect the first articles and close the above
measurements before increasing the manufacturing quantity or commissioning
the heater system.

## Reproducing the channel A calculation

This standard-library calculation models the nominal circuit with an ideal
CT current source, ignoring clamp conduction at the normal input amplitudes.
It is AC circuit analysis, not a complete SPICE or CT model.

```python
import math

for frequency in (50, 60):
    secondary_peak = 100 / 2000 * math.sqrt(2)
    z_shunt = 1 / (2j * math.pi * frequency * 33e-9 + 1 / 50e6)
    y_filter = 1 / (1000 + z_shunt)
    # Summing the two raw-node equations gives N = -P * ratio.
    ratio = y_filter / (y_filter + 1 / 1000)
    p = secondary_peak / (y_filter + (1 + ratio) / 5.1)
    n = -p * ratio
    iap = p * z_shunt / (1000 + z_shunt)
    ian = n * z_shunt / (1000 + z_shunt)
    print(frequency, abs(iap), abs(ian), abs(iap - ian),
          100 * 0.250 / abs(iap))
```

Review output was generated from temporary exports; committed schematic,
PCB, Gerbers, BOM, and firmware were left unchanged.
