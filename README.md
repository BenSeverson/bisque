# Bisque

ESP32-S3 firmware for ceramic kiln control with PID temperature regulation, web UI, and safety systems.

## Hardware Wiring

### SPI Bus (shared by thermocouple and display)

| Signal | ESP32-S3 GPIO |
|--------|---------------|
| MOSI   | 11            |
| MISO   | 13            |
| SCLK   | 12            |

### MAX31855 Thermocouple

| Signal | ESP32-S3 GPIO |
|--------|---------------|
| CS     | 10            |

### ST7735 LCD Display

| LCD Pin | ESP32-S3 GPIO | Notes |
|---------|---------------|-------|
| SDA     | 11            | SPI MOSI (data to display) |
| SCL     | 12            | SPI clock |
| CS      | 9             | Chip select |
| DC      | 46            | Data/Command |
| RST     | 3             | Reset |
| BL      | 8             | Backlight |

### SSR Output

| Signal | ESP32-S3 GPIO |
|--------|---------------|
| SSR    | 4             |

## Building

```bash
# Build web UI
cd web_ui && npm install && npm run build && cd ..

# Gzip assets
gzip -k -9 spiffs_data/www/assets/*.js spiffs_data/www/assets/*.css

# Build firmware
source ~/.espressif/v5.5.2/esp-idf/export.sh
idf.py build

# Flash
idf.py flash
```

## Simulator / Mock Server

A mock kiln server simulates the full API (status, profiles, firing, settings, history, autotune, diagnostics) with realistic temperature physics so you can develop and test without hardware.

### Web UI development

The mock server runs automatically as a Vite plugin when you start the web UI dev server:

```bash
cd web_ui
npm run dev
```

The mock is enabled by default. To disable it and proxy to a real kiln instead:

```bash
VITE_MOCK=false npm run dev
```

Control simulation speed with `VITE_MOCK_SPEED` (default `60` = 60x real-time):

```bash
VITE_MOCK_SPEED=120 npm run dev
```

### iOS app development

A standalone mock server is available for testing the iOS app in the Xcode simulator:

```bash
cd web_ui
npm run mock-server
```

This starts an HTTP + WebSocket server on `localhost:8080`. In the iOS simulator, the connection screen shows a "Use Mock Server" button that auto-fills `localhost:8080`.

To change the port or simulation speed:

```bash
MOCK_PORT=9000 MOCK_SPEED=120 npm run mock-server
```

### iOS project setup

The iOS project uses [XcodeGen](https://github.com/yonaskolb/XcodeGen). After modifying `ios/Bisque/project.yml`, regenerate the Xcode project:

```bash
cd ios/Bisque
xcodegen generate
```
