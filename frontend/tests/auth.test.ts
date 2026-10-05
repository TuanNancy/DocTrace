// @vitest-environment node
import type { CookieOptions } from "@supabase/ssr";
import { NextRequest } from "next/server";
import { beforeEach, expect, it, vi } from "vitest";
import { updateSession } from "@/lib/supabase/middleware";
import { getSupabaseConfig } from "@/lib/supabase/config";

type CookieAdapter = {
  getAll: () => { name: string; value: string }[];
  setAll: (cookies: { name: string; value: string; options?: CookieOptions }[], headers: Record<string, string>) => void;
};
const auth = vi.hoisted(() => ({
  user: null as { id: string } | null,
  error: null as { message: string } | null,
  refresh: false,
  getUser: vi.fn(),
}));

vi.mock("@supabase/ssr", () => ({
  createServerClient: (_url: string, _key: string, { cookies }: { cookies: CookieAdapter }) => ({
    auth: {
      getUser: async () => {
        auth.getUser();
        if (auth.refresh) {
          cookies.setAll([{ name: "session", value: "refreshed", options: { path: "/", sameSite: "lax" } }], { "Cache-Control": "private, no-store" });
        }
        return { data: { user: auth.user }, error: auth.error };
      },
    },
  }),
}));

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", "test-public-key");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "");
  auth.user = null;
  auth.error = null;
  auth.refresh = false;
  auth.getUser.mockReset();
});

it("validates Auth and redirects an unverified session away from chat", async () => {
  auth.error = { message: "Invalid token" };
  const response = await updateSession(new NextRequest("https://app.example.test/chat?private=value", {
    headers: { Cookie: "session=forged" },
  }));
  expect(auth.getUser).toHaveBeenCalledOnce();
  expect(response.status).toBe(307);
  expect(response.headers.get("location")).toBe("https://app.example.test/auth/login");
  expect(response.headers.get("cache-control")).toBe("private, no-store");
});

it("propagates refreshed cookies to the request and browser response", async () => {
  auth.user = { id: "user-a" };
  auth.refresh = true;
  const request = new NextRequest("https://app.example.test/chat");
  const response = await updateSession(request);
  expect(request.cookies.get("session")?.value).toBe("refreshed");
  expect(response.cookies.get("session")?.value).toBe("refreshed");
  expect(response.headers.get("location")).toBeNull();
  expect(response.headers.get("cache-control")).toBe("private, no-store");
});

it("keeps cookie updates on an auth redirect", async () => {
  auth.refresh = true;
  const response = await updateSession(new NextRequest("https://app.example.test/chat"));
  expect(response.status).toBe(307);
  expect(response.cookies.get("session")?.value).toBe("refreshed");
});

it("protects the document library using the same verified session", async () => {
  const response = await updateSession(new NextRequest("https://app.example.test/documents"));
  expect(response.status).toBe(307);
  expect(response.headers.get("location")).toBe("https://app.example.test/auth/login");
});

it("allows visitors to reach the public login page", async () => {
  const response = await updateSession(new NextRequest("https://app.example.test/auth/login"));
  expect(response.status).toBe(200);
  expect(response.headers.get("location")).toBeNull();
});

it("supports a legacy anon key but fails clearly when configuration is missing", () => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", "");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "legacy-public-key");
  expect(getSupabaseConfig().key).toBe("legacy-public-key");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
  expect(getSupabaseConfig).toThrow("Thiếu NEXT_PUBLIC_SUPABASE_URL");
});
