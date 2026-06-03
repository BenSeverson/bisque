import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { kilnMockPlugin } from './mock-server/plugin'

// The demo build (BISQUE_DEMO=true) produces a self-contained static bundle for
// GitHub Pages at https://benseverson.github.io/bisque/ — it bundles the kiln
// simulator (gated on __DEMO__) and writes to ./dist instead of the firmware's
// SPIFFS directory. The normal build is unaffected.
const isDemo = process.env.BISQUE_DEMO === 'true'

export default defineConfig({
  base: isDemo ? '/bisque/' : '/',
  define: {
    __APP_VERSION__: JSON.stringify(process.env.BISQUE_VERSION ?? '0.0.0-dev'),
    __DEMO__: JSON.stringify(isDemo),
  },
  plugins: [
    kilnMockPlugin(),
    // The React and Tailwind plugins are both required for Make, even if
    // Tailwind is not being actively used – do not remove them
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: isDemo ? 'dist' : '../spiffs_data/www',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://192.168.4.1',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
