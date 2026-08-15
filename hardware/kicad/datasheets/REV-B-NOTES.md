# Rev B pre-layout datasheet notes

Answers to the risks in spec §7.1 of
`docs/superpowers/specs/2026-08-10-pcb-rev-b-hardware-design.md`, taken from the
manufacturers' datasheets. **Tasks 8, 10 and 12 read this file.**

Compiled 2026-08-11. Every answer carries its source. Where a fact could not be
obtained from a primary source it is marked **COULD NOT VERIFY** rather than
guessed — see §10 for the full list of those.

## Sources and how they were obtained

| Part | Document | How it was read |
|---|---|---|
| ADE7953ACPZ-RL | ADE7953 data sheet, **Rev. C** (12/2016), 72 pp. | `analog.com` is unreachable from this build environment (HTTP/2 reset, then timeout, on every URL tried, including the `static/imported-files` path). Read instead via the page-by-page text mirror at `https://www.radiolocman.com/datasheet/pdf.html?di=150331&p=<N>` (`p` is 0-based; `p=22` renders page 23). Page numbers below are the **datasheet's own** page numbers and were confirmed against each page's `Rev. C \| Page N of 72` footer, so they can be checked against the canonical PDF at `https://www.analog.com/media/en/technical-documentation/data-sheets/ADE7953.pdf`. |
| ULN2003ADR | TI ULN2003A data sheet | Downloaded to `ULN2003A.pdf` in this directory from `https://www.ti.com/lit/ds/symlink/uln2003a.pdf`. |
| AO3400A | Alpha & Omega AO3400A data sheet | Already in this directory: `AO3400A_30V_Vds_5.7A_Id_N-Channel_MOSFET_SOT-23.pdf`. |
| ESP32-S3-WROOM-1/1U | Espressif module data sheet | See §9. |

PDFs **obtained and placed in this directory**: `MAX31856.pdf` (Maxim 19-7534
Rev 0, from the rlocman mirror), `LTV-817_LiteOn_Photocoupler_M_S_S-TA_S-TA1_S-TP_RevC.pdf`
(Lite-On DS70-2012-0050 Rev C), `BAT54S_Nexperia.pdf`, `ULN2003A.pdf` (TI
SLRS027T), `ESP32-S3_Series_Datasheet_v2.2.pdf`, plus the pre-existing AO3400A
and ESP32-S3-WROOM-1/1U sheets.

> **Only the ADE7953 PDF could not be mirrored** — every `analog.com` URL tried
> either reset the HTTP/2 stream or timed out, and the usual re-hosts return
> bot-check HTML. §1–§4 cite Rev. C page numbers that are verifiable against the
> canonical document by anyone on an unblocked network.
>
> Note the PDFs in this directory are **git-ignored by design** (the directory is
> a regenerable cache); `.gitignore` was adjusted so that *this notes file alone*
> is tracked. Do not assume the PDFs are present after a fresh clone.

---

## Summary — what each downstream task needs

| # | Question | Verdict |
|---|---|---|
| 1 | ADE7953 `IRMS` without the voltage channel | **CONFIRMED — proceed.** Computed entirely in the current path; ADI documents an explicit "no voltage available" mode. |
| 2 | ADE7953 footprint | **`Package_DFN_QFN:QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm`.** EP is 3.14 mm nom (3.04–3.24); the 3.25 mm candidate exceeds the max. Not the `_ThermalVias` variant. |
| 3 | I²C strapping and address | `CS`=1, `SCLK`=1; `PULL_HIGH`→VDD and `PULL_LOW`→AGND direct, no resistors. Fixed 7-bit address **0x38**, no address pins. |
| 4 | Support components | `VDD` 10 µF ∥ 100 nF; `VINTA`/`VINTD`/`REF` 4.7 µF ∥ 100 nF each; `~RESET` 10 kΩ + 1 µF; crystal caps **unresolved** (see §10). |
| 5 | MAX31856 | **No BIAS bypass cap exists.** AVDD/DVDD share 3V3, 0.1 µF each to AGND/DGND respectively. Filter: 100 Ω series, 100 nF differential, 2 × 10 nF common-mode. |
| 6 | ULN2003 boot state | **10 kΩ is sufficient** — ~1000× margin, because GPIO 14/15/16 have no pull-up at reset. Guard rail in §6 if the map ever moves. |
| 7 | LTV-817S footprint | ⚠️ **All four candidates are wrong** (~6 mm span vs ~10 mm required). Build to LCSC geometry. CTR bin C = 200–400 % @ 5 mA; **do not drive below 5 mA**. |
| 8 | Charge-pump Schottky | **BAT54S, LCSC `C7420333`, Extended/Preferred** (no Basic dual Schottky exists). Gate 2.82 V vs 1.45 V max threshold → **+1.37 V, adequate**. |
| 9 | U.FL clearance | Receptacle 1.25 mm tall and **does not stand proud** of the 3.2 mm module. Reclaimed band **18 × 6.30 mm**. Exit azimuth **unspecified**. |

Two findings contradict assumptions the plan was carrying: **§7** (the opto
footprint shortlist) and **§9a** (the U.FL does not stand proud). Both are called
out in place.

---

## 1. ADE7953 `IRMS` with the voltage channel unused — **CONFIRMED, PROCEED**

**Verdict: the current-channel RMS registers are computed entirely within the
current signal path and do not depend on the voltage channel.** Spec §2.2's
current-only premise stands. No redesign needed.

Four independent pieces of datasheet evidence:

1. **The signal path contains no voltage term.** "As shown in Figure 42, the
   current channel ADC output samples are used to continually compute the rms.
   The rms is achieved by low-pass filtering the square of the output signal and
   then taking a square root of the result." Figure 42's chain is
   `CURRENT SIGNAL FROM HPF OR INTEGRATOR (IF ENABLED) → x² → LPF → √ → IRMSx[23:0]`,
   with only `IRMSOS` (a current-channel offset register) summed in.
   — *Rev. C, p. 23, "CURRENT CHANNEL RMS CALCULATION", Figure 42.*

2. **The three RMS measurements are explicitly parallel and simultaneous.** "The
   ADE7953 provide rms measurements for Current Channel A, Current Channel B,
   and the voltage channel simultaneously. These measurements have a settling
   time of approximately 200 ms and are updated at a rate of 6.99 kHz." The
   24-bit unsigned results are `IRMSA` (0x21A / 0x31A) and `IRMSB` (0x21B /
   0x31B); full scale reads 9032007d.
   — *Rev. C, p. 23.*

3. **The block diagram puts IRMS inside the current channel.** The Current
   Channel ADC block shows `CURRENT RMS (IRMS) CALCULATION`, `ZX_I DETECTION`
   and `CURRENT PEAK, OVERCURRENT DETECTION` all fed from the current PGA/ADC
   chain.
   — *Rev. C, p. 20, "CURRENT CHANNEL ADCS", Figure 39.*

4. **The datasheet documents a mode expressly for having no voltage at all.**
   "**In a tampering situation where no voltage is available to the energy
   meter**, the ADE7953 can accumulate the ampere-hour measurement instead of the
   apparent power in the APENERGYA and APENERGYB registers. If enabled, the
   Current Channel A and Current Channel B IRMS measurements are continually
   accumulated instead of the apparent power."
   — *Rev. C, p. 32, "AMPERE-HOUR ACCUMULATION".*
   This is ADI describing, in their own words, a supported operating mode in
   which IRMS is the only live measurement. It is the strongest single answer to
   the question.

### The one caveat, and why it does not bite

The datasheet recommends synchronising the read, not the measurement:

> "Because the LPF used in the rms signal path is not ideal, it is recommended
> that the IRMSx registers be read synchronously to the zero-crossing signal
> (see the Zero-Crossing Detection section). This helps to stabilize
> reading-to-reading variation by removing the effect of any 2ω ripple present
> on the rms measurement." — *Rev. C, p. 23.*

This is a read-timing recommendation for reducing jitter, **not** a validity
condition — and it is satisfiable without the voltage channel, because
zero-crossing detection is not voltage-only:

> "The ADE7953 includes a zero-crossing (ZX) detection feature **on all three
> input channels**." — *Rev. C, p. 43, "ZERO-CROSSING DETECTION".*

- **Pin 21 `ZX_I`** is the *current* channel zero-crossing output. It is driven
  from Current Channel A by default and can be switched to Channel B via the
  `ZX_I` bit (Bit 11) of `CONFIG` (0x102). — *Rev. C, p. 43, "Current Channel
  Zero Crossing".*
- The matching interrupts are `ZXIA` (Bit 12 of `IRQSTATA`/`IRQENA`, 0x22D /
  0x22C) and `ZXIB` (Bit 12 of `IRQSTATB`/`IRQENB`, 0x230 / 0x22F).
  — *Rev. C, pp. 43–44.*

So firmware can take the recommended synchronous read off `ZX_I` (pin 21) or the
`ZXIA` interrupt. At 1 Hz polling the residual 2ω ripple is in any case well
inside the ±3–5 % accuracy spec §2.2 already accepts.

**Design consequence for Task 10:** route `ZX_I` (pin 21) to a GPIO or at least
to a test point. It is the current-only substitute for `ZX`, and it is what makes
the datasheet's own read-synchronisation advice available on this board.

### Registers valid / invalid with `VP`, `VN` unconnected

**Valid (current path only):**

| Measurement | Register / pin | Cite |
|---|---|---|
| Current RMS A / B | `IRMSA` 0x21A, `IRMSB` 0x21B | p. 23 |
| Current waveform samples | `IA`, `IB` | p. 20 |
| Current peak A / B | `IAPEAK` 0x228, `IBPEAK` 0x22A (+ read-with-reset `RSTIAPEAK` 0x229, `RSTIBPEAK` 0x22B) | p. 46 |
| Overcurrent detection | `OILVL`; `OIA` Bit 13 of `IRQSTATA`, `OIB` Bit 13 of `IRQSTATB` | p. 48 |
| Current zero crossing | pin 21 `ZX_I`; `ZXIA`/`ZXIB` interrupts | p. 43 |
| Current signal dropout | `ZXTO_IA` (Bit 11 `IRQENA`), `ZXTO_IB` (Bit 11 `IRQENB`), period from `ZXTOUT` 0x100 | p. 44 |
| Ampere-hour accumulation | `APENERGYA` / `APENERGYB` in ampere-hour mode | p. 32 |
| Current gain / offset calibration | `AIGAIN`, `BIGAIN`, `IRMSOS` | pp. 23, 35 |

`ZXTO_IA` / `ZXTO_IB` are worth noting to Task 10 beyond this gate: a
current-channel zero-crossing timeout is a *direct* "this element bank has
stopped drawing current" signal, which is exactly the element-health diagnosis
spec §3.6 asks for, and it comes as an interrupt rather than a polled compare.

**Invalid or meaningless (needs the voltage channel):**

- `VRMS` (0x21C) — voltage RMS. *p. 23.*
- `AWATT` (0x212), `BWATT` (0x213) — active power is the product of the voltage
  and current waveforms. *p. 24.*
- Reactive power / `RENERGY*`, apparent power `AVA`/`BVA`, and all active and
  reactive energy accumulation. *pp. 24–31.*
- Power factor, and angle measurement. *TOC, pp. 38–39.*
- **All line-cycle accumulation modes** — "the energy accumulation of the
  ADE7953 is synchronized to the voltage channel zero crossing". *p. 32.* This
  includes ampere-hour accumulation *if run in line-cycle mode*; ampere-hour in
  continuous mode is fine.
- Period / line-frequency measurement. *TOC, p. 36.*
- Pin 1 `ZX`, and the `ZXV` interrupt. *p. 43.*
- Voltage sag detection (`SAGCYC`, `SAGLVL`), `VPEAK` (0x226), overvoltage
  `OVLVL`. *pp. 45–47.*
- Pin 20 `REVP` (reverse power) — needs both channels. *p. 47.*

**Firmware note for Task 10:** with `VP`/`VN` idle the voltage channel will sit
below the internal zero-crossing threshold (fixed at 1250:1 of full scale, *p.
44*), so no `ZX` pulses are produced and the **voltage zero-crossing timeout will
assert continuously**. Mask `ZXV` (Bit 15) and `ZXTO` (Bit 14) in `IRQENA` or the
`IRQ` pin will be stuck low. Both are disabled by default (*p. 44*), so this is a
"do not enable them" note rather than a fix.

### Handling of the unused voltage inputs

The datasheet gives **no explicit instruction for leaving `VP`/`VN`
unconnected** — COULD NOT VERIFY from ADI. Engineering recommendation (flagged
as such, not datasheet text): terminate both `VP` (12) and `VN` (11) to `AGND`
through the DNP divider's lower leg, or fit a DNP-bypassable resistor to `AGND`
on each, so the high-impedance PGA inputs are not left floating on a board that
also carries SSR switching. This keeps the DNP SELV upgrade path of spec §2.2
intact.

Also confirmed for a CT front-end: "When using either a shunt resistor or a
current transformer (CT), this integrator is not required and should remain
disabled" — the digital integrator is off by default and must stay off.
— *Rev. C, p. 21, "di/dt Current Sensor and Digital Integrator".*

---

## 2. ADE7953 exposed-pad size and KiCad footprint — use `QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm`

**Package drawing (Rev. C, p. 69, Figure 79, "28-Lead Lead Frame Chip Scale
Package [LFCSP_WQ] 5 mm × 5 mm Body and 0.75 mm Package Height (CP-28-10)",
JEDEC MO-220-WHHD-1):**

| Dimension | min | nom | max |
|---|---|---|---|
| Body, square | 4.90 | 5.00 | 5.10 |
| Lead pitch | — | 0.50 BSC | — |
| **Exposed pad, square** | **3.04** | **3.14** | **3.24** |
| Lead length | 0.48 | 0.53 | 0.58 |
| Lead width | 0.20 | 0.25 | 0.30 |
| Package height | 0.70 | 0.75 | 0.80 |

**Measured from the installed KiCad 10 library**
(`/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Package_DFN_QFN.pretty`):

| Footprint | EP pad | Lead pad |
|---|---|---|
| `QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` | 3.10 × 3.10 mm | 0.95 × 0.25 mm, pad 1 at x = −2.375 |
| `VQFN-28-1EP_5x5mm_P0.5mm_EP3.25x3.25mm` | 3.25 × 3.25 mm | 0.80 × 0.25 mm, pad 1 at x = −2.45 |

**Decision: `Package_DFN_QFN:QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm`.**

- 3.10 mm sits inside the datasheet's 3.04–3.24 mm band, 0.04 mm under nominal —
  a conventional, slightly conservative EP land.
- 3.25 mm is **0.01 mm larger than the package's maximum EP (3.24 mm)**. At
  maximum material condition the land is already wider than the pad it solders
  to, and every micron of that overhang is EP paste creeping toward a 0.5 mm
  pitch lead row. Reject it.
- Both land patterns put the lead pad's *outer* edge at the same 2.85 mm from
  centre; they differ only in heel extent. EP-to-lead-heel clearance is 0.35 mm
  for the chosen footprint (1.90 − 1.55), comfortably above JLCPCB's minimum.

Two things to carry into Task 10:

- **Do not use the `_ThermalVias` variant.** `generator/check_via_in_pad.py` is a
  hard verification gate (spec §7) and fails on any via overlapping an SMD pad;
  the `_ThermalVias` footprint puts a via array inside the EP by design. Use the
  plain footprint and stitch ground *around* the pad.
- The `QFN` vs `VQFN` prefix in KiCad's naming tracks package height (this part
  is 0.75 mm, an LFCSP_WQ) and affects only the 3D model and courtyard, not
  copper. The chosen footprint's `descr` field cites a TMC2208 datasheet — it is
  a generic geometric match, selected here by comparing dimensions against
  Figure 79, not a vendor-supplied ADE7953 land pattern.

**Exposed pad connection is mandatory, and it is a ground pin, not just a
thermal tab:** "Create a similar pad on the PCB under the exposed pad. Solder the
exposed pad to the pad on the PCB to confer mechanical strength to the package.
**Connect the pad to AGND and DGND.**" — *Rev. C, p. 10, Table 5 (EPAD); repeated
as the note on Figure 4, p. 9.* The layout guidelines add: "The AGND, DGND, and
PULL_LOW pins traces of the ADE7953 are then routed directly in to the PCB pad."
— *Rev. C, p. 68.*

---

## 3. ADE7953 interface selection (I²C) and address

**The brief's framing needs one correction:** pins 7/8 (`PULL_HIGH`) and 14
(`PULL_LOW`) are **not** interface-selection straps. Table 5 describes them only
as "These pins should be connected to VDD for proper operation" and "This pin
should be connected to AGND for proper operation" respectively — they are
internal-node pins and are tied **directly**, with no resistor. — *Rev. C, p. 9,
Table 5; confirmed by Figure 78, p. 68, which shows direct connections.*

Interface selection is done by `CS` (28) and `SCLK` (25):

**Table 9, Communication Autodetection (Rev. C, p. 51):**

| Interface | Pin 28 `CS` | Pin 25 `SCLK` | Pin 27 | Pin 26 |
|---|---|---|---|---|
| SPI | 0 | don't care | MOSI | MISO |
| **I²C** | **1** | **1** | **SCL** | **SDA** |
| UART | 1 | 0 | Rx | Tx |

Narrative confirmation: "The `CS` pin (Pin 28) is used to determine whether the
communication method is SPI… The `SCLK` pin (Pin 25) is used to determine whether
the communication method is I²C or UART. If this pin is held high, the
communication interface is set to I²C; if it is held low, the communication
interface is set to UART." And: "although Pin 25 (`SCLK`) and Pin 28 (`CS`) are
not required if communicating via I²C or UART, these pins should be configured in
hardware as shown in Table 9 to ensure the functionality of the autodetection
system." — *Rev. C, p. 51.*

Table 5 corroborates per-pin: pin 25 — "If using the I²C interface, this pin must
be pulled high"; pin 28 — "This pin must be pulled high if using the I²C or UART
interface." — *Rev. C, p. 10.*

### So, for this board

| Pin | Net | Fit |
|---|---|---|
| 7, 8 `PULL_HIGH` | `+3V3` | direct, no resistor |
| 14 `PULL_LOW` | `AGND` | direct, no resistor; route into the EP land (p. 68) |
| 25 `SCLK` | `+3V3` | pull-up, 10 kΩ |
| 28 `~CS` | `+3V3` | pull-up, 10 kΩ |
| 27 `MOSI/SCL/Rx` | `I2C_SCL` | shared bus pull-up |
| 26 `MISO/SDA/Tx` | `I2C_SDA` | shared bus pull-up |

**On the 10 kΩ figure — read this before treating it as gospel.** Table 5 and
Table 9 state only "pulled high" / logic 1; they give **no resistor value**. The
Test Circuit (Figure 35, *Rev. C, p. 16*) shows 10 kΩ pull-ups to 3.3 V in this
part of the schematic, but the mirror used here renders figures as flattened
text, so the exact resistor-to-net association in that figure **could not be read
with confidence**. 10 kΩ is recommended and is what Figure 35 uses; the value is
not critical, since both pins are static logic inputs that nothing else drives.
Tying them straight to `+3V3` is equally compliant with Table 9 — the resistors
buy the ability to override the strap for bring-up or a future SPI experiment,
which is worth 2 cents on a board where the interface is autodetected and then
locked.

### I²C address — fixed, no address-select pins

"The address of the ADE7953 is **0111000X**. Bit 7 in the address byte indicates
whether a read or a write is required: 0 indicates a write, and 1 indicates a
read." — *Rev. C, p. 53, "I²C INTERFACE".*

- 7-bit address **0x38**; write byte 0x70, read byte 0x71.
- **There are no address-select pins.** Only one ADE7953 can sit on the bus —
  fine here, since the one part carries both current channels.
- Max SCL 400 kHz; minimum 100 ns between SCL and SDA edges (`tHD;DAT`, Table 3).
  — *Rev. C, p. 53.*
- **Address-collision note for spec §2.5's I²C expansion header:** 0x38 is also
  the base address of the PCF8574**A** I/O expander and is used by some I²C touch
  controllers. A DS3231 RTC (0x68) does not collide. Worth a line in the
  connector documentation so a user does not plug in a conflicting breakout.

### Two firmware requirements this gate should hand to Task 10

- **Lock the interface after the first transaction.** Clear `COMM_LOCK` (Bit 15)
  of `CONFIG` (0x102) shortly after power-up, or the autodetect can be
  re-triggered later. Once locked it cannot change without a reset. — *Rev. C,
  p. 51, "LOCKING THE COMMUNICATION INTERFACE".*
- **The undocumented-looking mandatory unlock write is real and required.** "For
  optimum performance, Register Address 0x120 must be configured by the user
  after powering up… This register is not set by default and thus must be written
  by the user each time the ADE7953 is powered up." Sequence, which "must be
  performed in succession to be successful": write **0xAD to 0xFE**, then **0x30
  to 0x120**. — *Rev. C, p. 18, "REQUIRED REGISTER SETTING".*
- Power-up timing: the chip is inactive below 2 V ±10 %, then held inactive a
  further 26 ms, then ~40 ms to enable internal circuitry. A reset interrupt on
  `IRQ` marks the end of the sequence and "cannot be disabled"; if `IRQ` is not
  used, allow a **≥100 ms** timeout before the first transaction. — *Rev. C, p.
  18, "ADE7953 POWER-UP PROCEDURE".* This argues for routing `IRQ` (pin 22) to a
  GPIO.

---

## 4. ADE7953 support components

All values below are from **Table 5, Pin Function Descriptions, Rev. C, pp.
9–10**, cross-checked against **Figure 78, "ADE7953 Crystal and Capacitors
Connections", Rev. C, p. 68**.

| Pin | Name | Required | Figure 78 refdes |
|---|---|---|---|
| 3 | `VINTD` (2.5 V digital LDO tap) | "decoupled with a **4.7 µF** capacitor in parallel with a **100 nF** ceramic capacitor" | C4 4.7 µF, C3 0.1 µF |
| 15 | `VINTA` (2.5 V analog LDO tap) | "decoupled with a **4.7 µF** capacitor in parallel with a **100 nF** ceramic capacitor" | C2 4.7 µF, C1 0.1 µF |
| 13 | `REF` (1.2 V reference out) | "decoupled with a **4.7 µF** capacitor in parallel with a **100 nF** ceramic capacitor" | C10 4.7 µF, C9 0.1 µF |
| 17 | `VDD` (3.3 V supply) | "decoupled with a **10 µF** capacitor in parallel with a **100 nF** ceramic capacitor" | C5 10 µF, C6 0.1 µF |

Note `VINTA`, `VINTD` and `REF` are **outputs to be decoupled, never driven** —
`VINTA`/`VINTD` expose the internal 2.5 V LDOs and `REF` the internal 1.2 V
reference (an external 1.2 V reference may optionally be applied to `REF`
instead). — *Rev. C, p. 9, Table 5.*

Placement, from the layout guidelines: "The `VDD`, `VINTA`, `VINTD`, and `REF`
pins each have two decoupling capacitors, one of µF order and a ceramic one of
220 nF or 100 nF. These ceramic capacitors need to be placed **closest to the
ADE7953** as they decouple high frequency noises, while the µF ones need to be
placed in close proximity." — *Rev. C, p. 68.*

### Crystal

Pin 18 `CLKIN` / pin 19 `CLKOUT`: "a **parallel resonant AT crystal** can be
connected across the `CLKIN` and `CLKOUT` pins… The clock frequency for specified
operation is **3.58 MHz**. **Ceramic load capacitors of a few tens of picofarads**
should be used with the gate oscillator circuit. **Refer to the crystal
manufacturer's data sheet for the load capacitance requirements.**" — *Rev. C, p.
9, Table 5.*

ADI's own reference circuits use **20 pF** on each of `CLKIN` and `CLKOUT` (C7,
C8 in Figure 78, p. 68; likewise Figure 35, p. 16).

> **COULD NOT VERIFY — the load capacitance of the specified crystal.**
> `C7471632` is `H6OEL89CSC-SUGYLC-3.579545M` (YXC, HC-49S-SMD). LCSC publishes
> no description and no datasheet for it, and neither the jlcsearch nor the
> EasyEDA component API exposes a C_L field. **Task 10 must not simply copy
> 20 pF.** The correct value is `C = 2 × (C_L − C_stray)`, and if this crystal is
> a 20 pF C_L part the load caps should be ≈30 pF, not 20 pF — a real oscillator
> risk, not a rounding argument. Either obtain YXC's datasheet, or switch to a
> crystal whose C_L is published.
>
> **Second, unrelated concern with this crystal choice:** HC-49S-SMD is
> **11.4 × 4.8 mm** (EasyEDA footprint `HC-49S_L11.4-W4.8-LS12.7` for C7471632)
> on a board that spec §6.3 already calls density-constrained. LCSC stocks
> 3.579545 MHz parts in SMD3225-4P (3.2 × 2.5 mm), e.g. `C2838127`
> (`TFOM3.579545M4RHKCNT2T`, 6 566 in stock, $0.339) — ~8× the area saved for
> ~$0.23. Flagging for Task 10 / Task 14; no C_L verified for that part either.

### `~RESET` (pin 2)

"Active Low Reset Input. To initiate a hardware reset, this pin must be brought
low for at minimum of **10 µs**." — *Rev. C, p. 9, Table 5.*

Figure 78 (p. 68) shows no components on pin 2 — it is application-dependent. The
Test Circuit (Figure 35, p. 16) shows a **10 kΩ pull-up to 3.3 V with a 1 µF
capacitor to ground**, giving a power-on reset stretch. That is the recommended
fit. Driving it from a GPIO as well is optional; the ADE7953 also supports a
software reset, and §1 above notes the reset interrupt fires either way.

---

## 5. MAX31856 — `BIAS`, split supplies, input filter

Source: **MAX31856 Precision Thermocouple to Digital Converter with
Linearization**, Maxim Integrated, **19-7534; Rev 0; 2/15** (Rev 0 is the only
revision — Revision History, p. 30). PDF obtained from the rlocman mirror
`https://www.rlocman.ru/i/File/2022/12/20/MAX31856.pdf` and saved locally as
`MAX31856.pdf` (30 pp., verified with `pdfinfo`).

### Pinout — CONFIRMED against the datasheet, no conflict

All 14 pins of the KiCad 10 `Sensor_Temperature:MAX31856` symbol match the Pin
Configuration diagram and Pin Description table, both on **p. 10**: 1 AGND,
2 BIAS, 3 T−, 4 T+, 5 AVDD, 6 DNC, 7 `~DRDY`, 8 DVDD, 9 `~CS`, 10 SCK, 11 SDO,
12 SDI, 13 `~FAULT`, 14 DGND. The datasheet renders overbars on `CS`, `FAULT`
and `DRDY`, consistent with KiCad's `~` on pins 7/9/13.

This is the item spec §7.1.2 specifically demanded be verified from the
datasheet rather than by package convention. It has been.

### a) `BIAS` (pin 2) — **there is no BIAS bypass capacitor**

This corrects the premise of the question as asked.

- Pin description, **p. 10**: "Bias Voltage Source. Nominally 0.735 V. This pin
  is floating when no conversions are taking place." **No bypass or decoupling
  is specified** — pointedly unlike AVDD and DVDD, whose entries in the same
  table both say "Bypass with a 0.1 µF capacitor".
- Its job is to set the input common mode: "T− is biased to approximately
  0.735 V by the BIAS output" (**p. 11**), and "Connect the BIAS output to T−.
  This biases the thermocouple within the common-mode range of the inputs."
  (**p. 27**).
- Electrical Characteristics, **p. 3**: `V_BIAS` = 0.735 V, `R_BIAS` = 2 kΩ,
  input common-mode range 0.5 V–1.4 V.
- **The 0.01 µF capacitor drawn near BIAS in the datasheet's own schematics is
  the T− common-mode filter capacitor, not a BIAS bypass.** In the Typical
  Application Circuit (**p. 1**) BIAS ties directly to the T− node so the two
  share a node and the cap looks like it belongs to BIAS; in **Figure 8, p. 27**,
  where 100 Ω series resistors are present, BIAS connects to the thermocouple
  side of the resistor while the 0.01 µF connects from the **T− pin** to AGND.
  Do not add a separate capacitor on pin 2.
- Absolute Maximum Ratings, **p. 2**: T+, T−, BIAS rated ±45 V and ±20 mA;
  Note 8 (p. 5) confirms the over/undervoltage limits cover BIAS.

### b) AVDD (5) and DVDD (8) on one 3V3 rail — **yes, and effectively required**

- Recommended DC Operating Conditions, **p. 2**, specifies **`AVDD − DVDD` =
  −100 mV to +100 mV**. A ±100 mV matched-supply requirement means the two pins
  must share a rail; they cannot be separately regulated.
- Both the Typical Application Circuit (**p. 1**) and Figure 8 (**p. 27**) show
  AVDD and DVDD on a common 3.3 V net.
- **Decoupling is per-pin and the ground references differ** — Pin Description
  table, **p. 10**:
  - Pin 5 AVDD — "Bypass with a 0.1 µF capacitor **to AGND**."
  - Pin 8 DVDD — "Bypass with a 0.1 µF capacitor **to DGND**."
- Placement: "The effects of power-supply noise can be minimized by placing
  0.1 µF ceramic bypass capacitors close to the V_DD pins and to GND" — **p. 27,
  Noise Considerations**. No distance figure is given.
- Supply range, **p. 2**: 3.0 V min / **3.3 V typ** / 3.6 V max, so 3.3 V is the
  datasheet's own typical. Abs max −0.3 V to +4.0 V. `V_POR` = 2.7 V min /
  2.85 V max (**p. 3**). Supply current 5.25 µA typ standby, 1.2 mA typ /
  2 mA max converting (**p. 2**).
- Logic thresholds for the ESP32-S3 side, **p. 2**: `V_IL` ≤ 0.8 V, `V_IH` ≥
  2.1 V — comfortably met by 3.3 V CMOS.

### c) Recommended thermocouple input filter (T+ / T−, pins 4/3)

From **Noise Considerations and Figure 8, p. 27** ("Typical Connection to Reduce
the Effect of Noise Pickup in the Thermocouple Cable"):

| Component | Value | Status |
|---|---|---|
| Series R, each leg (T+ and T−) | **100 Ω** | shown in Figure 8 |
| Differential C, across T+/T− | **100 nF** | "**strongly recommended**" |
| Common-mode C, T+→GND and T−→GND | **10 nF** each | for "high noise levels, especially significant RF fields" |

Exact wording: "It is strongly recommended to add a 100 nF ceramic surface-mount
differential capacitor, placed across the T+ and T− pins, to filter noise on the
thermocouple lines." And: "In environments with high noise levels, especially
significant RF fields, a 100 nF capacitor between T+ and T− should be
supplemented with a 10 nF capacitor between T+ and GND, and another 10 nF
capacitor between T− and GND." — **p. 27**.

**Fit all five on this board.** A kiln controller sits beside SSR-switched
element wiring with a Wi-Fi radio on the same PCB; that is the RF-field case the
datasheet is describing.

Topology detail from Figure 8: **all three capacitors are on the IC side of the
100 Ω resistors**; the resistors sit between the thermocouple leads and the
T+/T− pins.

Caveats the datasheet attaches, which matter for a two-channel design:

- "These values may need to be modified depending on the nature of the noise
  pickup" (**p. 27**).
- Series resistance costs offset: "added resistance in series with T+ and T− can
  increase offset voltage" (**p. 27**). The Effect of Series Resistance section
  (**p. 28**) gives `IB × ΔRS + ΔIB × RS`, worked as `65 nA × (50 Ω + 1 Ω) +
  4 nA × 100 Ω = 3.7 µV` for Figure 8's 100 Ω mismatched by 1 Ω with 50 Ω of
  cable at 85 °C. Negligible for kiln work, but it argues for **1 % resistors**
  so ΔRS stays small.
- The R/C choice interacts with fault detection: Table 4, Open-Circuit Detection
  Mode (**p. 14**), buckets detection timing by `RS < 5 kΩ` vs `40 kΩ > RS >
  5 kΩ` **and** by whether the input network's time constant is above or below
  2 ms. With 100 Ω and 100 nF the constant is ~10 µs, safely in the fast bucket.
- `R_CABLE` max is 40 kΩ per lead (**p. 2**) — no constraint for kiln lead
  lengths.
- If higher fault voltages are ever expected, Figure 9 (**p. 28**) substitutes
  **2 kΩ** in series with T+, T− *and* BIAS, buying "an additional ±40 V of
  overdrive before the 20 mA input current limit is reached" (**p. 27**). Not
  proposed here — note the 900 mW dissipation warning in that paragraph.

---

## 6. ULN2003 input state with a high-impedance ESP32 pin at boot — **10 kΩ IS SUFFICIENT**

Source: TI **SLRS027T**, "ULx2003A, ULQ200x High-Voltage, High-Current Darlington
Transistor Arrays", DEC 1976 – revised MARCH 2025, 42 pp. Local copy:
`ULN2003A.pdf`.

### What the datasheet actually specifies

- **Series base resistor 2.7 kΩ per channel**: "The ULx2003A devices have a
  2.7 kΩ series base resistor for each Darlington pair for operation directly
  with TTL or 5 V CMOS devices" — Description, **p. 1**. Confirmed in **Figure
  7-2, p. 14**, which also shows internal **7.2 kΩ** and **3 kΩ** base-emitter
  pulldowns.
- Those internal pulldowns exist for exactly this purpose: "The 7.2 kΩ and 3 kΩ
  resistors connected between the base and emitter of each respective NPN act as
  pulldowns and **suppress the amount of leakage that may occur from the
  input**" — §7.3, **p. 15**. But "All resistor values shown are nominal" (note
  above Figure 7-1, **p. 14**) — no tolerance, so they cannot carry the argument
  alone.
- **There is no `V_I(off)` voltage threshold for the ULN2003A — the off state is
  specified as a current.** `I_I(off)` = **50 µA min**, 65 µA typ, at
  `V_CE = 50 V, T_A = 70 °C, I_C = 500 µA` (Figure 6-3 test circuit) — §5.6,
  **p. 6**. Read as a guarantee: no unit reaches 500 µA of collector current with
  less than 50 µA into the input. (The ULN200**4**A does get a voltage-referenced
  spec, `V_I = 1 V → I_CEX 500 µA max`; that row is in the 2004A column only and
  does not apply to our part.)
- `I_CEX` collector cutoff, §5.6 **p. 5**: 50 µA max and 100 µA max at
  `V_CE = 50 V, I_I = 0` — so a fully-off channel can still sink up to 100 µA.
- `V_I(on)`, §5.6 **p. 5**, at `V_CE = 2 V`: 2.4 V max @ 200 mA, 2.7 V @ 250 mA,
  3.0 V @ 300 mA — guaranteed-*on* voltages, not thresholds.
- ESP32-S3 pin leakage `I_IH`/`I_IL` = **50 nA max** — *ESP32-S3 Series Datasheet
  v2.2*, **Table 5-4, "DC Characteristics (3.3 V, 25 °C)", p. 65**; the same
  table gives internal `R_PU`/`R_PD` = **45 kΩ typ**, with **no min or max**.

### The arithmetic, for a genuinely Hi-Z pin

Worst case, ignoring the ULN's nominal-only internal resistors entirely so the
bound holds regardless of their tolerance:

```
V_in(max) = I_leak(max) x R_pd = 50 nA x 10 kΩ = 0.5 mV
I_in(max) = 50 nA                    vs  I_I(off) min = 50 µA  →  1000x margin
```

Including the internal network (2.7 k + 7.2 k = 9.9 kΩ, nominal): node impedance
`10 k ∥ 9.9 k = 4.97 kΩ`, so `V_in ≈ 50 nA × 4.97 kΩ ≈ 249 µV` and
`I_in ≈ 25 nA` → **2000× margin**.

Voltage-domain sanity check (derived from the datasheet's own `I_I` spec of
0.93 mA typ at `V_I` = 3.85 V through `R_B` = 2.7 kΩ, **p. 6**): the base only
starts to see current once the pin is around `3.85 − 0.93 mA × 2.7 kΩ ≈ 1.3 V`.
That is ~5400× above the 0.25 mV computed above.

### The case that would have broken it — and why it does not apply here

If a driving GPIO asserted an **internal weak pull-up** at reset, 10 kΩ would be
marginal rather than safe:

```
R_node = 10 k ∥ 9.9 k = 4.975 kΩ
V_in   = 3.3 V x 4.975 / (45 + 4.975) = 0.328 V
I_in   = 0.328 V / 9.9 kΩ = 33.2 µA   vs  I_I(off) min = 50 µA  →  only 1.5x
```

and `R_PU` is a **typ with no minimum specified**, so that 1.5× is not a bounded
worst case — at `R_PU` = 30 kΩ it reaches 47 µA and the margin is gone.

**Checked against this board's actual pin map, and it does not apply.** Spec
§5.2 puts the three used ULN2003 channels on **GPIO 14, 15 and 16**. From Table
2-1, Pin Overview, *ESP32-S3 Series Datasheet v2.2*, **pp. 16–17** (legend
p. 18: "IE – input enabled", "WPU – internal weak pull-up resistor enabled"):

| GPIO | Chip pin | At Reset | After Reset |
|---|---|---|---|
| GPIO14 | 19 | `IE` | *(blank)* |
| GPIO15 | 21 (`XTAL_32K_P`) | *(blank)* | *(blank)* |
| GPIO16 | 22 (`XTAL_32K_N`) | *(blank)* | *(blank)* |

**None of the three has `WPU`.** GPIO14 is input-enabled with no pull; GPIO15 and
GPIO16 have neither input enable nor any pull at reset — more inert still. The
Hi-Z case above is the governing one, and **10 kΩ passes with ~1000× margin.**
Spec §7.1 risk 4 is retired.

### The guard rail this implies for Tasks 8 and 14

The 10 kΩ value is safe **because of which pins were chosen**, not
unconditionally. In the whole general-purpose GPIO pool the pins that are
`WPU, IE` at reset are **GPIO0** (a strapping pin) and **GPIO20** (`USB_PU`),
plus the `VDD_SPI` flash pins (SPICS1/SPIHD/SPIWP/SPICS0/SPICLK/SPIQ/SPID),
which are unavailable anyway. GPIO45 and GPIO46 are `WPD, IE` — pull-*down*,
which helps.

So: **if a future re-map ever moves an aux channel onto GPIO0, drop that
channel's pulldown to 4.7 kΩ or lower.** For reference, at `R_PU` = 45 kΩ typ:
4.7 kΩ gives 22.0 µA (2.3×) and 2.2 kΩ gives 12.8 µA (3.9×). This is a good
candidate assertion for `generator/check_pinmap.py`.

---

## 7. LTV-817S-TA1-C — pinout, footprint, CTR

> **Historical.** The optocouplers were removed from the board before fab —
> opto-isolation only isolates if the SSR control loop is powered off-board,
> and this board powers it (hardware-design spec §2.4). This section is kept
> as the datasheet record it always was; nothing on the current board uses it.


Source: Lite-On **"Photocoupler Product Data Sheet LTV-817 (M, S, S-TA, S-TA1,
S-TP) Series"**, Spec No. **DS70-2012-0050, Revision C**, effective 2014-12-20,
12 pp. Saved locally as
`LTV-817_LiteOn_Photocoupler_M_S_S-TA_S-TA1_S-TP_RevC.pdf`.

### a) Pinout — CONFIRMED, the assumed order is correct

The "Pin No. and Internal connection diagram" printed inside **§2.3 "LTV-817S",
p. 2/12** legends explicitly: **1 Anode, 2 Cathode, 3 Emitter, 4 Collector**. The
same figure shows pins 1–2 as the LED and pins 4–3 as the phototransistor
(collector upper-left, emitter upper-right).

So KiCad's unnamed `Isolator:LTV-817` pin order — 1 anode, 2 cathode, 3 emitter,
4 collector — is correct **as verified from the datasheet**, not as assumed from
convention. (This is the second of the two "do not trust package convention"
items spec §7.1.2 raised.)

### b) Footprint — **NONE of the four candidates fit. This one would have killed the board.**

Package drawing, **§2.3, p. 2/12**, all in mm:

| Dimension | Value |
|---|---|
| Body, along pin rows | 4.6 ± 0.5 |
| Body, along lead span | 6.5 ± 0.5 |
| Body height | 3.5 ± 0.5 |
| **Lead pitch** | **2.54 ± 0.25** |
| Lead row spacing at the shoulder | 7.62 ± 0.3 |
| **Overall lead span, gull-wing tip to tip** | **10.16 ± 0.3** |
| Foot length | 1.0 ± 0.25 |
| Lead thickness | 0.26 ± 0.1 |
| Standoff | 0.35 +0.25 / −0.30 |

The 2.54 mm pitch premise is **confirmed from the drawing**: the LTV-817S is a
gull-wing "surface-mount DIP" that keeps DIP lead pitch, so a 1.27 mm-pitch
footprint is indeed wrong.

**Measured from the installed KiCad 10 library** (`Package_SO.pretty`,
`Package_DIP.pretty`), pad centre-to-centre:

| Footprint | Pitch | **Pad row span (C–C)** | Verdict |
|---|---|---|---|
| `SO-4_4.4x2.3mm_P1.27mm` | 1.27 | **6.30** | wrong pitch *and* span |
| `SO-4_4.4x3.6mm_P2.54mm` | 2.54 | **6.30** | span far too small |
| `SO-4_4.4x3.9mm_P2.54mm` | 2.54 | **6.30** | span far too small |
| `SO-4_4.4x4.3mm_P2.54mm` | 2.54 | **6.00** | span far too small |
| `Package_DIP:SMDIP-4_W9.53mm` | 2.54 | **9.53** | closest stock part |

**The brief's stated differentiator is wrong, and that is why the shortlist was
wrong.** In KiCad's `SO-4_AxB_P2.54mm` naming, the 3.6 / 3.9 / 4.3 figure is
**not** the lead span — it is the *body* dimension along the pin rows. Confirmed
from the `F.Fab` outline of `SO-4_4.4x3.6mm_P2.54mm`, which spans X −2.2…+2.2
(4.4 mm) and Y −1.8…+1.8 (3.6 mm) with pads at X = ±3.15. All three 2.54 mm
candidates sit at ~6.0–6.3 mm span regardless of the name.

Against a required ~10 mm, choosing any of the four would place each pad roughly
**1.85 mm per side inboard of the actual gull-wing feet — the part would not land
on copper at all.** DRC cannot see this.

**Cross-check against LCSC's own library** (`easyeda.com/api/products/C109227/components`),
independently re-decoded here: footprint `OPTO-SMD-4_L4.6-W6.5-P2.54-LS10.3-BL`,
pads at **2.54 mm pitch**, **10.00 mm row span (C–C)**, pad size **1.5 × 3.0 mm**.
That agrees with the datasheet's 4.6 / 6.5 / 2.54 / 10.16 — **the two sources do
not disagree.**

**Recommendation for Task 7:** generate the footprint to LCSC's geometry — pads
at ±5.00 mm, 1.5 × 3.0 mm, 2.54 mm pitch — since the board is JLCPCB-assembled
and LCSC's library is what the placement machine is fed. If a stock KiCad part
must be used, `Package_DIP:SMDIP-4_W9.53mm` is the only defensible one: at
9.53 mm span its 3.765–5.765 mm pads still capture the 1.0 mm foot (which lands
at 4.08–5.08 mm from centre) with ~0.32 mm heel and ~0.69 mm toe. It is 0.235 mm
per side inboard of LCSC's geometry — acceptable, not ideal.

### c) CTR bin C, and the drive-current floor

**Rank table, §5 "RANK TABLE OF CURRENT TRANSFER RATIO CTR", p. 7/12:** bin **C =
200 % min, 400 % max**, at **`I_F` = 5 mA, `V_CE` = 5 V, `T_a` = 25 °C**. (Series
bins: L 50–100, A 80–160, B 130–260, C 200–400, D 300–600.)

| Drive | Guaranteed minimum `I_C` | Status |
|---|---|---|
| `I_F` = 5 mA | **10 mA** (5 mA × 200 %) | **directly guaranteed** — 5 mA is the bin's own test condition |
| `I_F` = 10 mA | 20 mA | **extrapolation, NOT a spec** — see below |

Corroboration: §4.2 independently specs `I_C` 2.5 mA min / 30 mA max at
`I_F` = 5 mA, `V_CE` = 5 V for the ungraded part; the C bin tightens that minimum
to 10 mA.

**The rank table's only condition is `I_F` = 5 mA — there is no guaranteed CTR at
10 mA.** 20 mA is a reasonable floor because Fig. 5 shows typical CTR *rising*
from 5 to 10 mA, but it must be treated as an extrapolation.

**CTR does fall off below 5 mA, and steeply.** §6 **Fig. 5, "Current Transfer
Ratio vs. Forward Current", p. 8/12** (25 °C, log-log, `V_CE` = 5 V), read
graphically at ±10 % relative: ≈355 % at 10 mA, ≈290 % at 5 mA, ≈150 % at 1 mA,
≈27 % at 0.1 mA, peaking ≈370 % around 13–15 mA.

> **Design rule for Task 7: do not drive this LED below 5 mA.** CTR roughly halves
> by 1 mA and is down an order of magnitude by 0.1 mA, and **below the 5 mA bin
> condition there is no guaranteed minimum CTR at all.**

**Forward voltage.** §4.2 guarantees `V_F` **typ 1.2 V / max 1.4 V at `I_F` =
20 mA** — that is the *only* specified `V_F` point. From §6 Fig. 4, "Forward
Current vs. Forward Voltage", p. 8/12 (25 °C typical): ≈1.09 V at 5 mA, ≈1.14 V
at 10 mA, ≈1.2 V at 20 mA (the 20 mA read reproduces the table's typ, which
calibrates the others to ±0.05 V). **Use 1.4 V for worst-case series-resistor
sizing.** A guaranteed `V_F` max at 5 or 10 mA is **COULD NOT VERIFY** — Lite-On
only specifies it at 20 mA.

**Absolute maximums, §4.1, p. 5/12:** `I_F` 50 mA, **`V_CEO` 35 V**, `V_R` 6 V,
`V_ECO` 6 V, `I_C` 50 mA, P(input) 70 mW, `P_C` 150 mW, `P_tot` 200 mW,
**`V_iso` 5000 Vrms (1 min)**, `T_opr` −50…+110 °C.

---

## 8. Charge-pump Schottky and the AO3400A gate — **PASSES, with one corner to know about**

Sources: Nexperia **BAT54S Schottky barrier diodes**, product data sheet, **1
July 2022**, 9 pp., saved as `BAT54S_Nexperia.pdf`; and Alpha & Omega
**AO3400A 30 V N-Channel MOSFET, Rev 3.1, July 2023**, already on disk.

### a) Part selection

- **BAT54S, SOT-23, LCSC `C7420333`** — JLCPCB class **Extended**, but flagged
  **Preferred**; stock ~197 k–315 k, **$0.0110**. Sources: `jlcsearch` API and
  `easyeda.com/api/products/C7420333/components`.
- **There is no JLCPCB *Basic* dual Schottky.** BAT54S, BAT54SW, BAT54C, BAT54A,
  BAT54, BAR43C, BAS40-04 and a generic dual-Schottky query all return
  `is_basic: false`. An Extended feeder is unavoidable here; picking a
  **Preferred** Extended part minimises the risk of it being unavailable at
  assembly time.
- **BAT54S is the correct member of the family** — it is the **series** pair.
  Table 2 "Pinning information", p. 1: pin 1 = A1, pin 2 = K2, pin 3 = K1;A2. The
  shared pin 3 is the pump node. (BAT54C is common-cathode, BAT54A common-anode;
  neither gives a series pair.)

### b) `V_F` at pump current — *not* at 100 mA

**Table 7 "Characteristics", p. 3/9** (25 °C, pulsed, `t_p` ≤ 300 µs, δ ≤ 0.02),
**max** values:

| `I_F` | `V_F` max |
|---|---|
| **0.1 mA** | **240 mV** |
| 1 mA | 320 mV |
| 10 mA | 400 mV |
| 30 mA | 500 mV |
| 100 mA | 800 mV |

The pump only holds a MOSFET gate, so it runs at roughly 10–100 µA and
**240 mV is the right worst-case number**. Using the 800 mV @ 100 mA figure would
understate the gate voltage by ~1.1 V and is the classic way to get this wrong.
Typical values from **Fig. 1, p. 3/9** (curve 3, 25 °C), read graphically at
±0.02 V: ≈0.16 V at 100 µA, ≈0.21 V at 1 mA, ≈0.30 V at 10 mA. 0.1 mA is the
datasheet's lowest specified point; below it only the curve exists, and it trends
lower.

### c) AO3400A threshold

**Electrical Characteristics, STATIC PARAMETERS, p. 2/5:**
**`V_GS(th)` = 0.65 V min / 1.05 V typ / 1.45 V max**, at `V_DS` = `V_GS`,
`I_D` = 250 µA. (The table prints "ID=250mA"; that is an AOS unit typo for the
standard 250 µA threshold condition. It does not affect the min/typ/max values
used here — noted so nobody re-derives it and thinks the table is being
misquoted.)

### d) The arithmetic

**At the stated 3.3 V drive, worst-case diode drops:**

```
V_gate  = 3.3 V − 2 x V_F(max @ 0.1 mA)
        = 3.3 V − 2 x 0.240 V
        = 2.82 V

Margin  = 2.82 V − V_GS(th),max
        = 2.82 V − 1.45 V
        = +1.37 V
```

Sanity band: at the 1 mA `V_F` max (0.320 V) → `V_gate` = 2.66 V, margin
**+1.21 V**. At typical `V_F` (0.16 V) → 2.98 V, margin **+1.53 V**.

**Verdict: ADEQUATE.** The gate sits at ~1.9× the worst-case threshold with
1.2–1.4 V of headroom. Not a marginal design at the 3.3 V assumption.

**Is the FET actually enhanced?** `R_DS(ON)` rows, p. 2/5: 26.5 mΩ max @
`V_GS` = 10 V; 32 mΩ max @ 4.5 V; **48 mΩ max @ `V_GS` = 2.5 V, `I_D` = 3 A**. At
2.66–2.82 V the part is above the 2.5 V spec point, so the 48 mΩ guarantee
applies conservatively. Plenty for a watchdog gate.

### The corner worth knowing — the 3.3 V premise is optimistic

The pump is driven by an **ESP32 GPIO, not a 3.3 V rail**, and the guaranteed
`V_OH` minimum is **0.8 × VDD = 2.64 V** — *ESP32-S3 Series Datasheet v2.2*,
**Table 5-4, "DC Characteristics (3.3 V, 25 °C)", p. 65**. Redoing it at
guaranteed minimum drive:

```
V_gate = 2.64 V − 2 x 0.240 V = 2.16 V
Margin = 2.16 V − 1.45 V      = +0.71 V
```

**Still positive — the FET turns on, and this is not a blocker.** Two things
follow, though:

1. At 2.16 V the gate is **below the 2.5 V `R_DS(ON)` spec point, and the AO3400A
   guarantees no `R_DS(ON)` at all below `V_GS` = 2.5 V.** Do not size the
   watchdog's load assuming a guaranteed on-resistance in that corner.
2. The `V_OH` spec carries a "measured using high-impedance load" footnote, which
   is on our side: a µA-scale pump load means `V_OH` will sit very near VDD in
   practice. The 2.64 V figure is a floor, not an expectation.

If Task 12 wants the 2.5 V spec point guaranteed in every corner, a lower-`V_F`
Schottky or a single-diode topology buys the ~0.35 V needed.

---

## 9. U.FL clearance on the WROOM-1U

Source: Espressif **"ESP32-S3-WROOM-1 & ESP32-S3-WROOM-1U Datasheet v1.8"**, 53
pp. — already on disk as
`ESP32-S3-WROOM-1-N16R8_RF_Module_...pdf`. It does contain the 1U dimensions; no
external fetch was needed.

### a) Connector height — it does **not** stand proud of the module

- **Connector height above the module PCB: 1.25 ± 0.15 mm** — **Figure 10-3,
  "Dimensions of External Antenna Connector", §10.2, p. 43**, side elevation.
- Same figure: body footprint 2.60 ± 0.15 mm square; mating boss Ø2.00 ± 0.05 mm;
  land pattern (3.10) mm overall including two 0.25 ± 0.10 mm side tabs.
  Compatible with "U.FL Series connector from Hirose", "MHF I connector from
  I-PEX", "AMC connector from Amphenol".
- **Module overall thickness with the connector: 3.2 ± 0.15 mm** — **Figure 10-2,
  §10.1, p. 42** (module PCB itself 0.8 mm). The WROOM-1 is 3.1 ± 0.15 mm.
- Therefore the connector's top face is at 0.8 + 1.25 = **2.05 mm** above the
  module PCB's underside — **below the 3.2 mm overall envelope. The bare U.FL
  does not protrude above the module's shield can** and adds no height of its own.
  **This corrects spec §7.1.6's premise** ("The connector stands proud of the
  module"). A *mated plug* does add height; the receptacle alone does not.

### b) Pigtail exit direction — **COULD NOT VERIFY**

**Espressif does not state a cable exit direction anywhere in this datasheet.**
Checked: §10.2 and Figure 10-3 (p. 43) give receptacle geometry and materials
only; p. 44 covers antenna gain/type with no mechanical routing guidance; §11.2
"Module Placement for PCB Design" (p. 46) defers entirely to the external *ESP32-S3
Hardware Design Guidelines*; and a full-text search for "clearance", "keep-out"
and "keepout" across all 53 pages returns nothing about the connector.

What *is* verifiable from Figure 10-3: the mating interface is a **vertical
(board-normal) coaxial receptacle** — the Ø2.00 mm boss is concentric about an
axis perpendicular to the mounting plane, and section A-A shows the centre
contact standing up out of the housing. So **the plug mates downward onto the
module and the coax leaves laterally, but the azimuth of that lateral exit is set
by how the plug is oriented at assembly, not by the module.**

> **For Task 14: budget clearance in every azimuth. Do not assume the pigtail
> leaves toward a particular board edge** — nothing in the datasheet fixes it.

**Connector position, which is what actually drives the keepout** — Figure 10-2,
p. 42, top view: the receptacle sits at the **corner of the antenna-end edge**,
centreline **3 mm from one side edge** and **2.46 mm from the antenna-end edge**.

### c) Module outlines, 1 vs 1U — §10.1, p. 42

| | WROOM-1 (Fig. 10-1) | WROOM-1U (Fig. 10-2) |
|---|---|---|
| Width | 18 ± 0.2 mm | 18 ± 0.2 mm |
| **Length** | **25.5 ± 0.2 mm** | **19.2 ± 0.2 mm** |
| Thickness | 3.1 ± 0.15 mm | 3.2 ± 0.15 mm |
| Pad rows | 16.51 mm span, 1.27 mm pitch, 40 × 0.9 mm | identical |
| Bottom row | 13.97 mm, 40 × 0.45 mm | identical |
| Antenna | PCB antenna, top ~6 mm | U.FL at 3 mm / 2.46 mm from the corner |

Length difference **25.5 − 19.2 = 6.3 mm**.

### d) The origin offset is stated, and it is 6.30 mm

This is the number spec §7.1.5 needs, and Espressif gives it explicitly in the
land patterns (§11.1):

- **Figure 11-1, WROOM-1 Recommended PCB Land Pattern, p. 45:** antenna-end
  outline to the pad-1/pad-40 centreline = **7.49 mm**. The figure also draws an
  **"Antenna Area" keepout of 18 × 6 mm** at that end.
- **Figure 11-2, WROOM-1U Recommended PCB Land Pattern, p. 46:** the same
  dimension is **1.19 mm**, and **no "Antenna Area" band is drawn at all**.
- **7.49 − 1.19 = 6.30 mm**, reconciling exactly with the 6.3 mm body difference.
  The land pattern is otherwise identical between the two figures (16.51, 13.97,
  40 × 0.9, 40 × 1.5, 1.27, 10.29, 3.7 × 3.7 thermal array, 7.5, 15, 26,
  0.5/1.27/2.015 all present and equal).
- Espressif states the consequence in words: "The pin diagram is applicable to
  ESP32-S3-WROOM-1 and ESP32-S3-WROOM-1U, but the latter has no antenna keepout
  zone." — note under **Figure 3-1, §3.1, p. 10**.

**Net for Task 14:** swapping WROOM-1 → WROOM-1U on an unchanged land pattern
reclaims a band **18 mm wide × 6.30 mm deep** beyond the module's antenna-end
edge, and the 18 × 6 mm RF keepout that band carried is explicitly withdrawn. Two
constraints replace it: (1) the U.FL sits *inside* the 1U outline but only
**2.46 mm** from that reclaimed edge, so a mated plug and its coax pass directly
over the boundary — parts placed in the band must clear a mated plug, which is
taller than the bare 1.25 mm receptacle, in an **unspecified azimuth**; (2) height
under the module is unchanged at 0.8 mm PCB plus standoff.

**This also confirms the CPL risk in spec §7.1.5 is real and quantified at
6.30 mm** — Task 15 must re-check the WROOM-1U's placement origin in JLCPCB's
preview rather than assume the WROOM-1's carries over.

---

## 10. Items recorded as COULD NOT VERIFY

Listed so nobody downstream mistakes a gap for a checked fact. None of these
blocks Tasks 8, 10 or 12; each is flagged where it lands.

| # | Item | Why | Who needs it |
|---|---|---|---|
| 1 | **ADE7953 crystal load capacitance** for `C7471632` (YXC `H6OEL89CSC-SUGYLC-3.579545M`) | LCSC publishes no datasheet and no description for this MPN; neither the jlcsearch nor the EasyEDA API exposes a `C_L` field | **Task 10** — 20 pF is ADI's *reference* value, not this crystal's requirement. If `C_L` = 20 pF the caps should be ~30 pF. Get YXC's datasheet or pick a crystal with a published `C_L`. |
| 2 | **ADE7953 ampere-hour accumulation enable bit** | The register bit tables (pp. 60–67) did not survive text extraction from the mirror; the narrative on p. 32 describes the mode without naming the bit | **Task 10** — it is in `LCYCMODE` (0x004). Firmware detail, not a layout blocker. Do not guess it. |
| 3 | **ADE7953 pull-up resistor *values* on `~CS` (28) and `SCLK` (25)** | Table 5 and Table 9 specify only "pulled high" / logic 1. Figure 35 shows 10 kΩ in that area but the text-only mirror cannot confirm the resistor-to-net association | **Task 10** — 10 kΩ recommended; value is not critical (static logic inputs). See §3. |
| 4 | **ADE7953 guidance for unused `VP`/`VN`** | The datasheet gives none | **Task 10** — the termination in §1 is an engineering recommendation, explicitly labelled as such, not datasheet text. |
| 5 | **LTV-817 `V_F` maximum at 5 mA or 10 mA** | Lite-On specifies `V_F` only at `I_F` = 20 mA (typ 1.2 V, max 1.4 V) | **Task 7** — size series resistors against 1.4 V worst case. Curve reads at 5/10 mA are typicals only. |
| 6 | **U.FL pigtail exit azimuth** | Not stated anywhere in the Espressif module datasheet; it is set by plug orientation at assembly | **Task 14** — budget clearance in every azimuth. See §9b. |
| 7 | **Which ADE7953 registers are gated by no-load detection in ampere-hour mode** | p. 32 says the apparent-energy no-load feature "remains active" in this mode but the no-load threshold sections were not extracted in full | **Task 10** — only affects accumulation, not `IRMS` itself. |

### Graphical reads (values taken off curves, not tables)

These are legitimate datasheet sources but carry read tolerance, so they are
flagged rather than presented as specs: LTV-817 CTR vs `I_F` (Fig. 5, ±10 %
relative) and `V_F` vs `I_F` (Fig. 4, ±0.05 V); BAT54S `V_F` typicals (Fig. 1,
±0.02 V). Every *guaranteed* number quoted in §7 and §8 comes from a
characteristics table, not a curve.

### PDFs that could not be mirrored into this directory

`analog.com` is unreachable from this build environment, so **no ADE7953 PDF is
stored here** — §1–§4 cite Rev. C page numbers verifiable against the canonical
document. The MAX31856, LTV-817, BAT54S and ESP32-S3 PDFs *were* obtained and are
in this directory, but note they are **git-ignored by design** (see
`hardware/kicad/.gitignore` — the directory is a regenerable cache; only this
notes file is tracked).

---

## 11. LCSC stock check

Re-checked **2026-08-11** via `https://jlcsearch.tscircuit.com/api/search`.
Spec baseline was 2026-08-10.

| LCSC | MPN | Package | JLCPCB class | Stock | Unit price |
|---|---|---|---|---|---|
| C3013945 | ESP32-S3-WROOM-1U-N16R2 | SMD 19.2 × 18 mm | Extended | 3 507 | $4.8396 |
| C2653162 | MAX31856MUD+T | TSSOP-14 | Extended | 7 744 | $4.3519 |
| C515890 | ADE7953ACPZ-RL | LFCSP-28 (5 × 5) | Extended | 4 846 | $3.4100 |
| C7471632 | H6OEL89CSC-SUGYLC-3.579545M | HC-49S-SMD | Extended | 13 518 | $0.1065 |
| C7512 | ULN2003ADR | SOIC-16 | **Basic** | 420 533 | $0.1579 |
| C109227 | LTV-817S-TA1-C | SMD-4P | **Basic** | 597 938 | $0.0749 |
| C558418 | SRV05-4 | SOT-23-6 | Extended | 377 254 | $0.0216 |

**All seven resolve with non-zero stock.** No part has moved out of stock or
changed JLCPCB class since the 2026-08-10 baseline. `ULN2003ADR` and
`LTV-817S-TA1-C` are confirmed **Basic** (no feeder fee), as spec §2.3 and §2.4
assume. The remaining five are Extended.

The thinnest margin is **C3013945 (WROOM-1U) at 3 507 units** — ample for a
prototype run, but it is the lowest-stock line and the one part with no
substitute that keeps the pin map, so re-check it at order time.
