import { expect, test } from "@playwright/test";

test("anonymous visitors are redirected and the bundled logo loads", async ({ page }) => {
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/auth\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  const logo = page.getByAltText("Baymax logo").first();
  await expect(logo).toBeVisible();
  await expect.poll(() => logo.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
});

test("login, reload session, upload, stream sources, recover from disconnect, and logout", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/auth/login");
  await page.getByPlaceholder("Email", { exact: true }).fill("demo@example.com");
  await page.getByPlaceholder("Password", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page.getByText("Invalid login credentials")).toBeVisible();
  await page.getByPlaceholder("Password", { exact: true }).fill("correct-password");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.reload();
  await expect(page.getByText("demo@example.com", { exact: true })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({
    name: "policy.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nfixture"),
  });
  await expect(page.getByText("Tải lên thành công", { exact: true })).toBeVisible();
  const input = page.getByPlaceholder("Nhập tin nhắn của bạn...");
  await input.fill("Có bao nhiêu ngày nghỉ phép?");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(page.getByText("Mười hai ngày nghỉ phép.", { exact: true })).toBeVisible();
  await expect(page.getByText("policy.pdf").last()).toBeVisible();
  await expect(input).toBeEnabled();

  await input.fill("disconnect");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(page.getByText(/Kết nối chat bị ngắt/)).toBeVisible();
  await expect(input).toBeEnabled();

  await page.getByRole("button", { name: /Demo Tester/ }).click();
  await page.getByRole("menuitem", { name: /Đăng xuất/ }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/auth\/login$/);
  expect(errors).toEqual([]);
});
