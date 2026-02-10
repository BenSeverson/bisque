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
