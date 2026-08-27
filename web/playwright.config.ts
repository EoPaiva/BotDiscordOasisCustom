import { defineConfig, devices } from "@playwright/test";

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL?.replace(/\/$/, "");

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  reporter: [["list"]],
  use: {
    baseURL: externalBaseURL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  webServer: externalBaseURL ? undefined : {
    command: "npm run build && npm start -- --hostname 127.0.0.1",
    url: "http://127.0.0.1:3000/login",
    reuseExistingServer: true,
    timeout: 180_000,
    env: {
      AUTH_DISCORD_ID: "",
      AUTH_DISCORD_SECRET: "",
      AUTH_SECRET: "playwright-local-secret-not-for-production",
      AUTH_URL: "http://127.0.0.1:3000",
      COMMAND_CENTER_API_URL: "http://127.0.0.1:9",
      VERCEL: "",
      VERCEL_URL: "",
    },
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
    { name: "desktop-firefox", use: { ...devices["Desktop Firefox"] } },
  ],
});
