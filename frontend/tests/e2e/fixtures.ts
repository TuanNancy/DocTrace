import { test as base, expect } from "@playwright/test";
import { resolve } from "node:path";

export const GOOGLE_SCRIPT = "https://accounts.google.com/gsi/client*";

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route(GOOGLE_SCRIPT, (route) => route.fulfill({
      path: resolve("tests/fixtures/google-identity.js"), contentType: "application/javascript",
    }));
    await use(page);
  },
});

export { expect };
