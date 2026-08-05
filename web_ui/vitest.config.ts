import { defineConfig } from "vitest/config";
import path from "path";

// Tests don't need Vite plugins (React, Tailwind) or the mock-server. Keeping
// vitest's config separate from vite.config.ts avoids spinning up the kiln
// mock server inside every `vitest run`.
//
// Split into two projects purely to scope the environment. mock-server/ and
// test/ model non-browser consumers — the node mock server and the firmware
// JSON contract — so running them under jsdom lets them lean on a DOM global
// their real callers don't have and still pass. (The wall-clock saving from
// skipping jsdom is in the noise at this suite size; the isolation is the
// point.) Scoping by directory rather than a per-file `@vitest-environment`
// docblock means a newly added contract test gets node without anyone
// remembering to annotate it; test/pwaAssets.test.ts opts back into jsdom.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Components branch on __DEMO__ to hide hardware-only controls (OTA, Wi-Fi,
  // relay test), and vite.config.ts supplies it via `define`. Without it here a
  // component test crashes on an undefined global before rendering anything.
  // Pinned false: the tests cover the device build, which is what ships.
  define: {
    __DEMO__: JSON.stringify(false),
  },
  test: {
    globals: false,
    projects: [
      {
        extends: true,
        test: {
          name: "app",
          environment: "jsdom",
          include: ["src/**/*.test.{ts,tsx}"],
          // Attaches jest-dom's matchers and Testing Library's cleanup, neither
          // of which self-registers while `globals` is false.
          setupFiles: ["./src/app/test/setup.ts"],
        },
      },
      {
        extends: true,
        test: {
          name: "node",
          environment: "node",
          include: ["mock-server/**/*.test.ts", "test/**/*.test.ts"],
        },
      },
    ],
  },
});
