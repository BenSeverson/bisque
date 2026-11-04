# Schematic and circuit review — 2026-11-03

Reviewed revision **B.5**, at commit `6b4de0e4070f3e180db1344565f1be226f287dd6`.
The current KiCad schematic and board, rather than the older reviews or knowledge
graph, were the authority. This review changes no circuit, layout, firmware, or
fabrication output. Existing working-tree edits were left alone.

## Assessment

The connectivity and manufacturing package are consistent, and the architecture
has improved substantially: high-side SSR switching removes the old grounded-return
bypass; the watchdog has a separate series cutoff; the power mux prevents buck
backfeed; chip selects have defined idle states; channel A has a balanced CT
reference; and the earlier thermal-via/paste problems have been addressed.

**I would permit a controlled first-article build, but would not commission a
heater or call this production-qualified yet.** The principal outstanding work is
correcting safety-relevant instructions, making the independent heater disconnect
an explicit installation requirement, qualifying the connector protection, and
establishing measured power, thermal, watchdog, and sensor limits.

There are **18 findings** below. They include confirmed drawing errors, electrical
design risks, existing installation requirements, and future improvements; they
are not 18 demonstrated circuit failures.

- **P1:** resolve before connecting heater power or issuing commissioning instructions.
- **P2:** resolve before production, or document a restricted use envelope supported
  by qualification. An untested calculation is not qualification.
- **P3:** maintainability, sourcing, or expansion improvement.

## Scope and verification

Read all six schematic pages, the 205-component/119-net exported netlist, PCB,
assembly data, enclosure guidance, earlier reviews, design notes, pin map, and
hardware-facing firmware. Checked the relevant manufacturer documentation,
including exact fitted variants where available. Calculations are engineering
estimates unless explicitly identified as manufacturer limits.

| Check | Result |
|---|---|
| KiCad 10.0.7 schematic ERC, all severities | 0 errors, 0 warnings, 0 exclusions reported |
| Native PCB DRC, all severities | 0 violations, 0 unconnected pads, 0 footprint errors |
| `make pcb-check` | Passed, including portable checks, footprint fit/placement, via/paste, silkscreen, sync idempotence, and datasheet manifest |
| Schematic/PCB parity | 205 components, 607 pads, 0 mismatches |
| Firmware/schematic/document pin map | 31 checked assignments agree |
| Fresh fabrication export to a temporary directory | All 11 plotted layers, drill map, and Excellon drill match the committed outputs after removing timestamps |
| Fresh BOM and CPL | Match committed files |
| Fresh schematic PDF | Extracted content matches committed PDF; all six freshly rendered pages inspected |
| Manufacturing ZIP | Matches the committed Gerber directory |

KiCad emitted macOS wx/debug messages during the Python checks, but the full
target completed successfully. ERC/DRC still have intentionally ignored rule
classes; a clean report does not prove electrical ratings, EMC immunity, thermal
performance, or functional safety. No physical board, load test, fault injection,
SPICE model, or EMC test was available for this review.

## Findings

### 1. P1 — The current drawing and commissioning procedure describe the wrong SSR topology

**Confirmed.** The Rev B.5 [root schematic](bisque-controller.kicad_sch) notes
still say J4/J9 pin 1 is always-live `VIN_P`, pin 2 is the switched return,
Q7 interrupts that return, and the channel gates are held down when off.
The actual [kiln circuit](sheets/kiln.kicad_sch) is P-channel high-side switching:
pin 1 is `SSR?_OUT`, pin 2 is GND, Q9 interrupts the supply, and the channel gate
must approach its source to turn off. The root's “≤200 mA per channel” also
conflicts with the ambient-dependent shared budget.

The [bench procedure](../../docs/bench-smoke-test.md) contains related errors:

- Its Q8 check identifies J4.1 as `VIN_P`. That terminal is downstream of Q9
  **and** Q5 and is normally off at idle; probe Q8's source or U11 VIN instead.
- It expects `SSR2_GATE` below 0.3 V while the channel is off. With `SSR_24V`
  live, the off gate should be near that rail. Near 0 V would command the P-FET
  on and exceed its intended gate drive if its zener failed.
- It lists Q9 shorted or SJ2 bridged as explanations for an energized output at
  idle. Q9 is already on during healthy supervision; neither condition alone
  commands a healthy Q5/Q6 on.
- Its external 1 kΩ stimulus through the existing 220 Ω opto LED resistor gives
  only about 1.7 mA, below the 5 mA CTR test point used by the design. A dark
  output is not a reliable watchdog proof unless the same stimulus is first
  demonstrated to turn the channel on with watchdog permission present.

**Action:** correct the root notes and test procedure together. State the expected
voltage at each named node for permission off, permission on/channel off, and
channel on. Prove the watchdog with a known effective forced-on channel stimulus
and dummy load, then remove permission without changing that stimulus.

### 2. P1 — Independent heater disconnection is still optional in part of the installation guidance

**System requirement; not a new PCB short.** The PCB watchdog removes SSR input
drive. It cannot interrupt an SSR whose mains output has failed short. The
[enclosure guide](../enclosure/README.md) calls the contactor “strongly recommended”
and explicitly offers a “no contactor” configuration, while other project guidance
requires independent over-temperature protection.

Make an independent, appropriately rated means of interrupting element power
mandatory: a temperature limiter with its own sensing/failure response operating
a contactor, or a suitably rated direct-acting cutout. Define manual reset,
power-restoration behavior, lid/E-stop wiring where required, and the response to
a welded contactor. A contactor controlled only by the same ESP32 is not an
independent temperature limit. Omron explicitly identifies shorted outputs as an
SSR failure mode and calls for load-side contactor/breaker protection.
[Omron SSR precautions](https://www.ia.omron.com/product/cautions/18/safety_precautions.html).

The installed isolation assessment must include the PSU, SSRs, CTs, thermocouple
construction and wiring, and USB-accessible circuitry. An “ungrounded junction”
label alone does not specify a probe's mains dielectric rating. Board GND is
deliberately bonded to the enclosure; use a dedicated protective-earth system,
not PCB copper as the protective conductor for mains faults.

### 3. P2 — J11's claimed 24 V fault tolerance relies on unspecified ESP32 clamp behavior

**Confirmed design reliance; survival unproven.** R12/R26/R28 are 100 kΩ between
the terminal and GPIO; R13/R27/R29 are 10 kΩ from the terminal to +3V3. D15–D17
have 30 V standoff and intentionally do not conduct at +29 V or −24 V.

At +29 V, nominally 2.57 mA enters +3V3 through each pull-up and about 0.254 mA
enters the GPIO **if** its internal clamp holds 3.6 V. That clamp voltage is an
assumption, not a specified external fault-protection function. Espressif's DC
input range ends at VDD + 0.3 V and does not provide an applicable guaranteed
continuous injection-current allowance in the cited datasheet. Negative faults
likewise rely on the internal lower clamp.
[ESP32-S3 electrical characteristics](https://documentation.espressif.com/esp32_s3_datasheet_en.pdf).

The argument that the board always consumes enough current to absorb backfeed
also excludes power-off, brownout, regulator shutdown, and several simultaneous
miswires. A powered field wire can partially power a nominally off controller.

**Action:** use specified external current limiting/clamping or a fault-rated
input stage, and address rail backfeed when unpowered. Qualify all three inputs
at positive and negative faults with the board powered, off, and transitioning.
Keep the dry-contact-only functional restriction: this is not a general PNP
24 V sensor input. The firmware change disabling its internal pull-up is correct.

### 4. P2 — J6's fitted ESD array does not establish protection for directly connected 3.3 V GPIOs

**Confirmed part-selection concern; an ESD failure has not been measured.** D18
is **TECH PUBLIC C2827672**, not ST's similarly named part. Its manufacturer
sheet gives 6–9 V breakdown and clamps of 11 V at 4.5 A / 14 V at 10 A. Each
button line connects directly to an ESP32 pin with no series resistor or secondary
external clamp. The MCU's internal structures can therefore conduct well before
D18 avalanches. A high ESD survival rating for D18 does not rate the protected MCU.
[Exact TECH PUBLIC datasheet, page 2](https://datasheet.lcsc.com/datasheet/pdf/6fa3bd67d2798839eb826e011504c0a5.pdf?productCode=C2827672).

**Action:** coordinate the clamp with the GPIO, normally with series impedance
and suitable secondary/rail steering protection, and verify the assembled panel
and loom. The routing difficulty recorded in the design notes explains the
omission but does not establish immunity. Treat exposed switches and their
wiring as part of the test article.

### 5. P2 — U13 improves accessory protection but does not yet prove controller fault containment

The AP2331's normal rated output is **200 mA total**, not its 300–500 mA short
limit. A short can add approximately 0.85 W to U2 at 5 V input before considering
the MCU's own demand. U13's thermal shutdown protects U13; it does not guarantee
that U2 or +3V3 stays in regulation throughout the event.
[AP2331 ratings and application circuit](https://www.diodes.com/datasheet/download/AP2331.pdf).

There is no local input bypass at U13: C55 is on its output, and the nearest
existing +3V3 capacitor by footprint-center distance is C35, about 38 mm away.
The application circuit shows an input capacitor as well as an output capacitor.
Add local input bypass and check the transient current loop.

D22 and the I²C pull-ups remain on the main rail, so an externally powered
peripheral can also backfeed through **signal pins**, bypassing U13's reverse
blocking. A shorted SDA/SCL disables the onboard ADE7953 bus regardless of the
header's power limiter.

**Action:** qualify hot-plug and sustained shorts with maximum Wi-Fi/display
activity and hot enclosure ambient. Measure at U1 and U10 as well as U2. Define
signal backfeed limits and use branch isolation/power control if accessory faults
must not disrupt onboard metering. Do not yet promise “a shorted peripheral no
longer drags the ESP32 rail down” as a verified property.

### 6. P2 — USB hot-plug and ESD voltage protection remain unqualified

U12 has a 6 V absolute maximum. U4's rail clamp is not a precision sub-6 V
limiter. C50 improves charge absorption, but the design notes themselves estimate
about 6.9 V hot-plug overshoot for one plausible cable/source model. The simple
8 kV `Q/C` calculation also omits capacitor/trace inductance and the initial
fast ESD peak. It cannot establish the schematic note's claimed protection level.
[TPS2116 ratings](https://www.ti.com/lit/ds/symlink/tps2116.pdf),
[ADI AN88, ceramic-capacitor hot-plug transients](https://www.analog.com/media/en/technical-documentation/application-notes/an88f.pdf).

**Action:** measure at U12 VIN2 using appropriate high-bandwidth probing, with
short/long cables, both power-source states and repeated plug/unplug. If the
limit is exceeded, add a coordinated damping/OVP solution or select a more
tolerant front end. An OVP device's response time and transient let-through must
also be checked. Test the finished assembly for ESD; retain the separate
restriction against defective high-voltage USB sources.

### 7. P2 — USB-only operation has no defined current/compliance policy

R4/R5 correctly implement Type-C sink terminations, but there is no CC current
advertisement detector or controllable load budget. The documented whole-board
5 V budget reaches 0.8–1.0 A, including possible expansion/auxiliary loads.
That is not a promise an arbitrary USB data port makes. Native USB console
enumeration alone is not evidence of permission to draw that current.

**Action:** define USB-only operation, measure startup/normal/suspend current,
check descriptor and VBUS-presence behavior, and shed backlight/peripheral loads
as needed. Either enforce the supported port budget or explicitly require an
appropriate bench supply while giving legacy data ports a lower-power mode.
Also exercise buck-to-USB handover at maximum permitted load; the mux's deliberate
voltage dip must leave adequate LDO headroom.
[USB-IF compliance updates](https://compliance.usb.org/index.asp?UpdateFile=Electrical),
[USB-IF Type-C specification, current advertisement](https://www.usb.org/sites/default/files/USB%20Type-C%20Spec%20R2.0%20-%20August%202019.pdf).

### 8. P2 — The input TVS/PPTC argument still does not guarantee safe fault clearing

Restricting J2 to an in-box current-limited supply substantially reduces the
threat. It does not make F1 an instantaneous current limiter. Its 1.5 A trip
rating is not a ceiling on current before tripping. Nor is D8's assumed destruction
into a permanent short a guaranteed protection function. TVSs can fail short,
open, or degraded, including opening after an initial short.
[Vishay, TVS failure modes and fusing](https://www.vishay.com/docs/88440/failurem.pdf).

Correct a pervasive rating error: the fitted XL1509 sheet specifies **40 V
operating maximum and 45 V absolute maximum**, not 40 V absolute maximum.
D8's 48.4 V specified high-current clamp is above both. The linear interpolation
from breakdown to clamp is an estimate, not a guaranteed full I–V/temperature
envelope. The SSR inputs also see the protected 24 V rail; a common 32 V operating
input cannot simply be assumed to survive the project's estimated 38 V fault.
[Exact XL1509 datasheet, page 5](https://datasheet.lcsc.com/datasheet/pdf/6764d4cba2504b189b593202c77b9bd6.pdf?productCode=C61063).

**Action:** keep the limited-supply/in-box restriction explicit and qualify its
actual fault behavior. For broader supplies, use appropriately rated input parts
and a controlled disconnect/crowbar/fuse scheme. Do not close this finding by
assuming a sacrificial TVS fails safely. The changes to 60 V catch diode D7 and
high-voltage flyback diodes D9/D10 are sensible improvements.

### 9. P2 — The watchdog's 1.3–3.1 s interval is an estimate, not a guaranteed timing specification

The one-shot topology, defined idle input, and Q3/Q7 pull-downs are good. However,
TI's bounded output-duration tests use much smaller RC combinations; the design
scales the 10 kΩ/0.1 µF test by **2000×** to 1 MΩ/2 µF. Timing curves and a
separate leakage allowance do not extend that production guarantee to this RC.
Capacitor bias/aging allowances also need an identified lifetime and evidence.
[SN74LVC1G123, switching characteristics and application curves](https://www.ti.com/lit/ds/symlink/sn74lvc1g123.pdf).

There are two different delays: last accepted kick to hardware cutoff, and
supervision failure to cutoff. A stalled safety task can still receive kicks
while its previous heartbeat remains fresh for up to 900 ms. Thus even if
3.1 s were established for the one-shot, “firmware failure to off” is not always
3.1 s; budget roughly another heartbeat interval plus scheduling/phase effects.

**Action:** label the interval an engineering estimate, characterize supply,
temperature, component tolerances and multiple units, and test task-only stalls
separately from total MCU halt. Obtain a manufacturer-supported timing bound or
use an appropriately specified timing/watchdog device if a guaranteed maximum
is required. At hot soak, also measure Q9 gate/source and outputs with permission
removed; R22's 100 kΩ makes off-state leakage worth checking. Keep SJ2 open.

### 10. P2 — The total supply/thermal budget is incomplete after adding expansion power

The board documents a useful 1 A/50 °C ceiling for the 5 V converter and a shared
280 mA/50 °C SSR-terminal allowance. Those are not independent reserves. The
header's 200 mA, 5 V auxiliary loads through SJ1, backlight, Wi-Fi peaks, buzzer,
and SSR/coil loads must fit one installed-system budget.

Aux coils supplied directly from the HDR-15-24 bypass F1 but still consume the
same PSU capacity. At 50 °C, the documented worst-case buck demand of 0.29 A plus
two SSR inputs/indicators at about 0.04 A leaves about **0.30 A** of a 0.63 A PSU
for external aux loads before margin. At the documented 60 °C derating, that
falls to about **0.14 A**. The enclosure's blanket “roughly 20” relay statement
does not cover 20 coils at the stated 20 mA upper value alongside the board.
The F1 hot-current allowance also uses an inferred family derating row rather
than an explicit guarantee for the exact `JK-mSMD075-33`; confirm that assumption.

**Action:** publish continuous and peak budgets per configuration and ambient,
including the shared 5 V and 3V3 limits. Measure startup, maximum load and
closed-enclosure soak. The buck's modified capacitor bank and ESR-dependent
stability still require the existing load-step qualification; similarity to an
LM2596 is not a substitute for XL1509 loop evidence. Treat 60 °C figures as
derating calculations, not an extension of the current 50 °C board rating.

### 11. P2 — J10 needs a board-level load rating and explicit failure policy

U6's 500 mA figure is a **single-output component rating**, not a three-channel
simultaneous board rating. The ULN2003A's input-voltage table requires up to
3 V for 300 mA at its stated test condition, while the ESP32's general guaranteed
VOH is 0.8×VDD. Guaranteed operation at the component headline current therefore
has not been established. Darlington voltage loss also matters for 5 V relay pickup.
[TI ULN2003A ratings and thermal data](https://www.ti.com/lit/ds/symlink/uln2003a.pdf).

As an illustrative thermal stress calculation, three 300 mA channels with 1.6 V
drop dissipate 1.44 W; TI's 88.6 °C/W SOIC reference figure implies about 128 °C
rise. This is not a prediction of this PCB, but rules out casually declaring
three heavy continuous loads at hot ambient.

**Action:** specify voltage, current, total dissipation, duty, inductance and
switching-rate limits; validate pickup/dropout and repetitive flyback with the
actual loads. Fuse the external supply/wiring appropriately, bond its negative
to board GND, connect COM to the coil positive supply, and leave SJ1 open with
external power. Aux outputs are outside the hardware watchdog: purge or gas-valve
use requires a separately designed safe state, not simply a future firmware role.

### 12. P2 — Thermocouple compatibility and cold-junction accuracy require installed qualification

The MAX31856 BIAS connection and 100 Ω / 100 nF differential / 10 nF common-mode
filters follow the recommended arrangement. Ungrounded probes are the appropriate
restriction for this shared-ground design. The IC's ±45 V input protection is
not mains isolation.
[MAX31856 application guidance](https://www.analog.com/media/en/technical-documentation/data-sheets/max31856.pdf),
[ADI grounded-tip guidance](https://ez.analog.com/data_converters/a/documents/c/max31856-faq/DO12495/is-it-possible-to-use-maxim-s-thermocouple-to-digital-converter-with-grounded-thermocouple).

The relevant thermal quantity is the terminal junction temperature versus the
IC's cold-junction sensor. The MAX31856/terminal footprint centers are about
17.3 mm apart on both channels, so enclosure heat flow, wire heating and terminal
gradients cannot be dismissed as “a few mm.” This distance alone does not prove
an accuracy error.

**Action:** compare against a reference through the intended temperature range,
then repeat at enclosure soak with radio, display and coils active. Control
extension-wire alloy, terminal transitions, polarity, probe construction and
probe maximum rating. Exercise open, reversed and shorted probes: a short that
reports plausible ambient temperature is not necessarily detected as a converter
fault. Channel 2 currently provides no independent firmware temperature protection.

### 13. P2 — CT selection, service safety, and metering accuracy need a complete interface specification

The added R65 balances channel A; the old unbalanced-A clipping finding is
resolved in the current circuit. For an ideal 2000:1 CT and 5.1 Ω burden,
100 A RMS produces approximately 0.361 V peak differential and nominal ADC full
scale is 138.6 A RMS at gain 1. That is an ADC calculation, not a rating of a
100 A CT, connector, or installed system. R65/R33 load the burden slightly;
calibrate each channel rather than copying an ideal constant.

Channel B remains single-ended, which the electrical table permits, but its
common-mode voltage exceeds the datasheet's preferred ±25 mV at substantial
currents. Qualify accuracy/noise over the intended range rather than treating
the two channels as identical analog circuits.
[ADE7953 analog-input specifications](https://www.analog.com/media/en/technical-documentation/data-sheets/ade7953.pdf).

**Action:** specify an exact current-output CT, ratio, bandwidth, insulation and
open-secondary protection. Do not substitute a voltage-output CT with an internal
burden. R31/R34 and D6 are on the PCB and cannot protect a disconnected secondary
out at the CT; provide suitable protected sensors/shorting arrangements and a
de-energized service procedure. Open CT secondaries can generate dangerous voltage.
[Schneider Electric CT service guidance](https://www.se.com/us/en/faqs/FA125574/).

Keep power/cost estimates labeled as current × configured voltage. Without a
voltage channel the circuit cannot measure true real power, power factor, or
actual line-voltage variation. Presently neither current channel has firmware
support, so there is no working stuck-SSR or failed-element current diagnostic.

### 14. P2 — The display remains a shared-bus qualification and failure-containment concern

The added source resistors and connector resistors are good provisions. Four
SPI devices, branch stubs, protection capacitance, layer transitions and a panel
loom still need measurement at 40 MHz. Nominal propagation delay alone does not
establish edge quality. Verify both thermocouple read integrity and panel behavior
with the actual maximum loom and switching environment.

R56 provides a useful way to disconnect panel SDO if a module fails to release
MISO; 33 Ω does not isolate two actively conflicting outputs. A display/loom
short can affect both thermocouple interfaces, so the two converters are not
independent safety channels. Any bus fault must lead to stale/fault rejection and
heat removal. Retain reset/download checks because LCD reset/backlight use strap
pins; qualify replacement display modules against the actual module circuit.
[LCDWIKI MSP4021 schematic](https://www.lcdwiki.com/res/MSP4021/4.0inch_SPI_Schematic.pdf).

### 15. P2 — Several populated functions are still hardware provisions, not usable product features

**Confirmed in current firmware.** The thermocouple driver has one device/cache,
SSR2 is explicitly parked low, and there are no functional ADE7953/I²C, touch,
gas-flow, spare-input, aux-2/3, or power-status consumers. Their Kconfig defaults
describe routing; they do not implement a feature. The ADE reset pin is a useful
recovery provision once a driver exists.

**Action:** release a hardware/firmware capability table and require bring-up
tests for the dormant circuits. Do not commission a two-zone kiln, gas-flow
interlock, touch-only door, or current-based heater-fault detector on the present
firmware. PWR_STATUS should eventually distinguish USB bench operation from
availability of the heater-control supply; define the process response to loss
and return of that supply. Keep future gas functions outside the ceramics
configuration until their independent safety design exists.

### 16. P3 — Exact variants and datasheet identity need tighter control

The current sourcing fields, package-fit checks and corrected assembly rotations
are strengths. However, a nonempty datasheet cache is not proof it describes the
fitted part: the cached generic WS2812B sheet uses different limits from fitted
**WS2812B-V5/W C2874885**. That exact sheet specifies 0.63×VDD input-high threshold
and an operating temperature ceiling of 65 °C. The project's 0.7×VDD arithmetic
and mixed “4.15 V”/“4.6 V” diode-drop descriptions are stale. D3's drop is also
load-dependent. This is a qualification/documentation issue, not proof that the
status LED will fail.
[Exact Worldsemi datasheet, pages 2–3](https://datasheet.lcsc.com/datasheet/pdf/3795cfb9d54f7ec8ecc0b043ede3c05a.pdf?productCode=C2874885).

Lock the N16R2 module, optocoupler CTR rank, protection-device manufacturer,
MOSFET ratings, and capacitor dielectric/voltage/ESR as substitution constraints.
U8/U9's description still says CTR 50–100% despite the GB-ranked sourcing;
correct it. If a guaranteed LED logic interface is required, use a specified
level interface rather than relying solely on typical GPIO swing and diode drop.
Record datasheet revision/hash and actual manufacturer for approved alternatives.
Recheck stock and the supplier placement preview when ordering; availability
and pricing were not independently requalified by this review.

### 17. P3 — Expansion has concrete GPIO, bus, and recovery limits

All usable GPIOs are allocated; the roadmap's “29 assigned and one spare” is
stale. Reusing IN3 or polling touch can free a function only with an explicit
pin/circuit change; general expansion needs an I²C expander or another interface.
An expander on the shared bus does not create an independent safety input.

The 4.7 kΩ I²C pull-ups imply approximately **75 pF** maximum total bus
capacitance for a 300 ns rise-time target using `tr ≈ 0.8473 Rp Cb`. An added
Qwiic cable and breakout can consume that margin. Establish clock rate, cable
length, cumulative pull-up loading and address rules, including U7's fixed 0x38.
100 kHz is a reasonable initial qualification target. Include stuck-bus recovery,
timeouts and separately switchable peripheral power if field accessories are planned.
[NXP I²C specification](https://www.nxp.com/docs/en/user-guide/UM10204.pdf?fsrch=1&pageNum=1&sr=1).

For a later revision, useful provisions are accessible ADE IRQ/current-zero-cross
test pads, an independent interlock/contactor-feedback connector, and a separately
controlled expansion branch. Decide these before trying to reclaim routing space
for optional features.

### 18. P3 — Drawing hygiene and release checks still allow explanatory text to drift

The hierarchy, real sheet pins, local labels, power symbols, sourcing fields,
defined unused inputs and clean ERC are substantial improvements over October's
drawing review. Remaining examples: root notes refer to removed J13; the README
still calls the powered oscillator a crystal and lists its former package; test
point prose mentions I²C pads that are no longer present; and several pages place
support circuitry far from the functional block with extensive explanatory prose.

**Action:** reduce each drawing note to the present interface/rating/required
restriction; move historical reasoning to a clearly historical design record.
Put critical limits beside the relevant connector. Distinguish manufacturer
absolute limits, recommended operation, board ratings and unmeasured estimates.
Use consistent tolerance/voltage/power metadata for passives and a meaningful
release date alongside revision B.5.

ERC is deliberately outside CI, and the ZIP check establishes ZIP-versus-Gerber
freshness, not Gerber-versus-PCB freshness. This review independently confirmed
all current outputs match. Add a release gate or source-hash manifest covering
schematic, PCB, BOM, CPL, plots and drawings, plus an actual native ERC/DRC run,
to preserve that state on future releases.

## Standards and installed-system review

Choose the product classification and intended markets before declaring compliance.
The following are relevant starting points, not a claim that every standard applies:

| Area | Review basis and consequence |
|---|---|
| Electroheating equipment | [IEC 60519-1:2020](https://webstore.iec.ch/en/publication/61886) covers general electroheating safety. Review the complete kiln installation and fault response. |
| Temperature controls/limits | [IEC 60730-2-9:2026](https://webstore.iec.ch/en/publication/94635) covers temperature-sensing controls. Decide whether this is a process controller, protective control, or a component used under an independent limiter. |
| US industrial control panel | [UL 508A scope](https://www.shopulstandards.com/ProductDetail.aspx?productId=UL508A) is relevant if marketed/constructed as an industrial control panel. Panel certification does not certify the connected kiln: [UL's explanation](https://www.ul.com/resources/does-ul-certified-industrial-control-panel-certification-cover-equipment-it-controls). |
| EMC | Select the applicable product standard; [IEC 61000-6-2](https://webstore.iec.ch/en/publication/25630) is a generic industrial-immunity starting point where applicable. Define ESD, EFT, conducted/radiated RF and supply-transient tests by actual port exposure, plus emissions testing. |
| Radio | Use the actual module grant/certificates and permitted antenna configuration, host labeling and integration conditions. A certified module does not alone qualify the whole product: [Espressif certificates](https://www.espressif.com/en/support/documents/certificates?field_product_value%5B%5D=ESP32-S3&keys=). |

The installed review must also settle supply and branch protection, disconnecting
means, load conductors and terminal ratings, protective-earth continuity, segregation
and strain relief, enclosure material/ingress rating after cutouts and vents,
SSR fuse coordination and heatsink derating, accessibility of live terminals,
component temperatures/lifetime, and behavior after power restoration. A 50 mm
wiring-separation suggestion or an SSR nameplate current is not by itself proof
of insulation or thermal compliance. Exact legal/code applicability was not
determined from this low-voltage PCB review.

## Required first-article evidence

Use dummy loads until the independent disconnect and corrected procedure are ready.
Record board serial, assembly substitutions, firmware revision, ambient, fixture,
waveforms and acceptance results. The existing smoke test is a useful starting
point **after finding 1 is corrected**, not completed evidence.

| Test group | Evidence to collect |
|---|---|
| Assembly | AOI/hidden-joint inspection as appropriate; EP/GND continuity; actual polarity and pin-1 orientation; open SJ1/SJ2; connector mating and retention |
| Supply and regulation | Low/high intended J2 input, idle/full load and load steps; buck stability/ripple/startup; USB-only/both-source transitions; no backfeed; U1/U10 rail minima |
| Fault protection | Controlled J11 positive/negative and power-off faults; header sustained short/hot-plug; signal backfeed; defined input fault clearing; capture recovery and residual heating |
| Watchdog/output | Both outputs through boot/reset/flashing/OTA, stopped/stuck-high/stuck-low kick, total MCU halt, task-only stall, 3V3 loss and recovery; forced-on positive control; hot leakage; measured terminal turnoff |
| Thermal | Closed enclosure at rated ambient with worst allowed radio/backlight/header/coil loads; U2/U11/D7/L1/F1/U6/U13 and SSR-base temperatures; capacitor and supply lifetime margin |
| Temperature | Each probe/channel against reference; thermal gradients and interference; open/short/reverse faults; stale SPI readings; source power loss |
| Metering | Driver initialization/reset/clock, independent A/B calibration over intended current and temperature, overrange, noise/crosstalk, sensor/service specification |
| Panel/expansion | Maximum loom, simultaneous display/TC traffic, MISO release, reset/download with panel, touch if implemented, I²C rise time/addresses/stuck-bus recovery |
| System protection | Independent limiter/lid/E-stop as specified actually removes element power despite an SSR-output bypass; controlled reset/restart; PE and insulation tests with sensitive circuits appropriately disconnected |
| EMC | Finished enclosure and actual cables under defined immunity/emissions tests; no unintended heat command; deterministic fault latch/recovery policy |

Do not infer a guaranteed fault envelope from a single surviving prototype. Close
each release-critical item with a circuit change, manufacturer-supported limit,
or repeatable qualification under a documented installation restriction.

## Review identity

Schematic root SHA-256:
`535e32bdf7ffced2b4b7f35911b2f4dde80825ec048d8b9c01829bbb6e707682`.

PCB SHA-256:
`a6b2de37ecca3f6ffb7fcb54d766ef9a851e52e876ea077c403ea32f1306db10`.

Previous reviews remain useful history, but their “closed” entries and historical
component values were not treated as proof for this revision.
