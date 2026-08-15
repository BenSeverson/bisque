/*
 * MAX31856 register map and conversion maths.
 *
 * Deliberately free of ESP-IDF so tests/host/test_max31856.c can cover it.
 * thermocouple.c keeps everything that needs a real SPI bus; this header keeps
 * everything that can be wrong without being a build error.
 *
 * All references are to Maxim 19-7534 Rev 0 (2/15), the part's only revision.
 * A local copy lives in hardware/kicad/datasheets/MAX31856.pdf — note that
 * directory is git-ignored, so it is absent from fresh clones and worktrees.
 */
#pragma once

#include <stdint.h>

#include "thermocouple.h" /* TC_FAULT_* — the fault vocabulary callers speak */

/* Register addresses (Table 6, p. 18). Reads use the address as-is, writes OR
   in bit 7: "the registers are accessed using the 0Xh addresses for reads and
   the 8Xh addresses for writes". */
#define MAX31856_REG_CR0   0x00
#define MAX31856_REG_CR1   0x01
#define MAX31856_REG_MASK  0x02
#define MAX31856_REG_CJTH  0x0A /* cold junction, MSB; CJTL is 0x0B */
#define MAX31856_REG_LTCBH 0x0C /* linearized TC, byte 2; LTCBM/LTCBL follow */
#define MAX31856_REG_SR    0x0F
#define MAX31856_WRITE_BIT 0x80

/* CR0 bits (p. 19). */
#define MAX31856_CR0_CMODE           0x80 /* 1 = automatic conversion, ~100 ms */
#define MAX31856_CR0_1SHOT           0x40
#define MAX31856_CR0_OCFAULT1        0x20 /* OCFAULT[1:0] are bits 5:4 */
#define MAX31856_CR0_OCFAULT0        0x10
#define MAX31856_CR0_CJ_DISABLE      0x08 /* 1 = internal cold junction off */
#define MAX31856_CR0_FAULT_INTERRUPT 0x04 /* 0 = comparator mode */
#define MAX31856_CR0_FAULTCLR        0x02
#define MAX31856_CR0_FILT_50HZ       0x01 /* 0 = reject 60 Hz (factory default) */

/* Open-circuit detection every 16 conversions, R_S < 5 kOhm timing — Table 4,
   p. 14. Rev B puts 100 Ohm in series with each leg and 100 nF across the pair
   (hardware/kicad/datasheets/REV-B-NOTES.md section 5c), so R_S is ~100 Ohm and
   the input time constant ~10 us, comfortably inside both of Table 4's
   thresholds. Detection runs once every 16 conversions, i.e. roughly every
   1.6 s — a severed thermocouple shows up within about two seconds, not on the
   next read. */
#define MAX31856_CR0_OCFAULT_LOW_Z MAX31856_CR0_OCFAULT0

/* The bits that stay clear are load-bearing:
     CJ_DISABLE       0 keeps the internal cold-junction sensor driving 0Ah/0Bh,
                        rather than turning them into registers an external
                        sensor must write.
     FAULT_INTERRUPT  0 selects comparator mode, in which the SR bits track the
                        live fault state and clear themselves (p. 25). Interrupt
                        mode latches until a FAULTCLR write, which a purely
                        polled driver would never issue.
     FILT_50HZ        0 rejects 60 Hz. See CR0_SETUP below before changing it. */
#define MAX31856_CR0_SETUP (MAX31856_CR0_OCFAULT_LOW_Z)
#define MAX31856_CR0_INIT  (MAX31856_CR0_SETUP | MAX31856_CR0_CMODE)

/* CR0 is written twice on init, and the split is not cosmetic: p. 19 says of
   the notch-filter bit, "Change the notch frequency only while in the 'Normally
   Off' mode - not in the Automatic Conversion mode." Writing CR0_SETUP settles
   the filter and open-circuit bits with CMODE still clear, and only then does
   CR0_INIT start converting. At 60 Hz this is a no-op — the bit is 0 in the
   factory default too — which is exactly why it would otherwise go unnoticed
   until someone selected 50 Hz. */

/* CR1 (p. 20): AVGSEL[2:0] in bits 6:4, TC TYPE[3:0] in bits 3:0.
   4-sample averaging costs (4-1) x 16.67 ms on top of the 82 ms typ / 90 ms max
   auto-mode conversion (pp. 4, 20), so ~132 ms typ and ~140 ms max — still
   inside temp_read_task's 250 ms period, so every poll gets a fresh
   conversion. */
#define MAX31856_CR1_AVG4   0x20
#define MAX31856_CR1_TYPE_K 0x03
#define MAX31856_CR1_INIT   (MAX31856_CR1_AVG4 | MAX31856_CR1_TYPE_K)

/* MASK gates the ~FAULT *pin* only — "masked faults will still result in fault
   bits being set in the Fault Status register" (p. 21) — so nothing this driver
   polls depends on it. Written anyway, at the cost of one transaction, so
   ~FAULT is live for anyone probing the test point. */
#define MAX31856_MASK_INIT 0x00

/* SR fault bits (pp. 25-26). */
#define MAX31856_SR_CJ_RANGE 0x80
#define MAX31856_SR_TC_RANGE 0x40
#define MAX31856_SR_CJHIGH   0x20
#define MAX31856_SR_CJLOW    0x10
#define MAX31856_SR_TCHIGH   0x08
#define MAX31856_SR_TCLOW    0x04
#define MAX31856_SR_OVUV     0x02
#define MAX31856_SR_OPEN     0x01

/* Linearized thermocouple temperature: 19-bit signed in bits [23:5] of the
   three-byte read, LSB 2^-7 C (Table 3 p. 13; LTCBL[4:0] are don't-care). */
static inline float max31856_decode_tc(const uint8_t raw[3])
{
    uint32_t bits = ((uint32_t)raw[0] << 16) | ((uint32_t)raw[1] << 8) | (uint32_t)raw[2];
    int32_t v = (int32_t)((bits >> 5) & 0x7FFFF);
    if (v & 0x40000) {
        v -= 0x80000; /* sign-extend from bit 18 */
    }
    return (float)v / 128.0f;
}

/* Cold junction: 14-bit signed in bits [15:2] of the two-byte read, LSB 2^-6 C
   (Table 2 p. 13; CJTL[1:0] read back as 0). */
static inline float max31856_decode_cj(const uint8_t raw[2])
{
    uint16_t bits = (uint16_t)(((uint16_t)raw[0] << 8) | (uint16_t)raw[1]);
    int32_t v = (int32_t)((bits >> 2) & 0x3FFF);
    if (v & 0x2000) {
        v -= 0x4000; /* sign-extend from bit 13 */
    }
    return (float)v / 64.0f;
}

/* Map SR to the TC_FAULT_* bits the rest of the firmware already handles.
   The MAX31855 distinguished short-to-GND from short-to-VCC; the MAX31856
   does not, so OVUV — an input outside the rails, the same physical failure
   class — is reported as TC_FAULT_SHORT_GND rather than invented as a new
   bit. Adding a bit would mean a contract change in api_json.c and both
   schemas for no diagnostic gain.

   SR's other six bits are deliberately not wiring faults. The four threshold
   bits (CJHIGH/CJLOW/TCHIGH/TCLOW) cannot assert at all while the fault
   thresholds keep their factory values, which this driver never rewrites
   (Table 6, p. 18: +127/-64 C for the cold junction, the full 19-bit range for
   the thermocouple). The two range bits arrive with the reported temperature
   already clamped at the type limit (p. 15), so an out-of-range hot junction
   reaches safety's over-temp cutoff as a 1372 C reading — which is the
   behaviour wanted, without a new fault bit to carry it. */
static inline uint8_t max31856_decode_faults(uint8_t sr)
{
    uint8_t f = 0;
    if (sr & MAX31856_SR_OPEN) {
        f |= TC_FAULT_OPEN_CIRCUIT;
    }
    if (sr & MAX31856_SR_OVUV) {
        f |= TC_FAULT_SHORT_GND;
    }
    return f;
}
