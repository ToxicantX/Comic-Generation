import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./console/frontend", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    include: ["console/frontend/**/*.test.ts"],
    restoreMocks: true,
  },
});
