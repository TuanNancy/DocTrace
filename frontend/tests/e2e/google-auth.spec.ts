import { createHash } from "node:crypto";
import { expect, GOOGLE_SCRIPT, test } from "./fixtures";

const tokenUrl = "http://127.0.0.1:4311/auth/v1/token?grant_type=id_token";

test("Google ID token login creates SSR cookies and survives protected-route reloads", async ({ page, context }) => {
  const legacyRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/auth/v1/authorize") legacyRequests.push(request.url());
  });
  const response = await page.goto("/auth/login");
  expect(response?.headers()["cross-origin-opener-policy"]).toBe("same-origin-allow-popups");
  const button = page.getByRole("button", { name: "Tiếp tục với Google", exact: true });
  await expect(button).toHaveAttribute("data-client-id", "e2e-placeholder.apps.googleusercontent.com");
  await expect(button).toHaveAttribute("data-ux-mode", "popup");
  const hashedNonce = await button.getAttribute("data-nonce");
  const exchange = page.waitForRequest((request) => request.url() === tokenUrl && request.method() === "POST");
  await button.click();
  const credentials = (await exchange).postDataJSON();
  expect(credentials.provider).toBe("google");
  expect(credentials.id_token).toBe(`fixture-google:${hashedNonce}`);
  expect(createHash("sha256").update(credentials.nonce).digest("hex")).toBe(hashedNonce);
  await expect(page).toHaveURL(/\/chat$/);
  expect((await context.cookies()).some((cookie) => cookie.name.startsWith("sb-") && cookie.name.includes("auth-token"))).toBe(true);
  await page.reload();
  await expect(page.getByRole("button", { name: "Đăng xuất", exact: true })).toBeVisible();
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/documents$/);
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/login$/);
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/auth\/login$/);
  expect(legacyRequests).toEqual([]);
});

test("failed ID token exchange is retryable with a fresh nonce", async ({ page }) => {
  await page.route(tokenUrl, (route) => route.request().method() === "OPTIONS" ? route.continue() : route.fulfill({
    status: 400, contentType: "application/json",
    headers: { "Access-Control-Allow-Origin": "http://localhost:4310" },
    body: JSON.stringify({ error: "invalid_grant", error_description: "Invalid fixture token" }),
  }));
  await page.goto("/auth/login");
  const button = page.getByRole("button", { name: "Tiếp tục với Google", exact: true });
  await expect(button).toBeVisible();
  const firstNonce = await button.getAttribute("data-nonce");
  await button.click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Không thể đăng nhập bằng Google. Vui lòng thử lại.");
  await expect(button).toBeVisible();
  expect(await button.getAttribute("data-nonce")).not.toBe(firstNonce);
  await expect(page).toHaveURL(/\/auth\/login$/);
  await page.unroute(tokenUrl);
  await button.click();
  await expect(page).toHaveURL(/\/chat$/);
});

test("blocked Google SDK leaves email login usable", async ({ page }) => {
  await page.route(GOOGLE_SCRIPT, (route) => route.abort());
  await page.goto("/auth/login");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Không tải được đăng nhập Google");
  await page.getByLabel("Địa chỉ email", { exact: true }).fill("student@example.test");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
});
