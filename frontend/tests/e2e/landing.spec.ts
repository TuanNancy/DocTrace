import { expect, test } from "./fixtures";

test("landing demo can pause, replay, switch questions and reveal sources without API calls", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const chatRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/chat") chatRequests.push(request.url());
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Tài liệu của bạn.Câu trả lời rõ ràng.");
  const demo = page.getByRole("region", { name: "Minh họa hỏi đáp PDF" });
  await demo.scrollIntoViewIfNeeded();
  await demo.getByRole("button", { name: "Tạm dừng minh họa" }).click();
  const answer = demo.locator("p[aria-hidden='true']");
  const pausedAnswer = await answer.textContent();
  await expect(demo.getByRole("status")).toHaveText("Đã tạm dừng");
  // Observe more than one streaming interval to verify the visible answer stays paused.
  await page.waitForTimeout(200);
  expect(await answer.textContent()).toBe(pausedAnswer);
  await demo.getByRole("button", { name: "Tiếp tục minh họa" }).click();
  await expect(demo.getByRole("status")).toHaveText("Đã trả lời", { timeout: 10000 });
  await expect(answer).toContainText("Dành một khoảng nghỉ ngắn");

  await demo.getByRole("button", { name: "Phát lại minh họa" }).click();
  await expect(demo.getByRole("status")).toHaveText("Đang trả lời…");
  await demo.getByRole("button", { name: "Tóm tắt tài liệu", exact: true }).click();
  await expect(demo.getByText("Tóm tắt những ý chính của tài liệu này.", { exact: true })).toBeVisible();
  await expect(demo.getByRole("status")).toHaveText("Đã trả lời", { timeout: 10000 });
  await expect(answer).toContainText("Sắp xếp công việc theo mức độ ưu tiên");

  const source = demo.getByRole("button", { name: "Xem nguồn minh họa 1, trang 4" });
  await source.click();
  await expect(demo.getByText("Đoạn trích mẫu · Trang 4")).toBeVisible();
  await demo.getByRole("button", { name: "Đóng nguồn minh họa" }).click();
  await expect(source).toBeFocused();
  expect(chatRequests).toEqual([]);
  await page.screenshot({ path: "test-results/landing-desktop.png", fullPage: true });
});

test("landing respects reduced motion, fits mobile and tablet, and leads into authenticated chat", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const demo = page.getByRole("region", { name: "Minh họa hỏi đáp PDF" });
  await expect(demo.getByRole("status")).toHaveText("Đã trả lời");
  await expect(demo.getByRole("button", { name: /Tạm dừng|Phát lại/ })).toHaveCount(0);
  await demo.getByRole("button", { name: "Tóm tắt tài liệu", exact: true }).click();
  await expect(demo.locator("p[aria-hidden='true']")).toContainText("Sắp xếp công việc theo mức độ ưu tiên");
  await expect(demo.getByRole("status")).toHaveText("Đã trả lời");

  for (const viewport of [{ width: 375, height: 812 }, { width: 812, height: 375 }, { width: 768, height: 1024 }]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole("link", { name: "Dùng thử ngay" }).first()).toBeVisible();
    await page.screenshot({ path: `test-results/landing-${viewport.width}.png`, fullPage: true });
  }

  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Đến nội dung chính" })).toBeFocused();
  await page.getByRole("link", { name: "Dùng thử ngay" }).first().click();
  await expect(page).toHaveURL(/\/auth\/login$/);
});
