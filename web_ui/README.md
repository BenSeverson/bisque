# Kiln Controller Web Panel

Web dashboard for the Bisque kiln controller. Built with React, Tailwind CSS, and Recharts.

The original design is available at https://www.figma.com/design/RPySfhiIONMDto2aIROkUA/Kiln-Controller-Web-Panel.

## Development

```bash
npm install
npm run dev
```

This starts a Vite dev server with the mock kiln server enabled by default. The mock simulates the full kiln API including firing physics, WebSocket temperature broadcasts, profiles, settings, history, and diagnostics.

### Mock server options

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_MOCK` | `true` | Set to `false` to disable the mock and proxy to a real kiln at `192.168.4.1` |
| `VITE_MOCK_SPEED` | `60` | Simulation speed multiplier (e.g. `120` = 120x real-time) |

```bash
# Use real kiln
VITE_MOCK=false npm run dev

# Faster simulation
VITE_MOCK_SPEED=120 npm run dev
```

### Standalone mock server (for iOS app testing)

The mock server can also run standalone, outside of Vite, for testing the iOS app in the Xcode simulator:

```bash
npm run mock-server
```

This starts an HTTP + WebSocket server on `localhost:8080`. The iOS simulator connection screen has a shortcut button to connect to it.

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_PORT` | `8080` | Server port |
| `MOCK_SPEED` | `60` | Simulation speed multiplier |

## Production build

```bash
npm run build
```

Output goes to `../spiffs_data/www/` for flashing onto the ESP32.

## Other commands

```bash
npm run lint          # ESLint
npm run lint:fix      # ESLint with auto-fix
npm run typecheck     # TypeScript type checking
```
