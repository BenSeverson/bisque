## Installing this release

Each release ships the full flash kit for an ESP32-S3 (N16R8, 16 MB). Replace
`<ver>` with this release's tag in the filenames below.

### First-time flash (blank board)

Writes every partition. Requires [esptool](https://docs.espressif.com/projects/esptool/):

```bash
esptool --chip esp32s3 write-flash \
  0x0      bisque-bootloader-<ver>.bin \
  0x8000   bisque-partitions-<ver>.bin \
  0x18000  bisque-otadata-<ver>.bin \
  0x20000  bisque-<ver>.bin \
  0x820000 bisque-spiffs-<ver>.bin
```

### Update an already-provisioned board

- **Over the air:** the device pulls new firmware automatically once this
  release is published (it polls the release `manifest.json`).
- **Over USB (app only):** `esptool --chip esp32s3 write-flash 0x20000 bisque-<ver>.bin`
- If the web dashboard changed, also reflash SPIFFS:
  `esptool --chip esp32s3 write-flash 0x820000 bisque-spiffs-<ver>.bin`

## Verifying the download

Integrity:

```bash
sha256sum -c SHA256SUMS
```

Provenance — every `.bin` carries a Sigstore build-provenance attestation:

```bash
gh attestation verify bisque-<ver>.bin --repo BenSeverson/bisque
```

---
