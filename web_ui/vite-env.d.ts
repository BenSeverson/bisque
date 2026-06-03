/// <reference types="vite/client" />

declare const __APP_VERSION__: string;

// True only in the static GitHub Pages demo build (BISQUE_DEMO=true); enables
// the in-browser mock backend and demo-only UI. Constant-folded to `false` in
// the firmware build so the simulator is tree-shaken out.
declare const __DEMO__: boolean;
