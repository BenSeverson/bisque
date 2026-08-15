# RM-5: Segment Fields + Padding Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `hold_tolerance_c` and `flags` to `firing_segment_t` — into its existing tail padding — with the migration that makes that safe.

**Architecture:** Both fields land at offsets 98–99, which today are padding. The struct stays 100 bytes, so a legacy blob is *byte-for-byte the same length* and `nvs_get_blob` copies all 100 bytes per segment, overwriting any zero-fill with whatever the padding held when the profile was saved. Zeroing the destination cannot help. RM-1's `schema_version` is what makes this tractable: on load, a version-0 profile has these bytes explicitly cleared across all segments.

**Tech Stack:** ESP-IDF NVS, cJSON, zod, Swift `Codable`, Unity host tests.

**Issue:** [#323](https://github.com/BenSeverson/bisque/issues/323) · **Hard dependency: [RM-1 #319](https://github.com/BenSeverson/bisque/issues/319)**

**Spec:** [`docs/heat-treating-extension-plan.md`](../../heat-treating-extension-plan.md) §3.2 and the padding analysis in §3.1.

## Global Constraints

- **Do not start this without RM-1 merged.** The spec says so explicitly and it is not a sequencing preference: without `schema_version` there is no way to distinguish a legacy blob's indeterminate padding from a deliberate `hold_tolerance_c = 30`. An old profile would come back with guaranteed soak, natural cooling, or a quench alert silently enabled — on a kiln.
- **The failure mode is silent and physical.** `SEG_FLAG_NATURAL_COOL` set by stale padding forces the SSR off mid-firing; `SEG_FLAG_ALERT_ON_COMPLETE` fires an alarm and a webhook. Neither looks like a bug at first glance. This is why the hostile test is mandatory, not thorough.
- Verify the measured layout before relying on it. The spec states `id[40]`, `name[48]`, `ramp_rate` @88, `target_temp` @92, `hold_time` @96–97, padding @98–99, `sizeof == 100`. **Confirm it on this compiler** — Task 1 exists for that.
- `hold_tolerance_c == 0` must mean today's behaviour: the hold timer runs once the target is reached.
- After editing any firmware C/H file, run `clang-format -i` on it.

## File Structure

| File | Responsibility |
|---|---|
| `components/firing_engine/include/firing_engine.h` | The two fields, `SEG_FLAG_*` |
| `components/firing_engine/firing_engine.c` (or `profile_blob.h` from RM-1) | The version-0 migration |
| `tests/host/test_firing_profile_nvs.c` | Extend with the hostile segment case |
| `api_json.c`, `api_handlers.c`, zod schemas, Swift models, mock server | Contract |

---

### Task 1: Confirm the layout before trusting it

**Files:**
- Create (temporarily): a static-assert or a one-off host test

- [ ] **Step 1: Assert the current layout**

Add to `tests/host/test_firing_profile_nvs.c`:

```c
/* The migration below is only correct if these two fields land in bytes a
   legacy blob already occupied. If sizeof changes when they are added, they
   went past the end instead — which is SAFER (RM-1's memset covers it) but
   makes the migration dead code that will mislead the next reader. Either
   way, know which happened. */
static void test_segment_layout_is_as_the_spec_measured(void)
{
    TEST_ASSERT_EQUAL_UINT(100, sizeof(firing_segment_t));
    TEST_ASSERT_EQUAL_UINT(88, offsetof(firing_segment_t, ramp_rate));
    TEST_ASSERT_EQUAL_UINT(92, offsetof(firing_segment_t, target_temp));
    TEST_ASSERT_EQUAL_UINT(96, offsetof(firing_segment_t, hold_time));
}
```

- [ ] **Step 2: Run it**

```bash
make test-host
```

**If any assertion fails, stop and re-measure.** Update this plan with the real layout before continuing — every decision below depends on it.

---

### Task 2: Add the fields and the migration

**Files:**
- Modify: `components/firing_engine/include/firing_engine.h`
- Modify: the blob loader extracted in RM-1

**Interfaces:**
- Produces: `SEG_FLAG_NATURAL_COOL`, `SEG_FLAG_ALERT_ON_COMPLETE`, and the two segment fields. RM-6, RM-7 and RM-8 consume them.

- [ ] **Step 1: Write the hostile test first**

```c
/* The whole reason RM-1 exists. A version-0 profile whose segment padding
   was 0xFF must load with both fields cleared — otherwise it comes back
   with natural cooling and a quench alert enabled on every segment, which
   turns the SSR off mid-firing and fires the alarm, and looks like a
   hardware fault rather than a deserialization bug. */
static void test_legacy_segment_padding_does_not_become_flags(void)
{
    uint8_t blob[LEGACY_PROFILE_SIZE];
    memset(blob, 0xFF, sizeof(blob));
    populate_legacy_profile_fields(blob);
    set_blob_schema_version(blob, 0);

    firing_profile_t p;
    TEST_ASSERT_EQUAL(ESP_OK, load_profile_from_blob(blob, sizeof(blob), &p));

    for (int i = 0; i < FIRING_MAX_SEGMENTS; i++) {
        TEST_ASSERT_EQUAL_UINT8(0, p.segments[i].hold_tolerance_c);
        TEST_ASSERT_EQUAL_UINT8(0, p.segments[i].flags);
    }
}

/* And the other half: a current-version profile must keep what it set. A
   migration that clears unconditionally passes the test above and destroys
   real data. */
static void test_current_version_profile_keeps_its_segment_fields(void)
{
    firing_profile_t in = valid_profile();
    in.segments[0].hold_tolerance_c = 5;
    in.segments[0].flags = SEG_FLAG_NATURAL_COOL;

    uint8_t blob[sizeof(firing_profile_t)];
    TEST_ASSERT_EQUAL(ESP_OK, save_profile_to_blob(&in, blob, sizeof(blob)));

    firing_profile_t out;
    TEST_ASSERT_EQUAL(ESP_OK, load_profile_from_blob(blob, sizeof(blob), &out));
    TEST_ASSERT_EQUAL_UINT8(5, out.segments[0].hold_tolerance_c);
    TEST_ASSERT_EQUAL_UINT8(SEG_FLAG_NATURAL_COOL, out.segments[0].flags);
}
```

- [ ] **Step 2: Run and confirm both fail**

```bash
make test-host
```

- [ ] **Step 3: Add the fields**

```c
/* Segment flags. */
#define SEG_FLAG_NATURAL_COOL      (1 << 0) /* SSR forced off; segment completes
                                               when temp <= target_temp.
                                               ramp_rate is ignored. */
#define SEG_FLAG_ALERT_ON_COMPLETE (1 << 1) /* alarm + webhook on completion
                                               ("quench now") */
```

and, appended to `firing_segment_t`:

```c
    uint8_t hold_tolerance_c; /* 0 = legacy: the hold timer runs once the target
                                 is reached. N = guaranteed soak: the clock only
                                 counts while |temp - target| <= N. */
    uint8_t flags;            /* SEG_FLAG_* */
```

- [ ] **Step 4: Implement the migration**

In the loader, where RM-1 left the placeholder:

```c
    if (profile->schema_version == 0) {
        /* These two fields occupy bytes 98-99 of firing_segment_t, which
           were tail padding before RM-5. sizeof did not change, so a legacy
           blob is the same length and nvs_get_blob copied all 100 bytes per
           segment — including whatever the padding happened to hold when the
           profile was saved. nvs_set_blob writes sizeof bytes straight from
           the struct, padding included, so those bytes are indeterminate,
           not zero. Clearing them explicitly is the only correct move. */
        for (int i = 0; i < FIRING_MAX_SEGMENTS; i++) {
            profile->segments[i].hold_tolerance_c = 0;
            profile->segments[i].flags = 0;
        }
        profile->schema_version = FIRING_SCHEMA_VERSION;
    }
```

- [ ] **Step 5: Confirm the layout assertion still holds**

Re-run Task 1's test. If `sizeof(firing_segment_t)` is now 102 rather than 100, the fields went past the end instead of into padding — the migration is then harmless but misleading, and the comment above is wrong. Fix the comment; do not delete the migration (a mixed fleet may still hold blobs written either way).

- [ ] **Step 6: Run, format, commit**

```bash
make test-host && clang-format -i components/firing_engine/
git add components/firing_engine/ tests/host/
git commit -m "feat(profiles): put soak tolerance and flags in padding, safely

hold_tolerance_c and flags land at bytes 98-99 of firing_segment_t, which
were tail padding. sizeof does not change, so a legacy blob is the same
length and nvs_get_blob copies all 100 bytes per segment — zero-filling
the destination cannot help, because the copy overwrites it with whatever
the padding held at save time. nvs_set_blob writes padding straight from
the struct, so that is indeterminate rather than zero.

RM-1's schema_version is what makes this tractable: a version-0 profile
has both fields cleared across all segments on load.

The test that matters uses 0xFF padding, because the failure is silent
and physical — stale bits would enable natural cooling and a quench alert
on every segment, turning the SSR off mid-firing and firing the alarm,
presenting as a hardware fault.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Carry the fields through the contract

**Files:** `api_json.c`, `api_handlers.c`, `web_ui/src/app/schemas/kiln.ts`, iOS models, `web_ui/mock-server/`

- [ ] **Step 1: Serialize and parse**

Add `holdToleranceC` and the flags to the segment payload. Prefer **named booleans** on the wire (`naturalCool`, `alertOnComplete`) over a numeric bitfield: a bitfield forces every client to know the bit positions, and the zod schema cannot validate it meaningfully.

- [ ] **Step 2: Regenerate fixtures, watch the contract fail, then model it**

```bash
make fixtures && make test-web
```

Expected: failure until the zod schema models the new fields — by design. Then add them to `kiln.ts`, let the TS types follow, and fix whatever `npm run typecheck` surfaces.

- [ ] **Step 3: Swift and mock server**

Add to the iOS `Codable` segment model and to `web_ui/mock-server/` so dev and demo agree.

- [ ] **Step 4: Verify everything**

```bash
make test && make web-demo && make lint
make test-ios   # macOS only
```

- [ ] **Step 5: Commit and close**

Close [#323](https://github.com/BenSeverson/bisque/issues/323). RM-6 (guaranteed soak), RM-7 (natural cool) and RM-8 (alerts) all unblock from here — they are the consumers of these two bytes.
