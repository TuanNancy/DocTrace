import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/auth\/login$/);
  await page.getByPlaceholder("Email", { exact: true }).fill("student@example.test");
  await page.getByPlaceholder("Password", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

const file = (name = "a.pdf") => ({ name, mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nfixture") });

test.beforeEach(async ({ request }) => { await request.post("http://127.0.0.1:4311/test/reset"); });

test("library lifecycle, streaming, citations and transient chat across navigation", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await login(page);
  await page.getByRole("link", { name: "Thư viện", exact: false }).first().click();
  await page.getByLabel("Chọn file", { exact: true }).setInputFiles(file());
  await expect(page.getByText("Tải lên thành công")).toBeVisible();
  const row = page.getByTestId("document-row").filter({ hasText: "a.pdf" });
  await expect(row.getByText("Sẵn sàng", { exact: true })).toBeVisible({ timeout: 15000 });
  await row.getByRole("button", { name: "Hỏi đáp", exact: true }).click();
  const input = page.getByLabel("Câu hỏi của bạn");
  await input.fill("Câu hỏi đầu tiên");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(page.getByText("Đang đọc tài liệu", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dừng trả lời" }).click();
  await expect(input).toBeEnabled();
  await expect.poll(async () => (await (await request.get("http://127.0.0.1:4311/test/status")).json()).cancelledStreams).toBe(1);
  await input.fill("Câu hỏi thứ hai");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("button", { name: "Xem nguồn 1, trang 1" }).click();
  await expect(page.getByText("Baymax giúp bạn tra cứu nội dung tài liệu. Mỗi câu trả lời có trích dẫn để đối chiếu với văn bản gốc.")).toBeVisible();
  const popupPromise = page.waitForEvent("popup");
  // Playwright's headless shell downloads PDFs instead of mounting Chrome's viewer.
  const downloadPromise = popupPromise.then((popup) => popup.waitForEvent("download"));
  await page.getByRole("button", { name: "Mở PDF · trang 1" }).click();
  const popup = await popupPromise;
  const download = await downloadPromise;
  expect(download.url()).toMatch(/fixture\.pdf\?signature=fixture#page=1/);
  expect(await download.failure()).toBeNull();
  await popup.close();

  await page.getByRole("navigation", { name: "Điều hướng chính" }).getByRole("link", { name: /Thư viện/ }).click();
  await expect(row).toBeVisible();
  await page.getByRole("link", { name: "Hỏi đáp tài liệu", exact: true }).click();
  await expect(page.getByText("Câu hỏi thứ hai", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Câu hỏi thứ hai", { exact: true })).not.toBeVisible();
  await expect(page.getByRole("button", { name: /a.pdf/ })).toBeVisible();
  await page.getByRole("button", { name: /a.pdf/ }).click();
  await expect(input).toBeEnabled();
  await page.getByRole("navigation", { name: "Điều hướng chính" }).getByRole("link", { name: /Thư viện/ }).click();
  await row.getByRole("button", { name: "Xóa a.pdf", exact: true }).click();
  await page.getByRole("button", { name: "Xóa tài liệu", exact: true }).click();
  await expect(row).not.toBeVisible({ timeout: 15000 });
  await page.getByRole("link", { name: "Hỏi đáp tài liệu", exact: true }).click();
  await expect(input).toBeDisabled();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByRole("link", { name: "Hỏi đáp tài liệu", exact: true })).toHaveAttribute("aria-current", "page");
  await page.screenshot({ path: "test-results/soft-glass-chat-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/login$/);
});

test("failed documents can be filtered, retried and selected", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await login(page);
  await page.getByRole("navigation", { name: "Điều hướng chính" }).getByRole("link", { name: /Thư viện/ }).click();
  await page.getByLabel("Chọn file", { exact: true }).setInputFiles(file("error.pdf"));
  const row = page.getByTestId("document-row");
  await expect(row.getByText("Lỗi xử lý", { exact: true })).toBeVisible({ timeout: 15000 });
  await page.getByLabel("Lọc trạng thái").selectOption("error");
  await expect(row).toBeVisible();
  await page.getByLabel("Tìm tài liệu").fill("không tồn tại");
  await expect(row).not.toBeVisible();
  await page.getByLabel("Tìm tài liệu").clear();
  await row.getByRole("button", { name: "Thử lại", exact: true }).click();
  await page.getByLabel("Lọc trạng thái").selectOption("all");
  await expect(row.getByText("Sẵn sàng", { exact: true })).toBeVisible({ timeout: 15000 });
  await page.screenshot({ path: "test-results/soft-glass-library-desktop.png", fullPage: true });
});

test("mobile navigation and citation drawers remain usable without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole("button", { name: "Mở điều hướng" }).click();
  await page.getByRole("dialog").getByRole("link", { name: /Thư viện/ }).click();
  await page.getByLabel("Chọn file", { exact: true }).setInputFiles(file("mobile.pdf"));
  const row = page.getByTestId("document-row");
  await expect(row.getByText("Sẵn sàng", { exact: true })).toBeVisible({ timeout: 15000 });
  await row.getByRole("button", { name: "Hỏi đáp", exact: true }).click();
  await page.getByLabel("Câu hỏi của bạn").fill("Tóm tắt tài liệu");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await page.getByRole("button", { name: "Xem nguồn 1, trang 1" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByText(/Baymax giúp bạn tra cứu nội dung tài liệu/)).toBeVisible();
  await page.getByRole("button", { name: "Đóng bảng", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/soft-glass-chat-mobile.png", fullPage: true });
});
