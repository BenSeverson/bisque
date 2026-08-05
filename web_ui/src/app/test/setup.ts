/**
 * Setup for the jsdom ("app") vitest project.
 *
 * Two jobs, both of which exist because `globals: false` is set in
 * vitest.config.ts: jest-dom's matchers have to be attached to the `expect`
 * tests import from vitest, and Testing Library's automatic cleanup — which it
 * only registers when it can see a global `afterEach` — has to be wired by hand.
 * Without the cleanup, mounted components leak between tests in a file and a
 * `getByRole` matches a widget belonging to an earlier one.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);

/* Browser APIs jsdom does not implement, which the Radix primitives the UI is
   built from call unconditionally. Each one throws rather than degrading, so
   without these a component test fails on layout measurement before it can
   assert on anything. */
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (!("matchMedia" in window)) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// Pointer capture and scrollIntoView are used by Radix's Select and Dialog.
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};
