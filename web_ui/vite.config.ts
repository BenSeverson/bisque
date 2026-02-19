import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { kilnMockPlugin } from './mock-server/plugin'

export default defineConfig({
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
    outDir: '../spiffs_data/www',
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
