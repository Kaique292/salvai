import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/ui/**/*.test.js"],
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["src/ui/app.js", "src/ui/mobile/mobile.js"],
      reporter: ["text", "json-summary"],
      reportsDirectory: "build/coverage-js",
      thresholds: { lines: 100, functions: 100, branches: 100, statements: 100 },
    },
  },
});
