import { defineConfig, devices } from "@playwright/test";

const appUrl = "http://127.0.0.1:3005";
const serviceUrl = "http://127.0.0.1:8999";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60000,
  expect: { timeout: 15000 },
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: { baseURL: appUrl, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    { command: "node tests/e2e/services.mjs", url: `${serviceUrl}/health`, reuseExistingServer: false },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3005",
      url: appUrl,
      timeout: 120000,
      reuseExistingServer: false,
      env: {
        NEXT_PUBLIC_API_URL: serviceUrl,
        NEXT_PUBLIC_SUPABASE_URL: serviceUrl,
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY: "e2e-public-key",
        NEXT_PUBLIC_SITE_URL: appUrl,
        NEXT_PUBLIC_DEMO_MODE: "false",
      },
    },
  ],
});
