import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const PERSONAL = "11111111-1111-4111-8111-111111111111";
const TEAM = "33333333-3333-4333-8333-333333333333";
const file = { name: "workspace.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nfixture") };

async function login(page: Page) {
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/auth\/login$/);
  await page.getByLabel("Địa chỉ email", { exact: true }).fill("student@example.test");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

test.beforeEach(async ({ request }) => { await request.post("http://127.0.0.1:4311/test/reset"); });

test("switching workspace isolates the library and restores it on switch back", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await login(page);
  const switcher = page.getByLabel("Chọn không gian làm việc");
  await expect(switcher).toHaveValue(PERSONAL);
  await expect(switcher.locator("option")).toHaveCount(2);

  await page.getByRole("navigation", { name: "Điều hướng chính" })
    .getByRole("link", { name: /Thư viện/ }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await page.getByLabel("Chọn file", { exact: true }).setInputFiles(file);
  const row = page.getByTestId("document-row").filter({ hasText: "workspace.pdf" });
  await expect(row.getByText("Sẵn sàng", { exact: true })).toBeVisible({ timeout: 15000 });

  await switcher.selectOption(TEAM);
  await expect(page.getByText("Thư viện đang chờ tài liệu đầu tiên")).toBeVisible();
  await expect(page.getByTestId("document-row")).toHaveCount(0);
  await expect(page.getByText("Đã chuyển sang “Nhóm học tập”.")).toBeVisible();

  await switcher.selectOption(PERSONAL);
  await expect(page.getByTestId("document-row").filter({ hasText: "workspace.pdf" })).toBeVisible();
});
