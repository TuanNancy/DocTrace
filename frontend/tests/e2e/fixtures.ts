import { test as base, expect, type Page } from "@playwright/test";
import { resolve } from "node:path";

export const GOOGLE_SCRIPT = "https://accounts.google.com/gsi/client*";

/**
 * The client-side URL changes before the previous route unmounts. Both /chat
 * and /documents render a "Chọn file" input, so wait for library content
 * before selecting a file; otherwise Playwright can attach it to the outgoing
 * page and the upload never starts.
 */
export async function expectLibrary(page: Page) {
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByRole("heading", { name: "Mọi tài liệu, một nơi." })).toBeVisible();
}

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route(GOOGLE_SCRIPT, (route) => route.fulfill({
      path: resolve("tests/fixtures/google-identity.js"), contentType: "application/javascript",
    }));
    await use(page);
  },
});

export { expect };
