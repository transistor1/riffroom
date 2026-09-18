import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:8765",
    launchOptions: {
      executablePath:
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      args: ["--autoplay-policy=no-user-gesture-required"],
    },
    viewport: { width: 1440, height: 1100 },
    screenshot: "only-on-failure",
  },
  workers: 1,
});
