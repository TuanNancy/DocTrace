import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const WORKSPACE = "44444444-4444-4444-8444-444444444444";
const DOCUMENT = "55555555-5555-4555-8555-555555555555";

async function login(page: Page) {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/auth\/login$/);
  await page.getByLabel("Địa chỉ email", { exact: true }).fill("student@example.test");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}
test.beforeEach(async ({ request }) => { await request.post("http://127.0.0.1:4311/test/reset"); });

test("workspace owners cannot enter the platform console", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("link", { name: "Quản trị", exact: true })).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("không có quyền platform admin");
  await expect(page.getByRole("navigation", { name: "Mục quản trị" })).toHaveCount(0);
});

test("admin reviews metadata, retries, changes plan and confirms asynchronous purge", async ({ page, request }) => {
  await request.post("http://127.0.0.1:4311/test/admin", { data: { allowed: true } });
  await page.setViewportSize({ width: 1440, height: 960 });
  await login(page);
  await page.getByRole("navigation", { name: "Điều hướng chính" }).getByRole("link", { name: "Quản trị", exact: true }).click();
  await expect(page.getByText("0.25 USD", { exact: true })).toBeVisible();
  await expect(page.getByText("2 lượt chưa rõ giá")).toBeVisible();
  await page.screenshot({ path: "test-results/admin-overview.png", fullPage: true });
  await page.getByRole("button", { name: "Tài liệu", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: DOCUMENT });
  await expect(row).toContainText("upload-fixture");
  await expect(row).toContainText("RQ: finished");
  await expect(row.getByRole("link")).toHaveCount(0);
  await row.getByRole("button", { name: "Thử lại", exact: true }).click();
  await expect(row).toContainText("ready");
  await expect(row).toContainText("index-retry");
  await page.getByRole("button", { name: "Workspaces", exact: true }).click();
  await page.getByLabel("Gói của Admin fixture team").selectOption("pro");
  await page.getByRole("button", { name: "Lưu", exact: true }).click();
  await expect(page.getByRole("button", { name: "Lưu", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await page.getByRole("button", { name: "Xóa vĩnh viễn", exact: true }).click();
  const submit = page.getByRole("button", { name: "Bắt đầu xóa", exact: true });
  await expect(submit).toBeDisabled();
  await page.getByLabel("Nhập ID workspace để xác nhận").fill(WORKSPACE);
  await submit.click();
  await expect(page.getByRole("progressbar", { name: `Tiến độ ${WORKSPACE}` })).toBeVisible();
  await expect(page.getByRole("region", { name: "Tiến trình xóa workspace" })).toContainText("0 / 1 đã xóa");
  await page.getByRole("button", { name: "Audit", exact: true }).click();
  await expect(page.getByText("workspace.purge_started", { exact: true })).toBeVisible();
  await expect(page.getByText("document.retry_accepted", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/admin-mobile.png", fullPage: true });
});

test("revoking platform access clears reports on refresh", async ({ page, request }) => {
  await request.post("http://127.0.0.1:4311/test/admin", { data: { allowed: true } });
  await login(page);
  await page.goto("/admin");
  await expect(page.getByText("0.25 USD", { exact: true })).toBeVisible();
  await request.post("http://127.0.0.1:4311/test/admin", { data: { allowed: false } });
  await page.getByRole("button", { name: "Làm mới", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("không có quyền platform admin");
  await expect(page.getByText("0.25 USD", { exact: true })).toHaveCount(0);
});
