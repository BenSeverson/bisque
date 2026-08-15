/* MAX31856 register decode — conversion maths and fault mapping.
 *
 * The driver itself needs an SPI bus, but everything that can silently
 * miscalibrate a kiln is arithmetic, and arithmetic is host-testable. Most
 * vectors below are the datasheet's *own* table rows (Maxim 19-7534 Rev 0,
 * Table 2 p. 13 for the cold junction, Table 3 p. 13 for the linearized
 * thermocouple reading) rather than values re-derived here, so a sign-extension
 * or shift error fails against Maxim's numbers instead of against a repeat of
 * whatever mistake the implementation made.
 */
#include "unity.h"
#include "max31856_regs.h"

void setUp(void)
{
}
void tearDown(void)
{
}

/* ── Linearized thermocouple: 19-bit signed in bits [23:5], LSB 2^-7 C ──── */

/* Table 3: +25.00 C -> 0000 0001 1001 0000 0000 0000 */
static void test_decode_tc_positive(void)
{
    uint8_t raw[3] = {0x01, 0x90, 0x00};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 25.0f, max31856_decode_tc(raw));
}

/* Table 3: -1.00 C -> 1111 1111 1111 0000 0000 0000 */
static void test_decode_tc_negative(void)
{
    uint8_t raw[3] = {0xFF, 0xF0, 0x00};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, -1.0f, max31856_decode_tc(raw));
}

/* Resolution is the point of this part: one LSB must be 2^-7, not the
   MAX31855's 0.25 C. */
static void test_decode_tc_resolution_is_one_128th(void)
{
    uint8_t raw[3] = {0x00, 0x00, 0x20}; /* value 1 << 5 */
    TEST_ASSERT_FLOAT_WITHIN(0.0001f, 0.0078125f, max31856_decode_tc(raw));
}

/* Table 3, the rows that bracket a kiln's working range and the sign boundary.
   +1600 C is above anything this controller allows but is the datasheet's own
   top row, so it pins the high end of the 19-bit field. */
static void test_decode_tc_datasheet_table_3(void)
{
    struct {
        uint8_t raw[3];
        float expect;
    } cases[] = {
        {{0x64, 0x00, 0x00}, 1600.0f}, {{0x3E, 0x80, 0x00}, 1000.0f}, {{0x06, 0x4F, 0x00}, 100.9375f},
        {{0x00, 0x01, 0x00}, 0.0625f}, {{0x00, 0x00, 0x00}, 0.0f},    {{0xFF, 0xFF, 0x00}, -0.0625f},
        {{0xFF, 0xFC, 0x00}, -0.25f},  {{0xF0, 0x60, 0x00}, -250.0f},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        TEST_ASSERT_FLOAT_WITHIN(0.001f, cases[i].expect, max31856_decode_tc(cases[i].raw));
    }
}

/* LTCBL[4:0] are documented "X" — don't-care bits that are not part of the
   19-bit value. A decoder that shifts by the wrong amount, or masks nothing,
   reads them as temperature. Same reading, garbage in the low five bits. */
static void test_decode_tc_ignores_dont_care_bits(void)
{
    uint8_t clean[3] = {0x01, 0x90, 0x00};
    uint8_t dirty[3] = {0x01, 0x90, 0x1F};
    TEST_ASSERT_EQUAL_FLOAT(max31856_decode_tc(clean), max31856_decode_tc(dirty));
}

/* ── Cold junction: 14-bit signed in bits [15:2], LSB 2^-6 C ─────────────── */

/* Table 2: +25 C -> 0001 1001 0000 0000 */
static void test_decode_cj_positive(void)
{
    uint8_t raw[2] = {0x19, 0x00};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 25.0f, max31856_decode_cj(raw));
}

/* Table 2 in full, including both rails of the sensor's -64..+128 C clamp. */
static void test_decode_cj_datasheet_table_2(void)
{
    struct {
        uint8_t raw[2];
        float expect;
    } cases[] = {
        {{0x7F, 0xFC}, 127.984375f}, {{0x7F, 0x00}, 127.0f},    {{0x7D, 0x00}, 125.0f}, {{0x40, 0x00}, 64.0f},
        {{0x00, 0x80}, 0.5f},        {{0x00, 0x04}, 0.015625f}, {{0x00, 0x00}, 0.0f},   {{0xFF, 0x80}, -0.5f},
        {{0xE7, 0x00}, -25.0f},      {{0xC9, 0x00}, -55.0f},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        TEST_ASSERT_FLOAT_WITHIN(0.001f, cases[i].expect, max31856_decode_cj(cases[i].raw));
    }
}

/* CJTL[1:0] read back as 0 on this part, but a decoder that forgets to shift
   would fold them in. Prove they cannot reach the result. */
static void test_decode_cj_ignores_dont_care_bits(void)
{
    uint8_t clean[2] = {0x19, 0x00};
    uint8_t dirty[2] = {0x19, 0x03};
    TEST_ASSERT_EQUAL_FLOAT(max31856_decode_cj(clean), max31856_decode_cj(dirty));
}

/* ── Fault decode ───────────────────────────────────────────────────────── */

static void test_faults_open_circuit(void)
{
    TEST_ASSERT_EQUAL_UINT8(TC_FAULT_OPEN_CIRCUIT, max31856_decode_faults(MAX31856_SR_OPEN));
}

/* The MAX31855 reported short-to-GND and short-to-VCC separately. The
   MAX31856 has no equivalent pair; OVUV is the closest signal and must map
   to something the existing consumers already understand, or a real fault
   reads as "no fault" to firing_engine. */
static void test_faults_ovuv_maps_to_a_reported_fault(void)
{
    TEST_ASSERT_NOT_EQUAL(0, max31856_decode_faults(MAX31856_SR_OVUV));
}

static void test_faults_none(void)
{
    TEST_ASSERT_EQUAL_UINT8(0, max31856_decode_faults(0x00));
}

/* Both at once — a decoder using `else if` would drop one. */
static void test_faults_open_and_ovuv_combine(void)
{
    uint8_t f = max31856_decode_faults(MAX31856_SR_OPEN | MAX31856_SR_OVUV);
    TEST_ASSERT_BITS_HIGH(TC_FAULT_OPEN_CIRCUIT, f);
    TEST_ASSERT_BITS_HIGH(TC_FAULT_SHORT_GND, f);
}

/* An out-of-range hot junction MUST fault. The reported temperature is clamped
   at the type limit (1372 C for K), which is below APP_HARDWARE_MAX_TEMP_C and
   below any max_safe_temp a user can configure up to it — so safety.c's
   over-temp comparison can never trip on it and the kiln would heat forever at
   a steady, plausible-looking 1372 C. This is the assertion that keeps the only
   remaining stop path (fault -> PID duty 0 -> emergency stop) wired up. */
static void test_faults_tc_out_of_range_is_a_fault(void)
{
    TEST_ASSERT_EQUAL_UINT8(TC_FAULT_OUT_OF_RANGE, max31856_decode_faults(MAX31856_SR_TC_RANGE));
    TEST_ASSERT_NOT_EQUAL(0, max31856_decode_faults(MAX31856_SR_TC_RANGE));
}

/* The four threshold bits cannot assert while the fault thresholds keep the
   factory values this driver never rewrites, and CJ_RANGE clamps the cold
   junction — a bounded bias on the reading, not the unbounded runaway a
   clamped hot junction produces. Assert the deliberate silence, so mapping one
   later is a decision rather than an accident. */
static void test_faults_threshold_and_cj_range_bits_are_not_faults(void)
{
    TEST_ASSERT_EQUAL_UINT8(0, max31856_decode_faults(MAX31856_SR_TCLOW));
    TEST_ASSERT_EQUAL_UINT8(0, max31856_decode_faults(MAX31856_SR_TCHIGH));
    TEST_ASSERT_EQUAL_UINT8(0, max31856_decode_faults(MAX31856_SR_CJLOW));
    TEST_ASSERT_EQUAL_UINT8(0, max31856_decode_faults(MAX31856_SR_CJHIGH));
    TEST_ASSERT_EQUAL_UINT8(0, max31856_decode_faults(MAX31856_SR_CJ_RANGE));
}

/* Every mapped fault bit must be distinct — reusing a value would make an
   over-range kiln report as a wiring fault in the UI during the one event
   where the operator most needs to know which it is. */
static void test_fault_bits_are_distinct(void)
{
    TEST_ASSERT_EQUAL_UINT8(0, TC_FAULT_OPEN_CIRCUIT & TC_FAULT_SHORT_GND);
    TEST_ASSERT_EQUAL_UINT8(0, TC_FAULT_OPEN_CIRCUIT & TC_FAULT_OUT_OF_RANGE);
    TEST_ASSERT_EQUAL_UINT8(0, TC_FAULT_SHORT_GND & TC_FAULT_OUT_OF_RANGE);
    TEST_ASSERT_EQUAL_UINT8(0, TC_FAULT_SHORT_VCC & TC_FAULT_OUT_OF_RANGE);
}

/* ── Config-register encoding ───────────────────────────────────────────── */

/* Table 6 p. 18: reads use 0Xh, writes 8Xh. Getting this backwards makes every
   read return the previous write's echo and every write land nowhere. */
static void test_write_bit_is_the_msb(void)
{
    TEST_ASSERT_EQUAL_HEX8(0x80, MAX31856_REG_CR0 | MAX31856_WRITE_BIT);
    TEST_ASSERT_EQUAL_HEX8(0x8F, MAX31856_REG_SR | MAX31856_WRITE_BIT);
}

/* CR0 p. 19. The two bits that are deliberately *clear* matter as much as the
   ones that are set: bit 3 (CJ) clear keeps the internal cold-junction sensor
   enabled, and bit 2 (FAULT) clear selects comparator mode, in which SR bits
   self-clear — which is the only reason a polled driver needs no fault-clear
   write. Set either one and the driver is quietly wrong, not broken. */
static void test_cr0_init_bits(void)
{
    TEST_ASSERT_BITS_HIGH(MAX31856_CR0_CMODE, MAX31856_CR0_INIT);
    TEST_ASSERT_BITS_HIGH(MAX31856_CR0_OCFAULT0, MAX31856_CR0_INIT);
    TEST_ASSERT_BITS_LOW(MAX31856_CR0_1SHOT, MAX31856_CR0_INIT);
    TEST_ASSERT_BITS_LOW(MAX31856_CR0_OCFAULT1, MAX31856_CR0_INIT);
    TEST_ASSERT_BITS_LOW(MAX31856_CR0_CJ_DISABLE, MAX31856_CR0_INIT);
    TEST_ASSERT_BITS_LOW(MAX31856_CR0_FAULT_INTERRUPT, MAX31856_CR0_INIT);
    TEST_ASSERT_BITS_LOW(MAX31856_CR0_FAULTCLR, MAX31856_CR0_INIT);
    /* 60 Hz mains: the filter bit selects 50 Hz when set. */
    TEST_ASSERT_BITS_LOW(MAX31856_CR0_FILT_50HZ, MAX31856_CR0_INIT);
}

/* OCFAULT[1:0] = 01 is Table 4's "R_S < 5 kOhm" bucket, which is what the rev B
   front end (100 Ohm series, 100 nF differential) sits in. The value is 0x10 —
   bit 4, OCFAULT0 — and the neighbouring bit 5 must stay clear or the part
   switches to the slow 40 kOhm > R_S > 5 kOhm timing. */
static void test_ocfault_selects_the_low_impedance_mode(void)
{
    TEST_ASSERT_EQUAL_HEX8(0x10, MAX31856_CR0_OCFAULT0);
    TEST_ASSERT_EQUAL_HEX8(0x20, MAX31856_CR0_OCFAULT1);
    TEST_ASSERT_EQUAL_HEX8(0x10, MAX31856_CR0_INIT & 0x30);
}

/* The setup write is CR0_INIT minus CMODE, and nothing else. The datasheet
   forbids changing the notch frequency in auto-conversion mode, so the driver
   writes CR0 twice; if these two ever diverge by more than CMODE, the second
   write would change a setting mid-conversion. */
static void test_cr0_setup_is_init_without_cmode(void)
{
    TEST_ASSERT_BITS_LOW(MAX31856_CR0_CMODE, MAX31856_CR0_SETUP);
    TEST_ASSERT_EQUAL_HEX8(MAX31856_CR0_INIT, MAX31856_CR0_SETUP | MAX31856_CR0_CMODE);
}

/* CR1 p. 20: AVGSEL[2:0] in bits 6:4, TC TYPE[3:0] in bits 3:0. K type is
   0011. Fitting a K-type probe and configuring, say, J silently rescales
   every reading. */
static void test_cr1_init_selects_k_type_and_4_sample_averaging(void)
{
    TEST_ASSERT_EQUAL_HEX8(0x03, MAX31856_CR1_INIT & 0x0F);
    TEST_ASSERT_EQUAL_HEX8(0x20, MAX31856_CR1_INIT & 0x70);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_decode_tc_positive);
    RUN_TEST(test_decode_tc_negative);
    RUN_TEST(test_decode_tc_resolution_is_one_128th);
    RUN_TEST(test_decode_tc_datasheet_table_3);
    RUN_TEST(test_decode_tc_ignores_dont_care_bits);
    RUN_TEST(test_decode_cj_positive);
    RUN_TEST(test_decode_cj_datasheet_table_2);
    RUN_TEST(test_decode_cj_ignores_dont_care_bits);
    RUN_TEST(test_faults_open_circuit);
    RUN_TEST(test_faults_ovuv_maps_to_a_reported_fault);
    RUN_TEST(test_faults_none);
    RUN_TEST(test_faults_open_and_ovuv_combine);
    RUN_TEST(test_faults_tc_out_of_range_is_a_fault);
    RUN_TEST(test_faults_threshold_and_cj_range_bits_are_not_faults);
    RUN_TEST(test_fault_bits_are_distinct);
    RUN_TEST(test_write_bit_is_the_msb);
    RUN_TEST(test_cr0_init_bits);
    RUN_TEST(test_ocfault_selects_the_low_impedance_mode);
    RUN_TEST(test_cr0_setup_is_init_without_cmode);
    RUN_TEST(test_cr1_init_selects_k_type_and_4_sample_averaging);
    return UNITY_END();
}
