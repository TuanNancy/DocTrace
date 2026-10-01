import { expect, test } from "@playwright/test";

test("login, PDF upload, immediate SSE, cancellation, document replacement and logout", async ({ page, request }) => {
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/auth\/login$/);
  await page.getByPlaceholder("Email", { exact: true }).fill("student@example.test");
  await page.getByPlaceholder("Password", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  const file = { name: "a.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nfixture") };
  await page.getByLabel("Chọn file", { exact: true }).setInputFiles(file);
  await expect(page.getByText("Tải lên thành công")).toBeVisible();
  const input = page.getByPlaceholder("Nhập tin nhắn của bạn...");
  await input.fill("Câu hỏi đầu tiên");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(page.getByText("Đang đọc tài liệu", { exact: true })).toBeVisible();
  await expect(input).toBeDisabled();
  await page.getByRole("button", { name: "Xóa tin nhắn" }).click();
  await expect(input).toBeEnabled();
  await expect.poll(async () => (await (await request.get("http://127.0.0.1:4311/test/status")).json()).cancelledStreams).toBe(1);

  await input.fill("Câu hỏi thứ hai");
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(page.getByText("Đang đọc tài liệu: nội dung kiểm thử.", { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await page.getByLabel("Chọn file khác").setInputFiles({ ...file, name: "b.pdf" });
  await expect(page.getByText("b.pdf", { exact: true })).toBeVisible();
  await expect(page.getByText("Câu hỏi thứ hai", { exact: true })).not.toBeVisible();

  await page.getByRole("button", { name: /Test Student/ }).click();
  await page.getByRole("button", { name: "Bật tối" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(input).toHaveCSS("color", "rgb(241, 245, 249)");
  await expect(input.locator("..")).toHaveCSS("background-color", "rgb(30, 41, 59)");
  await page.getByRole("menuitem", { name: "Đăng xuất" }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/auth\/login$/);
});
