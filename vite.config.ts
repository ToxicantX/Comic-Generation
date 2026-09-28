import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
    __VUE_OPTIONS_API__: "false",
    __VUE_PROD_DEVTOOLS__: "false",
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
  },
  build: {
    outDir: fileURLToPath(new URL("./console/static/vue", import.meta.url)),
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: false,
    lib: {
      entry: fileURLToPath(new URL("./console/frontend/main.ts", import.meta.url)),
      name: "ComicConsoleUI",
      formats: ["iife"],
      fileName: () => "console-ui.js",
      cssFileName: "console-ui",
    },
  },
});
