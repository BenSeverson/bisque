# Releasing Bisque

Releases are distributed as [GitHub Releases](https://github.com/BenSeverson/bisque/releases).
Pushing a `v*` git tag triggers `.github/workflows/release.yml`, which builds
the firmware + web UI, stages the flash artifacts, mints Sigstore
build-provenance attestations, and creates a **draft** release for review.

## Versioning

Version is derived entirely from **annotated git tags** of the form
`vMAJOR.MINOR.PATCH` — there is no version constant to edit.

- `scripts/version.sh` runs `git describe --tags --match 'v*'`.
- `CMakeLists.txt` feeds that into ESP-IDF's `PROJECT_VER`, which surfaces at
  runtime via `esp_app_get_description()->version` (boot log and the LCD
  splash screen).

Choosing the bump:

| Bump  | When |
|-------|------|
| PATCH | Bug fixes, no behavior change for a working setup. |
| MINOR | New features, backwards-compatible. |
| MAJOR | Breaking changes to firing behavior, the API, or the flash layout (e.g. `partitions.csv`). |

Pre-releases use an `-rcN` suffix (`v2.1.0-rc1`). The workflow auto-marks any
tag containing `-` as a GitHub pre-release; pre-releases never become
`latest`, so they are **not** served to devices over OTA.

> `web_ui/package.json` has its own static `version` field. It is unused for
> firmware versioning — ignore it.

## Pre-release checklist

1. CI is green on `main`.
2. The commit you will tag is already on `main` (don't tag a branch).
3. Run the [bench smoke test](docs/bench-smoke-test.md) on real hardware —
   it covers what CI can't (SSR clicks, thermocouple reads, history across
   reboot).

## Cutting a release

```bash
git checkout main && git pull
git tag -a vX.Y.Z -m "Bisque vX.Y.Z"
git push origin vX.Y.Z
```

The workflow then:

1. Builds the web UI + firmware (ESP-IDF v6.0.2, target `esp32s3`).
2. Runs `make size` — fails the release if a binary overflows its partition.
3. Stages the flash kit: `bisque-`, `bisque-spiffs-`, `bisque-bootloader-`,
   `bisque-partitions-`, `bisque-otadata-` `.bin`s.
4. Generates the OTA `manifest.json` and `SHA256SUMS`.
5. Mints a Sigstore build-provenance attestation for each binary.
6. Creates a **draft** release with flashing instructions
   (`.github/release-body.md`) plus auto-generated notes from merged PRs.

## Reviewing and publishing

1. Open the draft under [Releases](https://github.com/BenSeverson/bisque/releases).
2. Confirm the assets are present: five `bisque-*.bin` files,
   `manifest.json`, and `SHA256SUMS`.
3. Skim the auto-generated notes; edit if needed.
4. Click **Publish release**.

Devices only pick up new firmware over OTA **after** the draft is published —
the `/releases/latest/download/` URLs don't resolve until then.

## Fixing a bad release

If a problem is found before publishing, or a published release must be
pulled:

1. Delete the release (the draft, or the published one) in the GitHub UI.
2. Delete the tag locally and on the remote:
   ```bash
   git tag -d vX.Y.Z
   git push origin :vX.Y.Z
   ```
3. Fix the issue, then re-tag. Use an `-rcN` tag for trial runs so a broken
   build never lands as `latest`.
