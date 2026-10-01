import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET } from "../src/app/auth/callback/route";
import { signupAction } from "../src/app/auth/actions";

const auth = vi.hoisted(() => ({ exchangeCodeForSession: vi.fn(), signUp: vi.fn(), signOut: vi.fn() }));
vi.mock("@/lib/server", () => ({ createClient: async () => ({ auth }) }));
beforeEach(() => {
  auth.exchangeCodeForSession.mockResolvedValue({ error: null });
  auth.signUp.mockResolvedValue({ data: { session: null }, error: null });
  vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://app.example.com");
});
afterEach(() => { vi.resetAllMocks(); vi.unstubAllEnvs(); });

it.each(["https://evil.example", "//evil.example", "/\\evil.example", "/\n/evil.example"])("does not redirect off-site after OAuth: %s", async (next) => {
  const response = await GET(new Request(`https://app.example.com/auth/callback?code=abc&next=${encodeURIComponent(next)}`));
  expect(response.headers.get("location")).toBe("https://app.example.com/");
});

it("exchanges the authorization code and redirects to chat without caching", async () => {
  const response = await GET(new Request("https://app.example.com/auth/callback?code=abc&next=/chat"));
  expect(auth.exchangeCodeForSession).toHaveBeenCalledWith("abc");
  expect(response.headers.get("location")).toBe("https://app.example.com/chat");
  expect(response.headers.get("cache-control")).toContain("no-store");
});

it("routes failed code exchanges to the auth error page", async () => {
  auth.exchangeCodeForSession.mockResolvedValue({ error: new Error("Expired code") });
  const response = await GET(new Request("https://app.example.com/auth/callback?code=expired"));
  expect(response.headers.get("location")).toBe("https://app.example.com/auth/auth-code-error");
});

it("keeps the PKCE verifier until email confirmation, using the configured site URL", async () => {
  const form = new FormData();
  form.set("email", "demo@example.com");
  form.set("password", "test-password");
  form.set("full_name", "Demo");
  const result = await signupAction({ status: "idle", message: "" }, form);
  expect(result.status).toBe("success");
  expect(auth.signUp).toHaveBeenCalledWith(expect.objectContaining({
    options: { data: { full_name: "Demo" }, emailRedirectTo: "https://app.example.com/auth/callback?next=/chat" },
  }));
  expect(auth.signOut).not.toHaveBeenCalled();
});
