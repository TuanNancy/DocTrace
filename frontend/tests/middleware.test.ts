import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { updateSession } from "../src/lib/middleware";

const mocks = vi.hoisted(() => ({ createServerClient: vi.fn(), getUser: vi.fn() }));
vi.mock("@supabase/ssr", () => ({ createServerClient: mocks.createServerClient }));

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", "test-publishable-key");
  mocks.getUser.mockResolvedValue({ data: { user: null }, error: null });
  mocks.createServerClient.mockReturnValue({ auth: { getUser: mocks.getUser } });
});
afterEach(() => { vi.resetAllMocks(); vi.unstubAllEnvs(); });

it("redirects anonymous chat requests to login", async () => {
  const response = await updateSession(new NextRequest("https://app.example.com/chat?anything=1"));
  expect(response.headers.get("location")).toBe("https://app.example.com/auth/login");
  expect(response.headers.get("cache-control")).toContain("no-store");
});

it.each(["/auth/login", "/auth/signup", "/auth/callback?code=abc", "/auth/auth-code-error"])("keeps %s public without a redirect loop", async (path) => {
  const response = await updateSession(new NextRequest(`https://app.example.com${path}`));
  expect(response.headers.get("location")).toBeNull();
});

it("preserves refreshed cookies on both the request and successful response", async () => {
  const request = new NextRequest("https://app.example.com/chat");
  mocks.getUser.mockImplementation(async () => {
    const options = mocks.createServerClient.mock.calls[0][2];
    options.cookies.setAll([{ name: "sb-auth-token", value: "refreshed", options: { path: "/", sameSite: "lax" } }], { "Cache-Control": "private, no-store" });
    return { data: { user: { id: "user-1" } }, error: null };
  });
  const response = await updateSession(request);
  expect(response.headers.get("location")).toBeNull();
  expect(request.cookies.get("sb-auth-token")?.value).toBe("refreshed");
  expect(response.cookies.get("sb-auth-token")?.value).toBe("refreshed");
});

it("keeps clearing cookies when an expired session redirects to login", async () => {
  mocks.getUser.mockImplementation(async () => {
    const options = mocks.createServerClient.mock.calls[0][2];
    options.cookies.setAll([{ name: "sb-auth-token", value: "", options: { path: "/", maxAge: 0 } }], {});
    return { data: { user: null }, error: new Error("Expired") };
  });
  const response = await updateSession(new NextRequest("https://app.example.com/chat"));
  expect(response.headers.get("location")).toContain("/auth/login");
  expect(response.cookies.get("sb-auth-token")?.maxAge).toBe(0);
});
