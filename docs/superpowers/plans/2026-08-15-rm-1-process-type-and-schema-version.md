# RM-1: `process_type` + `schema_version` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `process_type` and `schema_version` to `firing_profile_t` end to end, with an NVS load path that is deterministic rather than accidentally correct.

**Architecture:** Two appended `uint8_t` fields, both past the end of any legacy blob. The load path gains a `memset` before `nvs_get_blob`; the save path gains a `memset` and a version stamp. `schema_version` does nothing visible in this task — it exists so RM-5 can safely put fields into `firing_segment_t`'s tail padding, which no amount of zero-filling the destination can protect.

**Tech Stack:** ESP-IDF NVS, cJSON, zod, Swift `Codable`, Unity host tests.

**Issue:** [#319](https://github.com/BenSeverson/bisque/issues/319)

**Spec:** [`docs/heat-treating-extension-plan.md`](../../heat-treating-extension-plan.md) §3.1 — read it before starting; it contains the measured struct layout this plan relies on.

## Global Constraints

- **`PROCESS_CERAMIC = 0`.** Zero must mean today's behaviour, because that is what a legacy profile will deserialize to.
- **The version stamp goes on the save path, not just the load path.** `profile_from_json()` starts with `memset(out, 0, sizeof(*out))` (`api_handlers.c:248`), so **every profile arriving over REST or import carries `schema_version == 0`**. Stamping only on load means a Phase 2 profile persists as version 0 and its next load runs the legacy migration, silently wiping the fields the user just set. The version describes *the layout being written*, which only the writer knows.
- **This is a contract change.** A new firmware field fails the web contract test until the zod schema models it — that is the test doing its job, not a break to work around. `api_json.c`, both schemas in `web_ui/src/app/schemas/`, both Swift models, and `make fixtures` all move together.
- `firing_cmd_t` carries a profile **by value** through a 4-deep queue; `firing_profile_t` is already ~1.83 KB, so the queue reserves ~7.3 KB. Two bytes is nothing, but re-check the figure rather than assuming it.
- After editing any firmware C/H file, run `clang-format -i` on it.

## File Structure

| File | Responsibility |
|---|---|
| `components/firing_engine/include/firing_engine.h` | `process_type_t`, the two fields, `FIRING_SCHEMA_VERSION` |
| `components/firing_engine/firing_engine.c` | Deterministic save/load |
| `components/web_server/api_json.c` | Serialize both fields |
| `components/web_server/api_handlers.c` | Parse `processType` |
| `web_ui/src/app/schemas/kiln.ts`, `api.ts` | zod, and therefore the TS types |
| `ios/Bisque/.../` models | Swift `Codable` |
| `tests/host/test_firing_profile_nvs.c` (new) | The round-trip tests, including the hostile case |

---

### Task 1: The struct and the version constant

**Files:**
- Modify: `components/firing_engine/include/firing_engine.h`

**Interfaces:**
- Produces: `process_type_t`, `FIRING_SCHEMA_VERSION`, and the two new `firing_profile_t` fields. Every later task consumes them.

- [ ] **Step 1: Add the enum and constant**

```c
typedef enum {
    PROCESS_CERAMIC = 0,   /* zero = legacy default; see the NVS note below */
    PROCESS_HEAT_TREAT,    /* metals: anneal / temper / harden / stress-relieve */
    PROCESS_GLASS,         /* glass annealing / slumping */
} process_type_t;

/* Persisted layout version for firing_profile_t.
 *
 * 0 = pre-versioning blob written before RM-1.
 * 1 = this layout.
 *
 * Bump this whenever a new field lands in bytes that were previously
 * indeterminate padding, and add a migration step in the loader. Appending
 * past the end of the struct does NOT need a bump — nvs_get_blob simply
 * never writes those bytes, so the loader's memset covers them. */
#define FIRING_SCHEMA_VERSION 1
```

- [ ] **Step 2: Append the fields to `firing_profile_t`**

Append at the **end** of the struct, never in the middle:

```c
    uint8_t process_type;    /* process_type_t; 0 = PROCESS_CERAMIC = legacy */
    uint8_t schema_version;  /* FIRING_SCHEMA_VERSION; 0 = legacy blob */
```

- [ ] **Step 3: Record the size before and after**

```bash
grep -rn "sizeof(firing_profile_t)" components tests | head
```

Note the old and new `sizeof` in the commit message. A later reader needs to know whether the struct grew or absorbed padding — the answer changes whether a migration is required.

---

### Task 2: Make the NVS path deterministic

**Files:**
- Modify: `components/firing_engine/firing_engine.c`

- [ ] **Step 1: Write the failing tests first**

Create `tests/host/test_firing_profile_nvs.c` covering the three cases the spec calls out. The hostile one is the point:

```c
/* A legacy blob whose tail padding was 0xFF, not 0x00. Padding is
   indeterminate — nvs_set_blob writes sizeof bytes straight from the
   struct, padding included — so this is a real profile, not a contrived
   one. It must load with the appended fields zeroed. */
static void test_legacy_blob_with_dirty_padding_loads_as_ceramic(void)
{
    uint8_t blob[LEGACY_PROFILE_SIZE];
    memset(blob, 0xFF, sizeof(blob));
    populate_legacy_profile_fields(blob);   /* helper: valid name/segments */

    firing_profile_t p;
    TEST_ASSERT_EQUAL(ESP_OK, load_profile_from_blob(blob, sizeof(blob), &p));
    TEST_ASSERT_EQUAL_UINT8(PROCESS_CERAMIC, p.process_type);
    TEST_ASSERT_EQUAL_UINT8(0, p.schema_version);
}

/* The regression test for an unstamped save. Without the save-path stamp
   this passes on the first load and fails on the second. */
static void test_saved_profile_round_trips_with_its_version(void)
{
    firing_profile_t in = valid_profile();
    in.process_type = PROCESS_HEAT_TREAT;

    uint8_t blob[sizeof(firing_profile_t)];
    TEST_ASSERT_EQUAL(ESP_OK, save_profile_to_blob(&in, blob, sizeof(blob)));

    firing_profile_t out;
    TEST_ASSERT_EQUAL(ESP_OK, load_profile_from_blob(blob, sizeof(blob), &out));
    TEST_ASSERT_EQUAL_UINT8(PROCESS_HEAT_TREAT, out.process_type);
    TEST_ASSERT_EQUAL_UINT8(FIRING_SCHEMA_VERSION, out.schema_version);
}

/* A blob larger than the struct means the device was downgraded from newer
   firmware. Truncating silently would drop fields the user set; refuse. */
static void test_oversized_blob_is_an_error(void)
{
    uint8_t blob[sizeof(firing_profile_t) + 8];
    memset(blob, 0, sizeof(blob));
    firing_profile_t p;
    TEST_ASSERT_NOT_EQUAL(ESP_OK, load_profile_from_blob(blob, sizeof(blob), &p));
}
```

**These tests need the blob logic reachable from the host.** `firing_engine_load_profile()` calls `nvs_get_blob` directly, which the host harness cannot. Extract the decision — zero, copy, migrate, validate — into a pure function in `firing_engine.c` or a small `profile_blob.h` beside it, taking a buffer and a length, exactly as `log_sink.c` was split out of `device_log.c`. **Do that extraction as part of this step**, and let the NVS call sites become thin wrappers.

- [ ] **Step 2: Run them and confirm they fail**

```bash
make test-host
```

- [ ] **Step 3: Implement the load path**

```c
    /* nvs_get_blob writes only as many bytes as the stored blob holds, and
       the caller often hands us an uninitialized stack struct. Without this
       memset, a legacy blob leaves process_type and schema_version as
       whatever was on the stack — randomly classifying old ceramic profiles
       and applying the wrong vent and safety policy. */
    memset(profile, 0, sizeof(*profile));
```

then, after the copy:

```c
    if (stored_len > sizeof(*profile)) {
        return ESP_ERR_INVALID_SIZE;  /* downgrade: refuse rather than truncate */
    }
    if (profile->schema_version == 0) {
        /* Legacy blob. Nothing to migrate yet — RM-5 adds the segment-field
           migration here when hold_tolerance_c and flags land in padding. */
        profile->schema_version = FIRING_SCHEMA_VERSION;
    }
```

- [ ] **Step 4: Implement the save path**

In `firing_engine_save_profile()`, on the canonical copy it writes:

```c
    /* Zero first so padding written from here on is deterministic; without
       this the same indeterminate-padding bug recurs at the next schema
       bump. */
    memset(&to_store, 0, sizeof(to_store));
    to_store = *profile;
    to_store.schema_version = FIRING_SCHEMA_VERSION;
```

> Note the ordering trap: `memset` then struct-assign re-copies the source's padding. If the source came from `profile_from_json()` its padding is already zeroed; if it came from a caller's stack it is not. Assign field-by-field, or `memset` the *destination after* assignment for the padding bytes you care about. Decide which, and write down why in the code.

- [ ] **Step 5: Run, format, commit**

```bash
make test-host && clang-format -i components/firing_engine/firing_engine.c
git add components/firing_engine/ tests/host/
git commit -m "feat(profiles): version the persisted layout, and mean it

Adds process_type and schema_version, both appended past the end of a
legacy blob so nvs_get_blob never writes them and a memset on the
destination makes them reliably zero.

The stamp goes on the SAVE path, which is the part that is easy to skip
and expensive to skip: profile_from_json() memsets its output, so every
profile arriving over REST or import carries schema_version 0. Stamping
only on load would persist Phase 2 profiles as version 0 and let their
next load run the legacy migration over the fields the user just set.

An oversized blob is refused rather than truncated — that is a downgrade
from newer firmware, and silently dropping fields is worse than failing.

The blob decision is extracted so the host suite can drive it, including
the case that matters: a legacy blob whose padding was 0xFF.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Carry it through the API contract

**Files:**
- Modify: `components/web_server/api_json.c`, `components/web_server/api_handlers.c`
- Modify: `web_ui/src/app/schemas/kiln.ts` (and `api.ts` if profiles appear in a response shape)
- Modify: the iOS `Codable` profile model
- Modify: `tests/host/fixture_sources.txt` if a new source feeds a `build_*_json()`

- [ ] **Step 1: Emit the field**

In `build_profile_json()` (or whichever `build_*_json()` owns profiles), add `processType`. Do **not** emit `schema_version` — it is a storage detail, and putting it on the wire invites a client to set it.

- [ ] **Step 2: Parse it**

In `profile_from_json()`, read `processType`, defaulting to `PROCESS_CERAMIC` when absent so older clients keep working. Reject values outside the enum rather than storing them.

- [ ] **Step 3: Regenerate fixtures and watch the contract test fail**

```bash
make fixtures
make test-web
```

Expected: **failure.** The contract suite rebuilds each schema `.strict()`, so a new firmware field is an error until the schema models it. That is the design.

- [ ] **Step 4: Model it in zod**

Add `processType` to the profile schema in `web_ui/src/app/schemas/kiln.ts`. The TS types are `z.infer`red, so `FiringProfile` follows automatically and every call site that no longer matches fails `npm run typecheck`.

- [ ] **Step 5: Model it in Swift**

Add the property to the iOS profile model. `FirmwareContractTests` has three tables that must stay honest — `decoded`, `notModelled`, `knownUnmodelled` — and a new fixture field fails until it lands in one of them.

- [ ] **Step 6: Full verification**

```bash
make test          # host + web
make test-ios      # macOS only
make lint
```

- [ ] **Step 7: Commit**

```bash
git add components/web_server/ web_ui/src/app/schemas/ ios/ tests/
git commit -m "feat(api): carry processType across the firmware contract

Adds processType to the profile payload, the zod schema and the Swift
model together, because the contract test fails on a firmware field no
schema models — which is the test working, not a break to route around.

schema_version deliberately stays off the wire: it describes how the blob
is stored, and exposing it invites a client to set it.

An absent processType parses as PROCESS_CERAMIC so older clients keep
working; out-of-range values are rejected rather than stored.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Close the loop

- [ ] **Step 1: Confirm the mock server agrees**

`web_ui/mock-server/` serves the same shapes. A profile it returns without `processType` will now fail the app's own parsing in dev. Add it there and to the demo simulator.

- [ ] **Step 2: Verify the demo still builds**

```bash
make web-demo
```

The demo's dynamic import is tree-shaken out of every non-demo bundle, so `npm run build` cannot catch a break in it — this target is the only thing that does.

- [ ] **Step 3: Close the issue**

Close [#319](https://github.com/BenSeverson/bisque/issues/319), noting the old and new `sizeof(firing_profile_t)`. RM-2, RM-3 and RM-4 unblock from here, and so does the entire Tier A application list.
