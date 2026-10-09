import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  forbidOnly: !!process.env.CI,
  workers: 1,
  timeout: 60000,
  reporter: process.env.CI ? [["line"], ["github"]] : "list",
  use: {
    baseURL: "http://localhost:4310",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node tests/fixtures/services.mjs",
      url: "http://127.0.0.1:4311/health",
      reuseExistingServer: false,
    },
    {
      // Compile every route before testing: a cold next dev /chat compilation
      // can exceed the login assertion timeout on CI. Both commands inherit
      // these fixture values because NEXT_PUBLIC_* is embedded at build time.
      command: "npm run build && npm run start -- --hostname 127.0.0.1 --port 4310",
      url: "http://localhost:4310",
      timeout: 240000,
      reuseExistingServer: false,
      env: {
        NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:4311",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY: "sb_publishable_e2e_placeholder",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "",
        NEXT_PUBLIC_SITE_URL: "http://localhost:4310",
        NEXT_PUBLIC_GOOGLE_CLIENT_ID: "e2e-placeholder.apps.googleusercontent.com",
        NEXT_PUBLIC_API_URL: "http://127.0.0.1:4311",
      },
    },
  ],
});
