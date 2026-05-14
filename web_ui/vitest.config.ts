import { defineConfig } from "vitest/config";
import path from "path";

// Tests don't need Vite plugins (React, Tailwind) or the mock-server. Keeping
// vitest's config separate from vite.config.ts avoids spinning up the kiln
// mock server inside every `vitest run`.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.{ts,tsx}", "mock-server/**/*.test.ts"],
  },
});
