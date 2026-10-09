import { expect, test } from "./fixtures";

test("signup redirects with persistent confirmation and allows email login", async ({ page }) => {
  await page.goto("/auth/signup");
  await page.getByLabel("Họ và tên", { exact: true }).fill("Test Student");
  await page.getByLabel("Địa chỉ email", { exact: true }).fill("student@example.test");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Tạo tài khoản", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/login\?registered=1$/);
  await expect(page.getByRole("main").getByRole("status")).toContainText("Tạo tài khoản thành công");
  await page.reload();
  await expect(page.getByRole("main").getByRole("status")).toContainText("email xác nhận");
  await page.getByLabel("Địa chỉ email", { exact: true }).fill("student@example.test");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
});

test("rejected signup reports its error and can be corrected", async ({ page }) => {
  await page.goto("/auth/signup");
  await page.getByLabel("Họ và tên", { exact: true }).fill("Test Student");
  await page.getByLabel("Địa chỉ email", { exact: true }).fill("wrong@example.test");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Tạo tài khoản", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Không thể tạo tài khoản");
  await expect(page).toHaveURL(/\/auth\/signup$/);
  await page.getByLabel("Địa chỉ email", { exact: true }).fill("student@example.test");
  await page.getByRole("button", { name: "Tạo tài khoản", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/login\?registered=1$/);
});
